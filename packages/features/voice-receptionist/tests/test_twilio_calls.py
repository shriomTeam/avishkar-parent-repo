import asyncio
import base64
import json
import random
import re
import uuid
from array import array
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_core.settings import get_settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import Agent, Call, PhoneNumber
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.twilio_calls import audio, signature, stream, webhook

PUBLIC = "https://api.example.com"
TOKEN = "test-token"
VOICE_URL = PUBLIC + webhook.VOICE_PATH


# ---- audio ---------------------------------------------------------------------------------------------------


def test_mulaw_known_values_and_round_trip():
    assert [audio._decode_one(b) for b in (0x00, 0x80, 0xFF, 0x7F)] == [-32124, 32124, 0, 0]
    samples = array("h", [0, 100, -100, 1000, -1000, 8000, -8000, 20000, -20000, 32000, -32000])
    back = audio.mulaw_to_pcm(audio.pcm_to_mulaw(samples))
    for original, restored in zip(samples, back, strict=True):  # mu-law is lossy: within about 3 percent
        assert abs(original - restored) <= max(40, abs(original) * 0.04)


def test_extremes_do_not_overflow():
    assert len(audio.pcm_to_mulaw(array("h", [-32768, 32767]))) == 2


def test_a_phone_frame_becomes_twice_as_many_model_samples():
    frame = bytes([0xFF]) * 160  # 20 ms of silence
    pcm = audio.phone_to_model(frame)
    assert len(pcm) == 160 * 2 * 2 and set(pcm) == {0}  # 320 samples of 16-bit zero


def test_the_model_to_phone_conversion_keeps_every_sample_across_odd_chunks():
    converter = audio.ModelToPhone()
    chunk = array("h", range(0, 1000)).tobytes()  # 1000 samples at 24 kHz
    produced = len(converter.convert(chunk[: 1001 * 0 + 1500])) + len(converter.convert(chunk[1500:]))
    assert produced == 1000 // 3  # leftovers wait for the next chunk instead of being dropped
    converter.reset()
    assert converter.convert(b"\x01") == b""  # half a sample is ignored, not an error


# ---- signature -----------------------------------------------------------------------------------------------

# Expected values computed with Twilio's own Python library (RequestValidator.compute_signature).
CASES = [
    (
        "12345",
        "https://mycompany.com/myapp.php?foo=1&bar=2",
        {
            "CallSid": "CA1234567890ABCDE",
            "Caller": "+12349013030",
            "Digits": "1234",
            "From": "+12349013030",
            "To": "+18005551212",
        },
        "0/KCTR6DLpKmkAf8muzZqo1nDgQ=",
    ),
    ("tok123", "https://abc.example/x", {}, "a0raRbJQksxjpO7t2oJjeuMHkQ4="),
    ("tok123", "https://abc.example/x", {"Name": "José Ünï", "Empty": ""}, "dOF92vwkioAANsz7KW+cv2lJrt8="),
]


@pytest.mark.parametrize("token,url,params,expected", CASES)
def test_signatures_match_twilios_own_library(token, url, params, expected):
    assert signature.expected_signature(token, url, params) == expected
    assert signature.is_valid(token, url, params, expected)


def test_a_wrong_missing_or_unconfigured_signature_is_refused():
    token, url, params, good = CASES[0]
    assert not signature.is_valid(token, url, params, good[::-1])
    assert not signature.is_valid(token, url, params, None)
    assert not signature.is_valid("", url, params, good)
    assert not signature.is_valid(token, url + "/other", params, good)
    assert not signature.is_valid(token, url, {**params, "To": "+10000000000"}, good)


# ---- the incoming-call webhook -----------------------------------------------------------------------------------

app = FastAPI()
app.include_router(webhook.router, prefix="/features/voice_receptionist")


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", PUBLIC)
    monkeypatch.setenv("VOICE_ALLOW_SIP_TEST_CALLS", "false")  # a developer's .env may turn this on
    get_voice_settings.cache_clear()
    core = get_settings().model_copy(update={"twilio_auth_token": TOKEN})
    monkeypatch.setattr(webhook, "get_settings", lambda: core)
    monkeypatch.setattr(webhook, "calls_full", lambda: False)
    yield
    get_voice_settings.cache_clear()


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _number():
    area = f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    exchange = f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    return f"+1{area}{exchange}{random.randint(0, 9999):04d}"


