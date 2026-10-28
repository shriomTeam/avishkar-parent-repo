import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from support_http import json_reply, serve
from test_live_session import FakeModel, _saved, _start

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Lead
from clinic_db.models.ops import OutboxEvent
from clinic_db.models.voice import Call, Tool, ToolExecution
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.live.events import Received, ToolCall, Transcript, TurnComplete
from clinic_voice_receptionist.tools.runner import ToolOutcome, ToolRunner
from clinic_voice_receptionist.tools.service import add_builtin

HOURS_SCHEMA = {"type": "object", "properties": {"day": {"type": "string"}}, "required": ["day"]}


@pytest.fixture
def allow_private(monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_ALLOW_PRIVATE_HOSTS", "true")
    get_voice_settings.cache_clear()
    yield
    monkeypatch.delenv("VOICE_TOOL_ALLOW_PRIVATE_HOSTS")
    get_voice_settings.cache_clear()


async def _tenant_with_call():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        lead_tool = await add_builtin(s, tenant, "create_lead")
        call = Call(tenant_id=tenant, agent_snapshot={}, channel="browser_test", status="in_progress", model="m")
        s.add(call)
        await s.flush()
        return tenant, call.id, lead_tool


def _ref(tool: Tool) -> dict:
    return {"id": str(tool.id), "name": tool.name, "schema": tool.input_schema, "timeout_seconds": tool.timeout_seconds}


async def _http_tool(tenant, url, **overrides):
    async with tenant_session(tenant) as s:
        values = dict(
            tenant_id=tenant, name="lookup_hours", description="Hours", kind="http", endpoint=url, method="POST",
            timeout_seconds=3, input_schema=HOURS_SCHEMA, enabled=True,
        )  # fmt: skip
        tool = Tool(**(values | overrides))
        s.add(tool)
        await s.flush()
        return tool


async def test_create_lead_saves_a_lead_links_it_to_the_call_and_announces_it():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    args = {"first_name": "Sam", "last_name": "Lee", "phone": "+1 (415) 555-0123", "interest": "Botox"}
    outcome = await runner.run(_ref(tool), args, "k1")
    assert outcome.success and outcome.response["created"] is True
    async with tenant_session(tenant) as s:
        lead = await s.get(Lead, uuid.UUID(outcome.response["lead_id"]))
        call = await s.get(Call, call_id)
        events = (await s.scalars(select(OutboxEvent.event_type))).all()
    assert (lead.first_name, lead.phone, lead.interest, lead.channel, lead.status) == (
        "Sam",
        "+14155550123",
        "Botox",
        "call",
        "new",
    )
    assert lead.utm == {"source": "voice_agent", "call_id": str(call_id)} and call.lead_id == lead.id
    assert events == ["lead.created"]


async def test_calling_create_lead_again_updates_the_same_lead():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    first = await runner.run(_ref(tool), {"first_name": "Sam", "phone": "+14155550123"}, "k1")
    second = await runner.run(_ref(tool), {"last_name": "Lee", "email": "Sam@Example.com"}, "k2")
    assert second.response["created"] is False and second.response["lead_id"] == first.response["lead_id"]
    async with tenant_session(tenant) as s:
        leads = (await s.scalars(select(Lead))).all()
        events = (await s.scalars(select(OutboxEvent.event_type))).all()
    assert len(leads) == 1 and (leads[0].first_name, leads[0].last_name, leads[0].email) == (
        "Sam",
        "Lee",
        "sam@example.com",
    )
    assert leads[0].phone == "+14155550123" and events == ["lead.created"]  # announced once


def _filled_ref(tool, **filled):
    return _ref(tool) | {"filled": {a: {"key": k, "label": k.title(), "required": r} for a, (k, r) in filled.items()}}


async def test_create_lead_takes_filled_arguments_from_captured_values_not_from_the_model():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    ref = _filled_ref(tool, phone=("mobile", True))
    captured = {"mobile": "+14155550123"}
    outcome = await runner.run(ref, {"first_name": "Sam", "phone": "+19998887777"}, "k", captured)
    assert outcome.success
    async with tenant_session(tenant) as s:
        lead = await s.get(Lead, uuid.UUID(outcome.response["lead_id"]))
    assert (lead.first_name, lead.phone) == ("Sam", "+14155550123")


async def test_a_missing_required_detail_stops_the_tool_and_tells_the_model_what_to_ask():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    outcome = await runner.run(_filled_ref(tool, phone=("phone", True)), {"first_name": "Sam"}, "k", {})
    assert not outcome.success and outcome.response["missing"] == ["Phone"]
    assert "save_caller_details" in outcome.response["error"]
    async with tenant_session(tenant) as s:
        assert (await s.scalars(select(Lead))).all() == []


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ({"first_name": "Sam"}, "phone number or an email"),
        ({"phone": "12"}, "invalid"),
        ({"email": "nope"}, "invalid"),
    ],
)
async def test_create_lead_refuses_unusable_details_and_tells_the_model_why(args, fragment):
    tenant, call_id, tool = await _tenant_with_call()
    outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(_ref(tool), args, "k")
    assert not outcome.success and fragment in str(outcome.response)
    async with tenant_session(tenant) as s:
        assert (await s.scalars(select(Lead))).all() == []


