from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from support_http import json_reply, serve

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import Call, Tool, ToolExecution
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.router import router as inbound_router
from clinic_voice_receptionist.tools import secrets
from clinic_voice_receptionist.tools.router import router as tools_router

app = FastAPI()
# This isolated router test intentionally exercises the explicit dev-header adapter.
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(inbound_router)
app.include_router(tools_router)

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Caller name"}},
    "required": ["name"],
}


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


def _tool(**overrides):
    body = {
        "name": "lookup_hours",
        "description": "Look up the clinic's opening hours.",
        "endpoint": "https://api.example.com/hours",
        "method": "GET",
        "timeout_seconds": 5,
        "input_schema": SCHEMA,
    }
    return body | overrides


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def allow_private(monkeypatch):
    """Lets tools call the local test server, as development does."""
    monkeypatch.setenv("VOICE_TOOL_ALLOW_PRIVATE_HOSTS", "true")
    get_voice_settings.cache_clear()
    yield
    monkeypatch.delenv("VOICE_TOOL_ALLOW_PRIVATE_HOSTS")
    get_voice_settings.cache_clear()


async def _create(client, tenant, **overrides):
    r = await client.post("/inbound/tools", json=_tool(**overrides), headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def _add_internal(client, tenant, key="create_lead"):
    r = await client.post("/inbound/tools/internal", json={"builtin_key": key}, headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def _tools(client, tenant):
    r = await client.get("/inbound/tools", headers=_h(tenant))
    assert r.status_code == 200, r.text
    return r.json()


async def _agent(client, tenant, **overrides):
    body = {"name": "Front desk", "prompt": "Be kind.", "fields": []} | overrides
    r = await client.post("/inbound/agents", json=body, headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def test_internal_tools_come_from_a_catalog_and_are_added_on_demand(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    assert await _tools(client, a) == []  # nothing is added for a clinic until it chooses
    catalog = (await client.get("/inbound/tools/catalog", headers=_h(a))).json()
    assert [(c["key"], c["added"]) for c in catalog] == [
        ("create_lead", False),
        ("update_lead", False),
        ("search_knowledge", False),
    ]
    assert all(c["title"] and c["description"] for c in catalog)

    lead = await _add_internal(client, a)
    assert lead["kind"] == "builtin" and lead["enabled"] is True and lead["endpoint"] is None
    assert "phone" in lead["input_schema"]["properties"] and lead["builtin_key"] == "create_lead"
    assert [t["name"] for t in await _tools(client, a)] == ["create_lead"]
    added = {c["key"]: c["added"] for c in (await client.get("/inbound/tools/catalog", headers=_h(a))).json()}
    assert added == {"create_lead": True, "update_lead": False, "search_knowledge": False}

    again = await client.post("/inbound/tools/internal", json={"builtin_key": "create_lead"}, headers=_h(a))
    assert again.status_code == 409 and "already added" in again.json()["detail"]
    unknown = await client.post("/inbound/tools/internal", json={"builtin_key": "launch_rockets"}, headers=_h(a))
    assert unknown.status_code == 422 and "internal tools" in unknown.json()["detail"]
    assert (await _add_internal(client, b))["id"] != lead["id"]  # each clinic has its own
    assert len(await _tools(client, a)) == 1  # the other clinic's tool did not appear here

    # An internal tool can be removed, and added again later.
    assert (await client.delete(f"/inbound/tools/{lead['id']}", headers=_h(a))).status_code == 204
    assert await _tools(client, a) == []
    assert (await _add_internal(client, a))["id"] != lead["id"]


async def test_a_custom_tool_cannot_take_the_name_of_an_internal_one(client):
    t = await create_test_tenant()
    for name in ("create_lead", "update_lead"):
        r = await client.post("/inbound/tools", json=_tool(name=name), headers=_h(t))
        assert r.status_code == 422 and "used by the platform" in r.json()["detail"]


async def test_only_managers_can_add_internal_tools(client):
    t = await create_test_tenant()
    r = await client.post("/inbound/tools/internal", json={"builtin_key": "create_lead"}, headers=_h(t, "front_desk"))
    assert r.status_code == 403
    assert (await client.get("/inbound/tools/catalog", headers=_h(t, "front_desk"))).status_code == 200


async def test_built_in_wording_follows_the_code_until_a_clinic_writes_its_own(client):
    t = await create_test_tenant()
    lead = await _add_internal(client, t)
    default = lead["default_description"]
    assert lead["description"] == default and lead["description_customized"] is False
    # Switch it off without touching the wording, then pretend an older release stored different text.
    await client.put(f"/inbound/tools/{lead['id']}", json=_tool(description=default, enabled=False), headers=_h(t))
    async with tenant_session(t) as s:
        (await s.get(Tool, UUID(lead["id"]))).description = "stale wording from an older release"
    refreshed = (await _tools(client, t))[0]
    assert refreshed["description"] == default and refreshed["enabled"] is False and refreshed["id"] == lead["id"]

    # A clinic's own wording is kept, however often the platform refreshes the built-ins.
    mine = "Only create a lead for callers who are not existing patients."
    saved = await client.put(f"/inbound/tools/{lead['id']}", json=_tool(description=mine), headers=_h(t))
    assert saved.json()["description"] == mine and saved.json()["description_customized"] is True
    for _ in range(2):
        again = (await _tools(client, t))[0]
        assert again["description"] == mine and again["default_description"] == default

    # Writing the default text back (the UI's "Reset to default") returns to following the code.
    reset = await client.put(f"/inbound/tools/{lead['id']}", json=_tool(description=default), headers=_h(t))
    assert reset.json()["description_customized"] is False
    async with tenant_session(t) as s:
        (await s.get(Tool, UUID(lead["id"]))).description = "stale again"
    assert (await _tools(client, t))[0]["description"] == default


async def test_a_custom_tool_can_be_created_changed_and_deleted(client):
    t = await create_test_tenant()
    tool = await _create(client, t)
    assert tool["kind"] == "http" and tool["has_auth"] is False and tool["method"] == "GET"
    changed = await client.put(
        f"/inbound/tools/{tool['id']}", json=_tool(description="Updated.", timeout_seconds=8), headers=_h(t)
    )
    assert changed.status_code == 200 and changed.json()["description"] == "Updated."
    assert (await client.get(f"/inbound/tools/{tool['id']}", headers=_h(t))).json()["timeout_seconds"] == 8
    assert {x["name"] for x in await _tools(client, t)} == {"lookup_hours"}
    assert (await client.delete(f"/inbound/tools/{tool['id']}", headers=_h(t))).status_code == 204
    assert (await client.get(f"/inbound/tools/{tool['id']}", headers=_h(t))).status_code == 404


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"endpoint": "http://api.example.com/x"}, "HTTPS"),
        ({"endpoint": None}, "endpoint"),
        ({"endpoint": "https://127.0.0.1/x"}, "not public"),
        ({"endpoint": "https://169.254.169.254/x"}, "not public"),
        ({"name": "end_call"}, "used by the platform"),
        ({"name": "save_caller_details"}, "used by the platform"),
        ({"input_schema": {"type": "object"}}, "JSON object"),
        ({"input_schema": {"type": "object", "properties": {"a": {"type": "string", "oneOf": []}}}}, "oneOf"),
        ({"auth_header_name": "Host", "auth_header_value": "x"}, "different header"),
        ({"auth_header_name": "X-Api-Key"}, "value to send"),
        ({"auth_header_value": "abc"}, "header name"),
        ({"auth_header_name": "X-Api-Key", "auth_header_value": "abc\ndef"}, "line breaks"),
        ({"auth_header_name": "X-Api-Key", "auth_header_value": "abc\x00def"}, "control characters"),
    ],
)
async def test_bad_tool_definitions_are_refused_with_a_message_staff_can_act_on(client, change, fragment):
    t = await create_test_tenant()
    r = await client.post("/inbound/tools", json=_tool(**change), headers=_h(t))
    assert r.status_code == 422 and fragment in r.json()["detail"]