def _sid():
    return "CA" + uuid.uuid4().hex


async def _setup(prompt="Caller is {{caller_number}}.", active=True, with_agent=True, features=("voice_receptionist",)):
    tenant = await create_test_tenant(features)
    number = _number()
    async with tenant_session(tenant) as s:
        agent = Agent(tenant_id=tenant, name="Front desk", prompt=prompt, model="m", is_active=active)
        s.add(agent)
        await s.flush()
        s.add(
            PhoneNumber(
                tenant_id=tenant,
                number=number,
                provider_sid="PN" + uuid.uuid4().hex,
                kind="local",
                agent_id=agent.id if with_agent else None,
            )
        )
        return tenant, number, agent.id


async def _post(client, params, *, sign=True, signature_value=None, url=VOICE_URL):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if sign:
        headers["X-Twilio-Signature"] = signature_value or signature.expected_signature(TOKEN, url, params)
    return await client.post(webhook.VOICE_PATH, content=urlencode(params), headers=headers)


def _call(to, frm="+14155550100", sid=None):
    return {"CallSid": sid or _sid(), "To": to, "From": frm, "CallStatus": "ringing"}


def _ticket(response):
    return re.search(r'name="ticket" value="([^"]+)"', response.text).group(1)


async def test_a_call_to_an_assigned_number_is_answered_with_a_stream_and_a_one_time_ticket(client):
    tenant, number, agent_id = await _setup()
    params = _call(number)
    r = await _post(client, params)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/xml")
    assert '<Stream url="wss://api.example.com/features/voice_receptionist/twilio/stream">' in r.text
    ticket = _ticket(r)
    async with tenant_session(tenant) as s:
        call = await s.scalar(select(Call).where(Call.provider_call_id == params["CallSid"]))
    assert (call.channel, call.status, call.direction, call.is_test) == ("twilio", "connecting", "inbound", False)
    assert (call.from_number, call.to_number, call.agent_id) == ("+14155550100", number, agent_id)
    assert call.agent_snapshot["prompt"] == "Caller is +14155550100."  # the built-in variable is filled in
    assert await tickets.redeem(ticket) == (tenant, call.id)
    assert await tickets.redeem(ticket) is None  # works once


async def test_the_dialled_number_decides_the_clinic_not_anything_the_caller_sends(client):
    t1, number1, _ = await _setup()
    t2, number2, _ = await _setup()
    r = await _post(client, _call(number2))
    ticket = _ticket(r)
    assert ticket.startswith(str(t2)) and not ticket.startswith(str(t1))
    assert number1 != number2


async def test_a_request_without_a_valid_signature_is_refused_before_anything_is_looked_up(client):
    tenant, number, _ = await _setup()
    params = _call(number)
    for r in (
        await _post(client, params, sign=False),
        await _post(client, params, signature_value="bm90LXR3aWxpbw=="),
        await _post(client, params, url="https://evil.example/features/voice_receptionist/twilio/voice"),
    ):
        assert r.status_code == 403 and "Stream" not in r.text
    async with tenant_session(tenant) as s:
        assert (await s.scalars(select(Call))).all() == []


async def test_without_a_public_address_or_token_the_endpoint_says_it_is_not_set_up(client, monkeypatch):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "")
    get_voice_settings.cache_clear()
    assert (await _post(client, _call(_number()))).status_code == 503


async def test_a_number_nobody_owns_or_without_an_agent_gets_a_polite_goodbye(client):
    _, unassigned, _ = await _setup(with_agent=False)
    for to in (_number(), unassigned):
        r = await _post(client, _call(to))
        assert r.status_code == 200 and "not in service" in r.text and "<Hangup/>" in r.text and "Stream" not in r.text


async def test_a_switched_off_agent_or_a_clinic_without_the_feature_does_not_answer(client):
    _, off_number, _ = await _setup(active=False)
    _, no_feature, _ = await _setup(features=())
    for to in (off_number, no_feature):
        assert "not in service" in (await _post(client, _call(to))).text