async def _update_tool(tenant) -> Tool:
    async with tenant_session(tenant) as s:
        return await add_builtin(s, tenant, "update_lead")


async def test_update_lead_changes_the_lead_made_in_this_call_and_nothing_else():
    tenant, call_id, create = await _tenant_with_call()
    update = await _update_tool(tenant)
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    made = await runner.run(_ref(create), {"first_name": "Sam", "phone": "+14155550123"}, "k1")
    changed = await runner.run(_ref(update), {"last_name": "Lee", "interest": "Filler"}, "k2")
    assert changed.success and changed.response == {"ok": True, "lead_id": made.response["lead_id"], "created": False}
    async with tenant_session(tenant) as s:
        leads = (await s.scalars(select(Lead))).all()
        events = (await s.scalars(select(OutboxEvent.event_type))).all()
    assert len(leads) == 1 and (leads[0].first_name, leads[0].last_name, leads[0].interest) == ("Sam", "Lee", "Filler")
    assert leads[0].phone == "+14155550123" and events == ["lead.created"]


async def test_update_lead_never_creates_a_lead():
    tenant, call_id, _ = await _tenant_with_call()
    update = await _update_tool(tenant)
    outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(_ref(update), {"first_name": "Sam"}, "k")
    assert not outcome.success and "Use create_lead first" in outcome.response["error"]
    async with tenant_session(tenant) as s:
        assert (await s.scalars(select(Lead))).all() == []


async def test_update_lead_needs_something_to_change_and_checks_what_it_gets():
    tenant, call_id, create = await _tenant_with_call()
    update = await _update_tool(tenant)
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    await runner.run(_ref(create), {"phone": "+14155550123"}, "k1")
    empty = await runner.run(_ref(update), {}, "k2")
    assert not empty.success and "Nothing to update" in empty.response["error"]
    bad = await runner.run(_ref(update), {"phone": "12"}, "k3")
    assert not bad.success and "phone" in bad.response["invalid"]
    async with tenant_session(tenant) as s:
        assert (await s.scalar(select(Lead))).phone == "+14155550123"  # untouched


async def test_arguments_that_break_the_schema_never_reach_the_tool():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    outcome = await runner.run(_ref(tool), {"phone": 5}, "k")
    assert not outcome.success and outcome.response == {"ok": False, "invalid": {"phone": "must be a string"}}
    huge = await runner.run(_ref(tool), {"interest": "x" * 9000}, "k")
    assert not huge.success and "too large" in huge.response["error"]


async def test_a_tool_that_was_switched_off_or_deleted_mid_call_is_unavailable():
    tenant, call_id, tool = await _tenant_with_call()
    runner = ToolRunner(tenant_id=tenant, call_id=call_id)
    async with tenant_session(tenant) as s:
        (await s.get(Tool, tool.id)).enabled = False
    off = await runner.run(_ref(tool), {"phone": "+14155550123"}, "k")
    assert not off.success and off.response == {"ok": False, "error": "This tool is not available."}
    async with tenant_session(tenant) as s:
        await s.delete(await s.get(Tool, tool.id))
    gone = await runner.run(_ref(tool), {"phone": "+14155550123"}, "k")
    assert not gone.success and gone.error == "tool unavailable"


