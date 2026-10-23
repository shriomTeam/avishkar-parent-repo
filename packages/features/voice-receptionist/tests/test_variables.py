import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Tenant
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import Call
from clinic_voice_receptionist.inbound.router import router as inbound_router
from clinic_voice_receptionist.variables import service
from clinic_voice_receptionist.variables.router import router as variables_router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(inbound_router)
app.include_router(variables_router)


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _variable(client, tenant, name="hours", value="Monday to Friday, 9 to 5"):
    r = await client.post("/inbound/variables", json={"name": name, "value": value}, headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def _agent(client, tenant, **overrides):
    body = {"name": "Front desk", "prompt": "You answer calls for the clinic."} | overrides
    return await client.post("/inbound/agents", json=body, headers=_h(tenant))


# ---- the pure parts ----------------------------------------------------------------------------------------


def test_placeholders_are_found_once_in_order_and_whitespace_is_allowed():
    assert service.placeholders("Hi {{ clinic_name }}, {{hours}} and {{clinic_name}}", None, "{{Odd}}") == [
        "clinic_name",
        "hours",
        "Odd",
    ]
    assert service.placeholders("{{ }} {{1bad}} {single} plain") == []


def test_resolving_fills_known_names_once_and_leaves_the_rest():
    values = {"hours": "9 to 5", "tricky": "{{hours}}"}
    assert service.resolve("Open {{hours}}. {{ tricky }} {{missing}}", values) == "Open 9 to 5. {{hours}} {{missing}}"
    assert service.resolve(None, values) is None


def test_built_in_values_use_the_clinic_clock():
    moment = datetime(2026, 10, 22, 19, 5, tzinfo=UTC)  # 3:05 PM in New York
    values = service.builtin_values(
        agent_name="Front desk", clinic_name="Glow", timezone="America/New_York", caller_number=None, now=moment
    )
    assert values == {
        "agent_name": "Front desk",
        "clinic_name": "Glow",
        "caller_number": "not available",
        "current_date": "Thursday, 22 October 2026",
        "current_time": "3:05 PM",
    }
    late = service.builtin_values(
        agent_name="a", clinic_name="c", timezone="Asia/Kolkata", caller_number="+1", now=moment
    )
    assert late["current_time"] == "12:35 AM" and late["current_date"] == "Friday, 23 October 2026"
    assert late["caller_number"] == "+1"


# ---- the API -----------------------------------------------------------------------------------------------


async def test_create_list_update_and_delete_a_variable(client):
    t = await create_test_tenant()
    made = await _variable(client, t)
    assert made["name"] == "hours" and made["used_by"] == []
    listing = (await client.get("/inbound/variables", headers=_h(t))).json()
    assert [v["name"] for v in listing["custom"]] == ["hours"]
    assert {b["name"] for b in listing["builtin"]} == service.BUILTIN_NAMES
    assert all(b["description"] and b["example"] for b in listing["builtin"])

    changed = await client.put(f"/inbound/variables/{made['id']}", json={"value": "  Daily 8 to 6 "}, headers=_h(t))
    assert changed.status_code == 200 and changed.json()["value"] == "Daily 8 to 6"
    assert (await client.delete(f"/inbound/variables/{made['id']}", headers=_h(t))).status_code == 204
    assert (await client.get("/inbound/variables", headers=_h(t))).json()["custom"] == []
    async with tenant_session(t) as s:
        actions = (await s.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["voice.variable.created", "voice.variable.updated", "voice.variable.deleted"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"name": "Hours", "value": "x"}, 422),  # not snake_case
        ({"name": "1hours", "value": "x"}, 422),
        ({"name": "ho urs", "value": "x"}, 422),
        ({"name": "a" * 65, "value": "x"}, 422),
        ({"name": "hours", "value": "   "}, 422),
        ({"name": "hours", "value": "x" * 1001}, 422),
        ({"name": "clinic_name", "value": "x"}, 409),  # built in
    ],
)
async def test_invalid_variables_are_refused(client, body, status):
    t = await create_test_tenant()
    r = await client.post("/inbound/variables", json=body, headers=_h(t))
    assert r.status_code == status
    if status == 409:
        assert "built in" in r.json()["detail"]


async def test_names_are_unique_and_cannot_change(client):
    t = await create_test_tenant()
    made = await _variable(client, t)
    again = await client.post("/inbound/variables", json={"name": "hours", "value": "other"}, headers=_h(t))
    assert again.status_code == 409
    renamed = await client.put(
        f"/inbound/variables/{made['id']}", json={"name": "opening", "value": "x"}, headers=_h(t)
    )
    assert renamed.json()["name"] == "hours"  # only the value is accepted