async def test_a_busy_server_tells_the_caller_to_try_again(client, monkeypatch):
    monkeypatch.setattr(webhook, "calls_full", lambda: True)
    _, number, _ = await _setup()
    r = await _post(client, _call(number))
    assert "try again" in r.text and "Stream" not in r.text


async def test_twilio_retrying_the_webhook_reuses_the_same_call_until_it_has_started(client):
    tenant, number, _ = await _setup()
    params = _call(number)
    first, second = _ticket(await _post(client, params)), _ticket(await _post(client, params))
    assert first != second
    async with tenant_session(tenant) as s:
        assert len((await s.scalars(select(Call))).all()) == 1
    assert await tickets.redeem(second) is not None
    again = await _post(client, params)  # the call is already running: no second stream
    assert "Stream" not in again.text and "<Hangup/>" in again.text


async def test_a_withheld_caller_number_is_recorded_as_unknown(client):
    tenant, number, _ = await _setup(prompt="Caller: {{caller_number}}")
    params = _call(number, frm="anonymous")
    assert (await _post(client, params)).status_code == 200
    async with tenant_session(tenant) as s:
        call = await s.scalar(select(Call).where(Call.provider_call_id == params["CallSid"]))
    assert call.from_number is None


@pytest.mark.parametrize("bad", [{"To": "12345"}, {"CallSid": "nope"}, {"To": "+1; DROP TABLE x"}])
async def test_malformed_requests_are_rejected(client, bad):
    _, number, _ = await _setup()
    r = await _post(client, {**_call(number), **bad})
    assert r.status_code == 400


# ---- the audio stream ----------------------------------------------------------------------------------------------


class FakeSocket:
    def __init__(self, messages):
        self.incoming = list(messages)
        self.sent, self.closed_with, self.accepted = [], None, False
        from starlette.websockets import WebSocketState

        self.application_state = WebSocketState.CONNECTED
        self.app = SimpleNamespace(state=SimpleNamespace(settings=get_settings()))

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect

        if not self.incoming:
            raise WebSocketDisconnect()
        item = self.incoming.pop(0)
        if item == "WAIT":
            await asyncio.sleep(5)
        return item

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, code=1000):
        from starlette.websockets import WebSocketState

        self.closed_with, self.application_state = code, WebSocketState.DISCONNECTED


def _start(ticket, call_sid, stream_sid="MZ1"):
    return json.dumps(
        {
            "event": "start",
            "start": {"streamSid": stream_sid, "callSid": call_sid, "customParameters": {"ticket": ticket}},
        }
    )


MEDIA = json.dumps({"event": "media", "media": {"payload": base64.b64encode(bytes([0xFF]) * 160).decode()}})


async def _live_call(client):
    tenant, number, _ = await _setup()
    params = _call(number)
    ticket = _ticket(await _post(client, params))
    return tenant, params["CallSid"], ticket


async def test_a_valid_start_runs_the_call_over_a_phone_transport(client, monkeypatch):
    seen = {}

    async def fake_run(app, tenant_id, call_id, snapshot, transport):
        seen["transport"], seen["call_id"] = transport, call_id
        frames = [f async for f in transport.frames()]
        seen["frames"] = frames
        await transport.send_audio(array("h", [1000] * 300).tobytes())
        await transport.send_event({"type": "interrupted"})

    monkeypatch.setattr(stream, "run_session", fake_run)
    _, call_sid, ticket = await _live_call(client)
    ws = FakeSocket(['{"event":"connected"}', _start(ticket, call_sid), MEDIA, MEDIA, '{"event":"stop"}'])
    await stream.phone_stream(ws)
    assert ws.accepted and len(seen["frames"]) == 2 and len(seen["frames"][0]) == 640  # 20 ms at 16 kHz, 16-bit
    media = [m for m in ws.sent if m["event"] == "media"]
    assert media and media[0]["streamSid"] == "MZ1" and len(base64.b64decode(media[0]["media"]["payload"])) == 100
    assert {"event": "clear", "streamSid": "MZ1"} in ws.sent  # an interruption clears what Twilio had buffered