async def test_a_custom_tool_calls_its_endpoint_and_the_answer_goes_back_to_the_model(allow_private):
    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({"open": "9 to 5"})

    async with serve(handler) as (url, requests):
        tool = await _http_tool(tenant, url + "/hours")
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(
            _ref(tool), {"day": "mon", "junk": 1}, "call:1"
        )
    assert outcome.success and outcome.response == {"ok": True, "status": 200, "response": {"open": "9 to 5"}}
    assert b"junk" not in requests[0]["body"]  # arguments outside the schema are dropped
    assert requests[0]["headers"]["idempotency-key"] == "call:1"


async def test_a_custom_tool_sends_its_template_filled_from_captured_details(allow_private):
    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({"id": "n1"})

    async with serve(handler) as (url, requests):
        tool = await _http_tool(
            tenant,
            url + "/patients/{{field.phone}}/notes",
            payload_template={"phone": "{{field.phone}}", "note": "{{arg.day}}", "call": "{{call.id}}", "k": 1},
        )
        ref = _ref(tool) | {"labels": {"phone": "Phone"}}
        captured = {"phone": "+14155550123"}
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(ref, {"day": "mon"}, "k", captured)
    assert outcome.success
    assert requests[0]["target"] == "/patients/%2B14155550123/notes"
    assert json.loads(requests[0]["body"]) == {"phone": "+14155550123", "note": "mon", "call": str(call_id), "k": 1}


async def test_a_custom_tool_does_not_run_while_a_captured_detail_is_missing(allow_private):
    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({})

    async with serve(handler) as (url, requests):
        tool = await _http_tool(tenant, url, payload_template={"phone": "{{field.phone}}"})
        ref = _ref(tool) | {"labels": {"phone": "Mobile number"}}
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(ref, {"day": "mon"}, "k", {})
    assert not outcome.success and outcome.response["missing"] == ["Mobile number"]
    assert requests == []  # nothing was sent


async def test_a_failing_endpoint_reports_the_problem_without_raising(allow_private):
    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({"error": "no"}, 500)

    async with serve(handler) as (url, _):
        tool = await _http_tool(tenant, url)
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(_ref(tool), {"day": "mon"}, "k")
    assert not outcome.success and outcome.response["status"] == 500 and "status 500" in outcome.error


async def test_long_answers_are_cut_down_before_they_reach_the_model_and_the_database(allow_private):
    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({"rows": ["x" * 100] * 200})

    async with serve(handler) as (url, _):
        tool = await _http_tool(tenant, url)
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(_ref(tool), {"day": "mon"}, "k")
    assert outcome.success and outcome.response["truncated"] is True and len(outcome.response["text"]) == 4000
    assert outcome.stored_output["truncated"] is True and len(outcome.stored_output["text"]) == 8000


async def test_auth_headers_are_decrypted_for_the_request_only(allow_private):
    from clinic_voice_receptionist.tools import secrets

    tenant, call_id, _ = await _tenant_with_call()

    async def handler(request, n):
        return json_reply({})

    async with serve(handler) as (url, requests):
        tool = await _http_tool(
            tenant, url, auth_header_name="Authorization", auth_header_secret=secrets.encrypt("Bearer abc")
        )
        outcome = await ToolRunner(tenant_id=tenant, call_id=call_id).run(_ref(tool), {"day": "mon"}, "k")
    assert requests[0]["headers"]["authorization"] == "Bearer abc"
    assert "Bearer abc" not in repr(outcome)


def _runner_for(tenant, call_id):
    return ToolRunner(tenant_id=tenant, call_id=call_id)


