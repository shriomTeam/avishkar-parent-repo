import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import Call, CallEvent, CallFieldValue, CallTurn
from clinic_voice_receptionist.inbound.router import router

app = FastAPI()
# This isolated router test intentionally exercises the explicit dev-header adapter.
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _body(**overrides):
    body = {
        "name": "Front desk",
        "prompt": "You answer calls for Glow Aesthetics.",
        "greeting": "Thanks for calling Glow!",
        "fields": [
            {"key": "caller_name", "label": "Name", "required": True},
            {"key": "service", "label": "Service", "data_type": "enum", "enum_values": ["botox", "filler"]},
        ],
    }
    return body | overrides


async def _create(client, tenant, **overrides):
    r = await client.post("/inbound/agents", json=_body(**overrides), headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_and_read_back_an_agent(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    assert agent["voice"] == "Puck" and agent["direction"] == "inbound" and agent["model"]
    assert [f["key"] for f in agent["fields"]] == ["caller_name", "service"]
    assert agent["fields"][1]["enum_values"] == ["botox", "filler"]
    got = await client.get(f"/inbound/agents/{agent['id']}", headers=_h(t))
    assert got.json() == agent
    assert [a["id"] for a in (await client.get("/inbound/agents", headers=_h(t))).json()] == [agent["id"]]


async def test_update_keeps_the_ids_of_fields_that_stay(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    kept = agent["fields"][0]["id"]
    body = _body(
        name="Renamed",
        fields=[
            {"key": "reason", "label": "Reason for calling"},
            {"key": "caller_name", "label": "Full name"},
        ],
    )
    r = await client.put(f"/inbound/agents/{agent['id']}", json=body, headers=_h(t))
    assert r.status_code == 200, r.text
    fields = r.json()["fields"]
    assert [f["key"] for f in fields] == ["reason", "caller_name"]  # new order, removed field gone
    assert next(f for f in fields if f["key"] == "caller_name")["id"] == kept
    assert next(f for f in fields if f["key"] == "caller_name")["label"] == "Full name"


async def test_agent_names_must_be_unique_within_a_clinic(client):
    t = await create_test_tenant()
    first = await _create(client, t)
    assert (await client.post("/inbound/agents", json=_body(), headers=_h(t))).status_code == 409
    other = await _create(client, t, name="Second")
    clash = await client.put(f"/inbound/agents/{other['id']}", json=_body(), headers=_h(t))
    assert clash.status_code == 409
    # Saving an agent under its own name is fine, and so is the same name in another clinic.
    assert (await client.put(f"/inbound/agents/{first['id']}", json=_body(), headers=_h(t))).status_code == 200
    await _create(client, await create_test_tenant())


@pytest.mark.parametrize(
    "change",
    [
        {"name": "   "},
        {"prompt": ""},
        {"voice": "NotAVoice"},
        {"language": "english"},
        {"fields": [{"key": "Bad Key", "label": "x"}]},
        {"fields": [{"key": "a", "label": "x"}, {"key": "a", "label": "y"}]},
        {"fields": [{"key": "a", "label": "x", "data_type": "enum"}]},
        {"fields": [{"key": "a", "label": "x", "enum_values": ["one"]}]},
        {"fields": [{"key": f"f{i}", "label": "x"} for i in range(21)]},
    ],
)
async def test_invalid_agents_are_rejected(client, change):
    t = await create_test_tenant()
    r = await client.post("/inbound/agents", json=_body(**change), headers=_h(t))
    assert r.status_code == 422


async def test_only_managers_can_change_agents_but_front_desk_can_read(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    assert (await client.post("/inbound/agents", json=_body(name="x"), headers=_h(t, "front_desk"))).status_code == 403
    r = await client.put(f"/inbound/agents/{agent['id']}", json=_body(), headers=_h(t, "front_desk"))
    assert r.status_code == 403
    assert (await client.delete(f"/inbound/agents/{agent['id']}", headers=_h(t, "front_desk"))).status_code == 403
    assert (await client.get("/inbound/agents", headers=_h(t, "front_desk"))).status_code == 200


async def test_a_clinic_cannot_see_or_change_another_clinics_agent(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    agent = await _create(client, a)
    url = f"/inbound/agents/{agent['id']}"
    assert (await client.get(url, headers=_h(b))).status_code == 404
    assert (await client.put(url, json=_body(), headers=_h(b))).status_code == 404
    assert (await client.delete(url, headers=_h(b))).status_code == 404
    assert (await client.get("/inbound/agents", headers=_h(b))).json() == []


async def test_changes_are_audited(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    await client.put(f"/inbound/agents/{agent['id']}", json=_body(), headers=_h(t))
    await client.delete(f"/inbound/agents/{agent['id']}", headers=_h(t))
    async with tenant_session(t) as s:
        actions = (await s.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["voice.agent.created", "voice.agent.updated", "voice.agent.deleted"]


async def _seed_call(tenant, agent_id):
    async with tenant_session(tenant) as s:
        call = Call(
            tenant_id=tenant,
            agent_id=uuid.UUID(agent_id),
            agent_snapshot={"name": "Front desk"},
            channel="browser_test",
            is_test=True,
            status="completed",
            model="m",
        )
        s.add(call)
        await s.flush()
        s.add_all(
            [
                CallTurn(tenant_id=tenant, call_id=call.id, seq=2, speaker="agent", text="Hello", offset_ms=900),
                CallTurn(tenant_id=tenant, call_id=call.id, seq=1, speaker="caller", text="Hi", offset_ms=0),
                CallEvent(tenant_id=tenant, call_id=call.id, seq=1, source="model", type="turn", payload={"a": 1}),
                CallFieldValue(tenant_id=tenant, call_id=call.id, key="caller_name", value="Sam"),
            ]
        )
        return str(call.id)


async def test_call_detail_orders_turns_and_returns_raw_events_only_on_request(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    call_id = await _seed_call(t, agent["id"])
    detail = (await client.get(f"/inbound/calls/{call_id}", headers=_h(t))).json()
    assert [turn["text"] for turn in detail["turns"]] == ["Hi", "Hello"]
    assert detail["values"] == [{"key": "caller_name", "label": None, "value": "Sam"}]
    assert detail["agent_name"] == "Front desk" and detail["events"] == []
    with_events = (await client.get(f"/inbound/calls/{call_id}?include_events=true", headers=_h(t))).json()
    assert with_events["events"][0]["payload"] == {"a": 1}


async def test_viewing_a_call_is_audited_and_hidden_from_other_clinics(client):
    t, other = await create_test_tenant(), await create_test_tenant()
    call_id = await _seed_call(t, (await _create(client, t))["id"])
    assert (await client.get(f"/inbound/calls/{call_id}", headers=_h(other))).status_code == 404
    await client.get(f"/inbound/calls/{call_id}", headers=_h(t))
    async with tenant_session(t) as s:
        assert "voice.call.viewed" in (await s.scalars(select(AuditLog.action))).all()


async def test_deleting_an_agent_keeps_its_calls_listed(client):
    t = await create_test_tenant()
    agent = await _create(client, t)
    await _seed_call(t, agent["id"])
    assert (await client.delete(f"/inbound/agents/{agent['id']}", headers=_h(t))).status_code == 204
    calls = (await client.get("/inbound/calls", headers=_h(t))).json()
    assert len(calls) == 1 and calls[0]["agent_id"] is None and calls[0]["agent_name"] == "Front desk"


async def test_call_list_pages_and_filters(client):
    t = await create_test_tenant()
    a, b = await _create(client, t), await _create(client, t, name="Second")
    for agent in (a, a, b):
        await _seed_call(t, agent["id"])
    listed = (await client.get("/inbound/calls", headers=_h(t))).json()
    assert len(listed) == 3 and {c["captured_count"] for c in listed} == {1}  # each seeded call captured one value
    assert len((await client.get(f"/inbound/calls?agent_id={a['id']}", headers=_h(t))).json()) == 2
    assert len((await client.get("/inbound/calls?limit=1&offset=2", headers=_h(t))).json()) == 1
    assert (await client.get("/inbound/calls?limit=0", headers=_h(t))).status_code == 422