@pytest.mark.parametrize("case", ["wrong_call", "reused", "no_ticket", "garbage_ticket", "never_starts"])
async def test_the_stream_is_refused_unless_the_ticket_is_for_this_call(client, monkeypatch, case):
    async def fake_run(*args, **kwargs):
        raise AssertionError("the call must not start")

    monkeypatch.setattr(stream, "run_session", fake_run)
    monkeypatch.setattr(stream, "START_TIMEOUT_SECONDS", 0.2)
    tenant, call_sid, ticket = await _live_call(client)
    messages = {
        "wrong_call": [_start(ticket, "CA" + uuid.uuid4().hex)],
        "no_ticket": [_start("", call_sid)],
        "garbage_ticket": [_start("not.a.ticket", call_sid)],
        "never_starts": ["WAIT"],
    }.get(case)
    if case == "reused":
        assert await tickets.redeem(ticket) is not None
        messages = [_start(ticket, call_sid)]
    ws = FakeSocket(messages)
    await stream.phone_stream(ws)
    assert ws.closed_with == 1008
    if case == "wrong_call":  # the call was opened by a ticket that did not match: it is closed, not left running
        async with tenant_session(tenant) as s:
            call = await s.scalar(select(Call).where(Call.provider_call_id == call_sid))
        assert call.status == "failed"


async def test_a_whole_phone_call_runs_through_the_real_call_engine(client):
    """Simulated Twilio audio in, the scripted model's reply out, and a finished call with a transcript behind it."""
    from clinic_db.models.voice import CallTurn
    from clinic_voice_receptionist.testing import ScriptedConnector

    tenant, number, _ = await _setup(prompt="You answer calls.")
    params = _call(number)
    ticket = _ticket(await _post(client, params))
    loud = json.dumps({"event": "media", "media": {"payload": base64.b64encode(bytes([0x10, 0x90] * 80)).decode()}})
    ws = FakeSocket(['{"event":"connected"}', _start(ticket, params["CallSid"]), *([loud] * 40), '{"event":"stop"}'])
    ws.app.state.voice_connector = ScriptedConnector()
    await stream.phone_stream(ws)

    async with tenant_session(tenant) as s:
        call = await s.scalar(select(Call).where(Call.provider_call_id == params["CallSid"]))
        turns = (await s.scalars(select(CallTurn).where(CallTurn.call_id == call.id))).all()
    assert call.status == "completed" and call.channel == "twilio" and call.ended_at is not None
    assert any(t.speaker == "caller" for t in turns) and any(t.speaker == "agent" for t in turns)
    media = [m for m in ws.sent if m["event"] == "media"]
    assert media and all(m["streamSid"] == "MZ1" for m in media)  # the agent's voice went back down the line
    assert len(base64.b64decode(media[0]["media"]["payload"])) > 0


async def test_sip_domain_calls_are_accepted_only_when_local_testing_allows_them(client, monkeypatch):
    _, number, _ = await _setup()
    sip = {
        **_call(number),
        "To": f"sip:{number}@avishkar-test.sip.twilio.com",
        "From": "sip:vishnu@avishkar-test.sip.twilio.com",
    }
    assert (await _post(client, sip)).status_code == 400  # off by default
    monkeypatch.setenv("VOICE_ALLOW_SIP_TEST_CALLS", "true")
    get_voice_settings.cache_clear()
    r = await _post(client, sip)
    assert r.status_code == 200 and "Stream" in r.text
    ten_digits = {**_call(number), "To": f"sip:{number[2:]}@x.sip.twilio.com", "From": "sip:a@x"}
    assert "Stream" in (await _post(client, ten_digits)).text  # a number typed without +1 still finds the number


def test_the_dialled_number_is_read_from_a_sip_address_only_when_allowed():
    assert webhook.dialled_number("sip:+14155550123@d.sip.twilio.com", True) == "+14155550123"
    assert webhook.dialled_number("sip:14155550123@d.sip.twilio.com", True) == "+14155550123"
    assert webhook.dialled_number("sip:415-555-0123@d.sip.twilio.com", True) == "+14155550123"
    assert webhook.dialled_number("sip:+14155550123@d.sip.twilio.com", False).startswith("sip:")
    assert webhook.dialled_number("+14155550123", True) == "+14155550123"