async def test_the_agent_can_create_a_lead_during_a_call_and_it_is_recorded():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        lead_tool = await add_builtin(s, tenant, "create_lead")
    model = FakeModel()
    tenant_id, call_id, session, _, transport, task = await _start(
        model, snapshot_extra={"tools": [_ref(lead_tool)]}, tool_runner=None
    )
    # _start makes its own tenant, so give the session a runner for that tenant and enable the tool there.
    async with tenant_session(tenant_id) as s:
        real = await add_builtin(s, tenant_id, "create_lead")
    session.tool_runner = ToolRunner(tenant_id=tenant_id, call_id=call_id)
    session._tools = {"create_lead": _ref(real)}

    model.push(ToolCall("t1", "create_lead", {"first_name": "Sam", "phone": "+14155550123"}))
    await asyncio.sleep(0.4)
    reply = model.tool_results[0][0].response
    assert reply["ok"] is True and reply["created"] is True
    assert [e for e in transport.events if e["type"] == "tool"] == [
        {"type": "tool", "name": "create_lead", "status": "running"},
        {"type": "tool", "name": "create_lead", "status": "ok", "duration_ms": transport.events[-1]["duration_ms"]},
    ] or [e["status"] for e in transport.events if e["type"] == "tool"] == ["running", "ok"]
    model.push(Received([TurnComplete()]))
    transport.inbox.put_nowait({"type": "hangup"})
    await asyncio.wait_for(task, 5)

    call, *_ = await _saved(tenant_id, call_id)
    async with tenant_session(tenant_id) as s:
        executions = (await s.scalars(select(ToolExecution))).all()
        lead = await s.get(Lead, call.lead_id)
    assert call.lead_id and lead.phone == "+14155550123"
    assert [(e.tool_name, e.success, e.idempotency_key) for e in executions] == [
        ("create_lead", True, f"{call_id}:create_lead:t1")
    ]
    assert (
        executions[0].input == {"first_name": "Sam", "phone": "+14155550123"}
        and executions[0].output["created"] is True
    )


class SlowRunner:
    async def run(self, ref, args, key, values=None):
        await asyncio.sleep(5)
        return ToolOutcome(True, {"ok": True})


class BrokenRunner:
    async def run(self, ref, args, key, values=None):
        return ToolOutcome(False, {"ok": False, "invalid": {"phone": "bad"}}, "invalid arguments", 3, {"ok": False})


async def test_a_tool_that_takes_too_long_is_cut_off_and_the_model_is_told():
    model = FakeModel()
    ref = {"id": str(uuid.uuid4()), "name": "slow_tool", "schema": HOURS_SCHEMA, "timeout_seconds": -2}  # 1 s budget
    tenant, call_id, session, _, transport, task = await _start(model, snapshot_extra={"tools": [ref]})
    session.tool_runner, session._tools = SlowRunner(), {"slow_tool": ref}
    model.push(Transcript("agent", "One moment while I check."))
    model.push(ToolCall("t1", "slow_tool", {"day": "mon"}))
    await asyncio.sleep(1.6)
    assert model.tool_results[0][0].response == {"ok": False, "error": "The tool took too long to answer."}
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
    _, turns, *_ = await _saved(tenant, call_id)
    assert [t.text for t in turns] == ["One moment while I check."]  # the transcript was not held up
    async with tenant_session(tenant) as s:
        executions = (await s.scalars(select(ToolExecution))).all()
    # The tool id here does not exist (as if the tool were deleted mid-call): the record is kept without the link.
    assert [(e.tool_name, e.success, e.error, e.tool_id) for e in executions] == [
        ("slow_tool", False, "timed out", None)
    ]


async def test_a_failed_tool_is_recorded_and_its_reason_reaches_the_model():
    model = FakeModel()
    ref = {"id": str(uuid.uuid4()), "name": "bad_tool", "schema": HOURS_SCHEMA, "timeout_seconds": 5}
    tenant, call_id, session, _, transport, task = await _start(model, snapshot_extra={"tools": [ref]})
    session.tool_runner, session._tools = BrokenRunner(), {"bad_tool": ref}
    model.push(ToolCall("t1", "bad_tool", {}))
    await asyncio.sleep(0.3)
    assert model.tool_results[0][0].response == {"ok": False, "invalid": {"phone": "bad"}}
    assert [e["status"] for e in transport.events if e["type"] == "tool"] == ["running", "failed"]
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)


async def test_a_function_that_is_not_a_configured_tool_is_refused():
    model = FakeModel()
    tenant, call_id, session, _, transport, task = await _start(model)
    model.push(ToolCall("t1", "delete_everything", {}))
    await asyncio.sleep(0.2)
    assert model.tool_results[0][0].response == {"ok": False, "error": "unknown function"}
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
