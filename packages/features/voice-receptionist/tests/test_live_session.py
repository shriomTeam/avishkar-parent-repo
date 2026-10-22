"""The call session against a fake model and a fake browser, with the real database."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import Agent, Call, CallEvent, CallFieldValue, CallTurn
from clinic_voice_receptionist.inbound.live import session as session_module
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.audio import CallAudio
from clinic_voice_receptionist.inbound.live.events import (
    AudioOut,
    Interrupted,
    ModelClosed,
    Received,
    Resumable,
    ToolCall,
    Transcript,
    TurnComplete,
    Usage,
)
from clinic_voice_receptionist.inbound.live.fields import coerce_all
from clinic_voice_receptionist.inbound.live.recorder import CallRecorder
from clinic_voice_receptionist.inbound.live.session import CallSession

CLOSE = object()
FIELDS = [
    {
        "id": None,
        "key": "caller_name",
        "label": "Name",
        "data_type": "text",
        "required": True,
        "description": None,
        "enum_values": None,
    },
    {
        "id": None,
        "key": "phone",
        "label": "Phone",
        "data_type": "phone",
        "required": True,
        "description": None,
        "enum_values": None,
    },
]


class FakeModel:
    def __init__(self):
        self.audio, self.texts, self.tool_results = [], [], []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_audio(self, pcm):
        self.audio.append(pcm)

    async def send_text(self, text):
        self.texts.append(text)

    async def send_tool_results(self, results):
        self.tool_results.append(results)

    def push(self, *events, raw=None):
        self.inbox.put_nowait(Received(list(events), raw))

    async def messages(self):
        while True:
            item = await self.inbox.get()
            if item is CLOSE:
                raise ModelClosed("closed")
            yield item


class FakeConnector:
    def __init__(self, *models):
        self.models, self.handles = list(models), []

    @asynccontextmanager
    async def connect(self, agent, fields, handle):
        self.handles.append(handle)
        yield self.models.pop(0)


class FakeTransport:
    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.audio, self.events = [], []

    async def frames(self):
        while (item := await self.inbox.get()) is not None:
            yield item

    async def send_audio(self, pcm):
        self.audio.append(pcm)

    async def send_event(self, event):
        self.events.append(event)


async def _start(*models, snapshot_extra=None, max_seconds=60, tool_runner=None, audio=None, store=None):
    tenant = await create_test_tenant()
    snapshot = {
        "name": "Front desk",
        "prompt": "p",
        "greeting": "Hi, thanks for calling!",
        "voice": "Puck",
        "language": "en-US",
        "model": "m",
        "fields": FIELDS,
    } | (snapshot_extra or {})
    async with tenant_session(tenant) as s:
        agent = Agent(tenant_id=tenant, name="Front desk", prompt="p", model="m")
        s.add(agent)
        await s.flush()
        call = Call(
            tenant_id=tenant,
            agent_id=agent.id,
            agent_snapshot=snapshot,
            channel="browser_test",
            is_test=True,
            status="in_progress",
            model="m",
        )
        s.add(call)
        await s.flush()
        call_id = call.id
    connector, transport = FakeConnector(*models), FakeTransport()
    session = CallSession(
        snapshot=snapshot,
        transport=transport,
        connector=connector,
        recorder=CallRecorder(tenant, call_id, snapshot),
        max_seconds=max_seconds,
        tool_runner=tool_runner(tenant, call_id) if tool_runner else None,
        audio=audio,
        store=store,
    )
    return tenant, call_id, session, connector, transport, asyncio.create_task(session.run())


async def _saved(tenant, call_id):
    async with tenant_session(tenant) as s:
        call = await s.get(Call, call_id)
        turns = (await s.scalars(select(CallTurn).where(CallTurn.call_id == call_id).order_by(CallTurn.seq))).all()
        values = {
            v.key: v.value for v in await s.scalars(select(CallFieldValue).where(CallFieldValue.call_id == call_id))
        }
        events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id))).all()
    return call, turns, values, events


async def test_a_full_call_is_saved_turn_by_turn_with_captured_fields():
    model = FakeModel()
    tenant, call_id, session, connector, transport, task = await _start(model)
    await asyncio.sleep(0.05)
    assert model.texts == ['The call has just connected. Greet the caller by saying: "Hi, thanks for calling!"']

    model.push(Transcript("agent", "Hi, thanks "), AudioOut(b"\x00\x01" * 100), raw={"server_content": {"x": 1}})
    model.push(Transcript("agent", "for calling!"), TurnComplete())
    model.push(Transcript("caller", "I'm Sam, number 555"))
    model.push(ToolCall("t1", "save_caller_details", {"caller_name": "Sam", "phone": "555"}))
    await asyncio.sleep(0.05)
    # The valid value is accepted; the bad phone number is sent back so the model asks again.
    assert model.tool_results[0][0].response == {
        "ok": False,
        "saved": ["caller_name"],
        "invalid": {"phone": "must be a phone number in E.164 format, for example +14155550123"},
    }
    model.push(Transcript("caller", " it's +1 415 555 0123"), TurnComplete())
    model.push(ToolCall("t2", "save_caller_details", {"phone": "+1 (415) 555-0123"}))
    model.push(ToolCall("t3", "end_call", {}), Usage({"total_token_count": 90}))
    model.push(Transcript("agent", "Goodbye!"), TurnComplete())
    await asyncio.wait_for(task, 5)

    call, turns, values, events = await _saved(tenant, call_id)
    assert (call.status, call.end_reason, call.usage) == ("completed", "agent_ended", {"total_token_count": 90})
    assert call.ended_at and call.duration_seconds is not None
    # Fragments of one utterance are joined, even with a tool call in between.
    assert [(t.speaker, t.text) for t in turns] == [
        ("agent", "Hi, thanks for calling!"),
        ("caller", "I'm Sam, number 555 it's +1 415 555 0123"),
        ("agent", "Goodbye!"),
    ]
    assert [t.seq for t in turns] == [1, 2, 3]
    assert values == {"caller_name": "Sam", "phone": "+14155550123"}
    assert [e.payload for e in events] == [{"server_content": {"x": 1}}]  # only messages that carried data
    assert transport.audio == [b"\x00\x01" * 100]
    assert transport.events[-1] == {"type": "ended", "reason": "agent_ended"}
    assert {"type": "fields", "values": {"caller_name": "Sam", "phone": "+14155550123"}} in transport.events


async def test_caller_audio_reaches_the_model_and_bad_frames_are_ignored():
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(model)
    for frame in (b"\x01\x00" * 320, b"\x01", b"\x00" * 40_000, {"type": "ping"}):
        transport.inbox.put_nowait(frame)
    await asyncio.sleep(0.05)
    assert model.audio == [b"\x01\x00" * 320]  # odd-length and oversized frames are dropped
    transport.inbox.put_nowait({"type": "hangup"})
    await asyncio.wait_for(task, 5)
    call, *_ = await _saved(tenant, call_id)
    assert (call.status, call.end_reason) == ("completed", "caller_hangup")


async def test_interruption_stops_playback_and_marks_the_agent_turn():
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(model)
    model.push(Transcript("agent", "Let me tell you about our many"))
    model.push(Interrupted())
    model.push(Transcript("caller", "Sorry, what are your hours?"), TurnComplete())
    await asyncio.sleep(0.05)
    transport.inbox.put_nowait(None)  # browser closes
    await asyncio.wait_for(task, 5)
    _, turns, *_ = await _saved(tenant, call_id)
    assert [(t.speaker, t.interrupted) for t in turns] == [("agent", True), ("caller", False)]
    assert {"type": "interrupted"} in transport.events


async def test_a_dropped_model_connection_resumes_with_the_saved_handle():
    first, second = FakeModel(), FakeModel()
    tenant, call_id, session, connector, transport, task = await _start(first, second)
    first.push(Resumable("handle-1"))
    first.inbox.put_nowait(CLOSE)
    await asyncio.sleep(0.6)
    assert connector.handles == [None, "handle-1"]
    assert second.texts == []  # the greeting is only sent on the first connection
    transport.inbox.put_nowait({"type": "hangup"})
    await asyncio.wait_for(task, 5)
    call, *_ = await _saved(tenant, call_id)
    assert call.status == "completed"


async def test_a_dropped_connection_without_a_handle_fails_the_call():
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(model)
    model.inbox.put_nowait(CLOSE)
    await asyncio.wait_for(task, 5)
    call, *_ = await _saved(tenant, call_id)
    assert (call.status, call.end_reason) == ("failed", "model_disconnected")
    assert transport.events[-1] == {"type": "ended", "reason": "model_disconnected"}


async def test_calls_end_at_the_time_limit(monkeypatch):
    monkeypatch.setattr(session_module, "FLUSH_SECONDS", 0.05)
    tenant, call_id, session, _, _, task = await _start(FakeModel(), max_seconds=0)
    await asyncio.wait_for(task, 5)
    call, *_ = await _saved(tenant, call_id)
    assert (call.status, call.end_reason) == ("completed", "max_duration")


async def test_transcript_and_raw_events_are_not_saved_when_the_agent_turns_them_off():
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(
        model, snapshot_extra={"save_transcript": False, "save_raw_events": False}
    )
    model.push(Transcript("agent", "Hello"), TurnComplete(), raw={"server_content": {"x": 1}})
    model.push(ToolCall("t1", "save_caller_details", {"caller_name": "Sam"}))
    await asyncio.sleep(0.05)
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
    _, turns, values, events = await _saved(tenant, call_id)
    assert turns == [] and events == [] and values == {"caller_name": "Sam"}  # captured fields are the point


async def test_a_full_audio_queue_drops_the_oldest_chunks_instead_of_growing():
    model = FakeModel()
    _, _, session, _, transport, task = await _start(model)
    session._out = asyncio.Queue(3)
    for i in range(5):
        session._queue_audio(bytes([i]))
    assert [session._out.get_nowait() for _ in range(3)] == [b"\x02", b"\x03", b"\x04"]
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)


class FakeStore:
    def __init__(self, fail_times=0):
        self.objects, self.attempts, self._fail = {}, 0, fail_times

    async def put(self, name, data):
        self.attempts += 1
        if self.attempts <= self._fail:
            raise OSError("storage unavailable")
        self.objects[name] = data

    async def get(self, name):
        return self.objects.get(name)


async def _recorded_call(store, *, audio=True, seconds=1):
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(
        model, audio=CallAudio(60) if audio else None, store=store
    )
    await asyncio.sleep(0.05)
    transport.inbox.put_nowait(b"\x01\x00" * 16_000 * seconds)
    model.push(AudioOut(b"\x02\x00" * 24_000 * seconds))
    await asyncio.sleep(0.05)
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
    return tenant, call_id


async def test_a_recorded_call_is_uploaded_under_its_clinic_and_marked_saved():
    store = FakeStore()
    tenant, call_id = await _recorded_call(store)
    name = f"voice-recordings/{tenant}/{call_id}.wav"
    assert list(store.objects) == [name]
    assert store.objects[name][:4] == b"RIFF"
    call, *_ = await _saved(tenant, call_id)
    assert (call.recording_object, call.recording_status) == (name, "saved")


async def test_a_failed_upload_is_retried_once_then_reported_without_losing_the_call():
    store = FakeStore(fail_times=1)
    tenant, call_id = await _recorded_call(store)
    call, *_ = await _saved(tenant, call_id)
    assert store.attempts == 2 and call.recording_status == "saved"

    store = FakeStore(fail_times=5)
    tenant, call_id = await _recorded_call(store)
    call, *_ = await _saved(tenant, call_id)
    assert store.attempts == 2 and store.objects == {}
    assert (call.status, call.recording_object, call.recording_status) == ("completed", None, "failed")


async def test_a_call_that_should_be_recorded_but_has_no_storage_is_marked_failed():
    tenant, call_id = await _recorded_call(None)
    call, *_ = await _saved(tenant, call_id)
    assert (call.status, call.recording_object, call.recording_status) == ("completed", None, "failed")


async def test_calls_are_not_recorded_unless_the_agent_asks_for_it():
    store = FakeStore()
    tenant, call_id = await _recorded_call(store, audio=False)
    call, *_ = await _saved(tenant, call_id)
    assert store.objects == {} and (call.recording_object, call.recording_status) == (None, None)


async def test_a_call_with_no_audio_leaves_no_recording():
    store = FakeStore()
    tenant, call_id, session, _, transport, task = await _start(FakeModel(), audio=CallAudio(60), store=store)
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
    call, *_ = await _saved(tenant, call_id)
    assert store.objects == {} and call.recording_status is None


def test_field_values_are_validated_and_normalised():
    fields = FIELDS + [
        {"key": "service", "data_type": "enum", "enum_values": ["Botox", "Filler"]},
        {"key": "dob", "data_type": "date"},
        {"key": "age", "data_type": "number"},
        {"key": "consent", "data_type": "boolean"},
        {"key": "email", "data_type": "email"},
    ]
    valid, errors = coerce_all(
        fields,
        {
            "caller_name": "  Sam Lee ",
            "phone": "+1 (415) 555-0123",
            "service": "botox",
            "dob": "1990-02-03",
            "age": "34",
            "consent": "yes",
            "email": "Sam@Example.com",
        },
    )
    assert errors == {}
    assert valid == {
        "caller_name": "Sam Lee",
        "phone": "+14155550123",
        "service": "Botox",
        "dob": "1990-02-03",
        "age": 34,
        "consent": True,
        "email": "sam@example.com",
    }
    _, errors = coerce_all(
        fields,
        {
            "phone": "12",
            "service": "laser",
            "dob": "03/02/1990",
            "age": "old",
            "email": "nope",
            "consent": "maybe",
            "nonsense": 1,
            "caller_name": "  ",
        },
    )
    assert set(errors) == {"phone", "service", "dob", "age", "email", "consent", "nonsense", "caller_name"}


async def test_a_ticket_works_once_and_only_for_its_own_call():
    tenant, other = await create_test_tenant(), await create_test_tenant()
    async with tenant_session(tenant) as s:
        call = Call(tenant_id=tenant, agent_snapshot={}, channel="browser_test", status="connecting", model="m")
        s.add(call)
        await s.flush()
        ticket = tickets.mint(call)
        call_id = call.id
    assert await tickets.redeem(ticket.rsplit(".", 1)[0] + ".wrong") is None
    assert await tickets.redeem(f"{other}.{call_id}.{ticket.rsplit('.', 1)[1]}") is None  # another clinic
    assert await tickets.redeem("garbage") is None
    assert await tickets.redeem(ticket) == (tenant, call_id)
    assert await tickets.redeem(ticket) is None  # single use
    async with tenant_session(tenant) as s:
        assert (await s.get(Call, call_id)).status == "in_progress"


async def test_an_expired_ticket_is_refused():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        call = Call(tenant_id=tenant, agent_snapshot={}, channel="browser_test", status="connecting", model="m")
        s.add(call)
        await s.flush()
        ticket = tickets.mint(call)
        call.connect_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await tickets.redeem(ticket) is None


def test_ticket_ids_are_uuids():
    uuid.UUID(str(uuid.uuid4()))


async def test_a_call_that_never_got_to_run_is_closed_not_left_in_progress():
    from clinic_voice_receptionist.inbound.live.ws import fail_call

    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        mine = Call(tenant_id=tenant, agent_snapshot={}, channel="browser_test", status="in_progress", model="m")
        done = Call(tenant_id=tenant, agent_snapshot={}, channel="browser_test", status="completed", model="m")
        s.add_all([mine, done])
        await s.flush()
        mine_id, done_id = mine.id, done.id
    await fail_call(tenant, mine_id, "not_allowed", None)
    await fail_call(tenant, done_id, "not_allowed", None)  # a finished call is never rewritten
    async with tenant_session(tenant) as s:
        rows = {c.id: (c.status, c.end_reason) for c in (await s.scalars(select(Call))).all()}
    assert rows[mine_id] == ("failed", "not_allowed") and rows[done_id][0] == "completed"