async def test_only_managers_read_or_change_variables_and_clinics_are_separate(client):
    t, other = await create_test_tenant(), await create_test_tenant()
    made = await _variable(client, t)
    assert (await client.get("/inbound/variables", headers=_h(t, "front_desk"))).status_code == 403
    denied = await client.post("/inbound/variables", json={"name": "x", "value": "y"}, headers=_h(t, "front_desk"))
    assert denied.status_code == 403
    assert (await client.get("/inbound/variables", headers=_h(other))).json()["custom"] == []
    assert (
        await client.put(f"/inbound/variables/{made['id']}", json={"value": "hacked"}, headers=_h(other))
    ).status_code == 404
    assert (await client.delete(f"/inbound/variables/{made['id']}", headers=_h(other))).status_code == 404
    same_name = await client.post("/inbound/variables", json={"name": "hours", "value": "mine"}, headers=_h(other))
    assert same_name.status_code == 201  # names are unique per clinic, not globally


async def test_agents_may_only_use_variables_that_exist(client):
    t = await create_test_tenant()
    refused = await _agent(client, t, prompt="Open {{hours}} at {{clinic_name}} {{Nope}}")
    assert refused.status_code == 422
    assert "{{hours}}" in refused.json()["detail"] and "{{Nope}}" in refused.json()["detail"]
    assert "{{clinic_name}}" not in refused.json()["detail"]  # built in, so fine
    await _variable(client, t)
    ok = await _agent(client, t, prompt="Open {{hours}} at {{clinic_name}}", greeting="Hi from {{ clinic_name }}")
    assert ok.status_code == 201
    typo = await client.put(
        f"/inbound/agents/{ok.json()['id']}",
        json={"name": "Front desk", "prompt": "Open {{hourz}}"},
        headers=_h(t),
    )
    assert typo.status_code == 422 and "{{hourz}}" in typo.json()["detail"]


async def test_a_variable_in_use_cannot_be_deleted_until_the_prompt_stops_using_it(client):
    t = await create_test_tenant()
    made = await _variable(client, t)
    agent = (await _agent(client, t, prompt="Open {{hours}}")).json()
    assert (await client.get("/inbound/variables", headers=_h(t))).json()["custom"][0]["used_by"] == ["Front desk"]
    blocked = await client.delete(f"/inbound/variables/{made['id']}", headers=_h(t))
    assert blocked.status_code == 409 and "Front desk" in blocked.json()["detail"]
    await client.put(
        f"/inbound/agents/{agent['id']}", json={"name": "Front desk", "prompt": "No variables."}, headers=_h(t)
    )
    assert (await client.delete(f"/inbound/variables/{made['id']}", headers=_h(t))).status_code == 204


async def test_a_test_call_gets_the_prompt_with_variables_filled_in(client):
    t = await create_test_tenant()
    async with tenant_session(t) as s:
        tenant = await s.get(Tenant, t)
        tenant.timezone = "Asia/Kolkata"
    await _variable(client, t, value="9 to 5, {{agent_name}} is not expanded")
    agent = (
        await _agent(
            client,
            t,
            prompt=(
                "You are {{agent_name}} at {{clinic_name}}. Hours: {{hours}}. "
                "Today is {{current_date}}. Caller: {{caller_number}}."
            ),
            greeting="Welcome to {{clinic_name}}!",
        )
    ).json()
    started = await client.post(f"/inbound/agents/{agent['id']}/test-call", headers=_h(t))
    assert started.status_code == 201
    async with tenant_session(t) as s:
        call = await s.get(Call, uuid.UUID(started.json()["call_id"]))
        tenant = await s.get(Tenant, t)
        snapshot = call.agent_snapshot
    assert snapshot["prompt"].startswith(f"You are Front desk at {tenant.name}. Hours: 9 to 5, {{{{agent_name}}}} is")
    assert "not available" in snapshot["prompt"] and "{{" not in snapshot["greeting"]
    assert snapshot["greeting"] == f"Welcome to {tenant.name}!"
    # The saved agent keeps its template, so later edits and changes to a variable still apply to the next call.
    assert (await client.get(f"/inbound/agents/{agent['id']}", headers=_h(t))).json()["prompt"].count("{{") == 5