async def test_names_that_are_not_snake_case_or_timeouts_out_of_range_are_rejected(client):
    t = await create_test_tenant()
    for change in ({"name": "Look Up"}, {"timeout_seconds": 0}, {"timeout_seconds": 11}, {"method": "DELETE"}):
        assert (await client.post("/inbound/tools", json=_tool(**change), headers=_h(t))).status_code == 422


async def test_tool_names_are_unique_within_a_clinic_only(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    await _create(client, a)
    clash = await client.post("/inbound/tools", json=_tool(), headers=_h(a))
    assert clash.status_code == 409 and "already exists" in clash.json()["detail"]
    other = await _create(client, a, name="another_tool")
    rename = await client.put(f"/inbound/tools/{other['id']}", json=_tool(), headers=_h(a))
    assert rename.status_code == 409
    await _create(client, b)  # the same name is fine in another clinic


async def test_the_auth_header_value_is_stored_encrypted_and_never_returned(client):
    t = await create_test_tenant()
    tool = await _create(client, t, auth_header_name="X-Api-Key", auth_header_value="top-secret-123")
    assert tool["has_auth"] is True and tool["auth_header_name"] == "X-Api-Key"
    shown = [tool, await _tools(client, t), (await client.get(f"/inbound/tools/{tool['id']}", headers=_h(t))).json()]
    assert "top-secret-123" not in repr(shown)
    async with tenant_session(t) as s:
        stored = (await s.get(Tool, UUID(tool["id"]))).auth_header_secret
    assert stored and "top-secret-123" not in stored and secrets.decrypt(stored) == "top-secret-123"

    # Saving again without a value keeps the secret; clearing removes it.
    kept = await client.put(
        f"/inbound/tools/{tool['id']}", json=_tool(auth_header_name="X-Api-Key", description="New."), headers=_h(t)
    )
    assert kept.json()["has_auth"] is True
    cleared = await client.put(f"/inbound/tools/{tool['id']}", json=_tool(clear_auth=True), headers=_h(t))
    assert cleared.json()["has_auth"] is False and cleared.json()["auth_header_name"] is None
    async with tenant_session(t) as s:
        assert (await s.get(Tool, UUID(tool["id"]))).auth_header_secret is None


async def test_builtin_tools_keep_their_name_and_arguments_but_allow_a_new_description(client):
    t = await create_test_tenant()
    lead = await _add_internal(client, t)
    r = await client.put(
        f"/inbound/tools/{lead['id']}",
        json=_tool(
            name="renamed",
            description="New wording.",
            endpoint="https://api.example.com/x",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            enabled=False,
        ),
        headers=_h(t),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["enabled"], body["description"]) == (False, "New wording.")
    assert body["name"] == "create_lead" and body["endpoint"] is None  # identity and arguments stay fixed
    assert body["input_schema"] == lead["input_schema"] and body["kind"] == "builtin"
    blank = await client.put(f"/inbound/tools/{lead['id']}", json=_tool(description="   "), headers=_h(t))
    assert blank.status_code == 422
    tested = await client.post(f"/inbound/tools/{lead['id']}/test", json={"input": {}}, headers=_h(t))
    assert tested.status_code == 409 and "test call" in tested.json()["detail"]


async def test_only_managers_can_change_tools_but_front_desk_can_read(client):
    t = await create_test_tenant()
    tool = await _create(client, t)
    desk = _h(t, "front_desk")
    assert (await client.get("/inbound/tools", headers=desk)).status_code == 200
    assert (await client.post("/inbound/tools", json=_tool(name="x_tool"), headers=desk)).status_code == 403
    assert (await client.put(f"/inbound/tools/{tool['id']}", json=_tool(), headers=desk)).status_code == 403
    assert (await client.delete(f"/inbound/tools/{tool['id']}", headers=desk)).status_code == 403
    assert (await client.post(f"/inbound/tools/{tool['id']}/test", json={}, headers=desk)).status_code == 403


async def test_a_clinic_cannot_see_or_use_another_clinics_tool(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    tool = await _create(client, a)
    url = f"/inbound/tools/{tool['id']}"
    assert (await client.get(url, headers=_h(b))).status_code == 404
    assert (await client.put(url, json=_tool(), headers=_h(b))).status_code == 404
    assert (await client.delete(url, headers=_h(b))).status_code == 404
    assert (await client.post(url + "/test", json={}, headers=_h(b))).status_code == 404
    assert tool["id"] not in {x["id"] for x in await _tools(client, b)}


async def test_agents_choose_their_tools_and_unknown_tools_are_refused(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    lead = await _add_internal(client, a)
    custom = await _create(client, a)
    agent = await _agent(client, a, tool_ids=[lead["id"], custom["id"]])
    assert set(agent["tool_ids"]) == {lead["id"], custom["id"]}
    listed = (await client.get("/inbound/agents", headers=_h(a))).json()
    assert set(listed[0]["tool_ids"]) == {lead["id"], custom["id"]}

    nope = {"name": "Other", "prompt": "Be kind.", "tool_ids": ["00000000-0000-0000-0000-000000000001"]}
    assert (await client.post("/inbound/agents", json=nope, headers=_h(a))).status_code == 422

    body = {"name": "Front desk", "prompt": "Be kind.", "tool_ids": [lead["id"]]}
    changed = await client.put(f"/inbound/agents/{agent['id']}", json=body, headers=_h(a))
    assert changed.json()["tool_ids"] == [lead["id"]]

    bad = await client.put(
        f"/inbound/agents/{agent['id']}",
        json=body | {"tool_ids": ["00000000-0000-0000-0000-000000000001"]},
        headers=_h(a),
    )
    assert bad.status_code == 422
    foreign = (await _add_internal(client, b))["id"]  # another clinic's tool
    assert (
        await client.put(f"/inbound/agents/{agent['id']}", json=body | {"tool_ids": [foreign]}, headers=_h(a))
    ).status_code == 422

    await client.put(f"/inbound/agents/{agent['id']}", json=body | {"tool_ids": [custom["id"]]}, headers=_h(a))
    await client.delete(f"/inbound/tools/{custom['id']}", headers=_h(a))
    assert (await client.get(f"/inbound/agents/{agent['id']}", headers=_h(a))).json()["tool_ids"] == []


async def test_a_test_call_only_receives_enabled_attached_tools_and_no_secrets(client):
    t = await create_test_tenant()
    lead = await _add_internal(client, t)
    on = await _create(client, t, name="tool_on", auth_header_name="Authorization", auth_header_value="Bearer abc123")
    off = await _create(client, t, name="tool_off", enabled=False)
    await _create(client, t, name="not_attached")
    agent = await _agent(client, t, tool_ids=[lead["id"], on["id"], off["id"]])
    started = await client.post(f"/inbound/agents/{agent['id']}/test-call", headers=_h(t))
    assert started.status_code == 201, started.text
    async with tenant_session(t) as s:
        snapshot = (await s.get(Call, UUID(started.json()["call_id"]))).agent_snapshot
    assert [x["name"] for x in snapshot["tools"]] == ["create_lead", "tool_on"]
    assert (
        "api.example.com" not in repr(snapshot)
        and "abc123" not in repr(snapshot)
        and "Authorization" not in repr(snapshot)
    )
    assert snapshot["tools"][1]["schema"] == SCHEMA


async def test_testing_a_tool_really_calls_the_endpoint_with_the_saved_settings(client, allow_private):
    t = await create_test_tenant()

    async def handler(request, n):
        return json_reply({"open": "9 to 5"})

    async with serve(handler) as (url, requests):
        tool = await _create(
            client, t, endpoint=url + "/hours", method="POST", auth_header_name="X-Api-Key", auth_header_value="k-123"
        )
        ok = await client.post(f"/inbound/tools/{tool['id']}/test", json={"input": {"name": "Sam"}}, headers=_h(t))
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True and ok.json()["status"] == 200 and ok.json()["response"] == {"open": "9 to 5"}
    assert requests[0]["headers"]["x-api-key"] == "k-123" and requests[0]["headers"]["idempotency-key"].startswith(
        "test:"
    )
    assert b'"Sam"' in requests[0]["body"]

    missing = await client.post(f"/inbound/tools/{tool['id']}/test", json={"input": {}}, headers=_h(t))
    assert missing.status_code == 422 and "name is required" in missing.json()["detail"]

    down = await client.post(f"/inbound/tools/{tool['id']}/test", json={"input": {"name": "Sam"}}, headers=_h(t))
    assert down.status_code == 200 and down.json()["ok"] is False and "connect" in down.json()["error"]


async def test_tool_runs_show_in_history_and_in_the_call(client):
    t = await create_test_tenant()
    lead = await _add_internal(client, t)
    agent = await _agent(client, t)
    async with tenant_session(t) as s:
        call = Call(
            tenant_id=t, agent_snapshot={"name": "Front desk"}, channel="browser_test", status="completed", model="m"
        )
        s.add(call)
        await s.flush()
        s.add(
            ToolExecution(
                tenant_id=t,
                call_id=call.id,
                tool_id=UUID(lead["id"]),
                tool_name="create_lead",
                input={"phone": "+14155550123"},
                output={"ok": True},
                success=True,
                error=None,
                duration_ms=42,
                idempotency_key="k1",
            )
        )
        call_id = str(call.id)
    history = (await client.get("/inbound/tool-executions", headers=_h(t))).json()
    assert [(e["tool_name"], e["success"], e["call_id"]) for e in history] == [("create_lead", True, call_id)]
    detail = (await client.get(f"/inbound/calls/{call_id}", headers=_h(t))).json()
    assert (
        detail["tool_executions"][0]["input"] == {"phone": "+14155550123"}
        and detail["tool_executions"][0]["duration_ms"] == 42
    )
    assert (await client.get("/inbound/tool-executions", headers=_h(await create_test_tenant()))).json() == []
    assert agent["id"]


async def test_tool_changes_are_audited(client):
    t = await create_test_tenant()
    tool = await _create(client, t)
    await client.put(f"/inbound/tools/{tool['id']}", json=_tool(description="x"), headers=_h(t))
    await client.delete(f"/inbound/tools/{tool['id']}", headers=_h(t))
    async with tenant_session(t) as s:
        actions = (await s.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["voice.tool.created", "voice.tool.updated", "voice.tool.deleted"]
