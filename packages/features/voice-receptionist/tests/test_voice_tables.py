"""Needs the local database migrated (same as the other integration tests)."""

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import Agent, AgentField, Call, CallEvent, CallFieldValue, CallTurn


def _agent(tenant, name="Front desk"):
    return Agent(tenant_id=tenant, name=name, prompt="Be kind.", model="test-model")


def _call(tenant, agent, **kw):
    return Call(
        tenant_id=tenant,
        agent_id=agent.id,
        agent_snapshot={"name": agent.name},
        channel="browser_test",
        model="test-model",
        **kw,
    )


async def _seed_call(tenant):
    """Agent, one field, and a call with a turn, a raw event and a captured value."""
    async with tenant_session(tenant) as s:
        agent = _agent(tenant)
        s.add(agent)
        await s.flush()
        field = AgentField(tenant_id=tenant, agent_id=agent.id, key="caller_name", label="Name")
        call = _call(tenant, agent)
        s.add_all([field, call])
        await s.flush()
        s.add_all(
            [
                CallTurn(tenant_id=tenant, call_id=call.id, seq=1, speaker="caller", text="Hi", offset_ms=0),
                CallEvent(tenant_id=tenant, call_id=call.id, seq=1, source="model", type="turn", payload={}),
                CallFieldValue(
                    tenant_id=tenant, call_id=call.id, agent_field_id=field.id, key="caller_name", value="Sam"
                ),
            ]
        )
        return agent.id, call.id


async def test_voice_rows_are_isolated_per_tenant():
    a, b = await create_test_tenant(), await create_test_tenant()
    await _seed_call(a)
    async with tenant_session(b) as s:
        for model in (Agent, AgentField, Call, CallTurn, CallEvent, CallFieldValue):
            assert await s.scalar(select(func.count()).select_from(model)) == 0
    async with tenant_session(a) as s:
        assert await s.scalar(select(func.count()).select_from(CallTurn)) == 1


async def test_agent_names_are_unique_per_tenant_only():
    a, b = await create_test_tenant(), await create_test_tenant()
    async with tenant_session(a) as s:
        s.add(_agent(a))
    async with tenant_session(b) as s:
        s.add(_agent(b))
    with pytest.raises(IntegrityError, match="uq_agents_tenant_id_name"):
        async with tenant_session(a) as s:
            s.add(_agent(a))


async def test_field_key_is_unique_within_an_agent():
    t = await create_test_tenant()
    agent_id, _ = await _seed_call(t)
    with pytest.raises(IntegrityError, match="uq_agent_fields_agent_id_key"):
        async with tenant_session(t) as s:
            s.add(AgentField(tenant_id=t, agent_id=agent_id, key="caller_name", label="Again"))


async def test_a_field_can_only_have_one_value_per_call():
    t = await create_test_tenant()
    _, call_id = await _seed_call(t)
    with pytest.raises(IntegrityError, match="uq_call_field_values_call_id_key"):
        async with tenant_session(t) as s:
            s.add(CallFieldValue(tenant_id=t, call_id=call_id, key="caller_name", value="Other"))


async def test_provider_call_id_is_unique_only_when_set():
    t = await create_test_tenant()
    agent_id, _ = await _seed_call(t)
    async with tenant_session(t) as s:
        agent = await s.get(Agent, agent_id)
        s.add_all([_call(t, agent), _call(t, agent)])  # two calls without a provider id are fine
        s.add(_call(t, agent, provider_call_id="CA123"))
    with pytest.raises(IntegrityError, match="uq_voice_calls_tenant_provider_call"):
        async with tenant_session(t) as s:
            s.add(_call(t, agent, provider_call_id="CA123"))


async def test_deleting_an_agent_keeps_its_calls_and_snapshot():
    t = await create_test_tenant()
    agent_id, call_id = await _seed_call(t)
    async with tenant_session(t) as s:
        await s.execute(delete(Agent).where(Agent.id == agent_id))
    async with tenant_session(t) as s:
        call = await s.get(Call, call_id)
        assert call.agent_id is None
        assert call.agent_snapshot == {"name": "Front desk"}
        assert await s.scalar(select(func.count()).select_from(AgentField)) == 0  # fields go with the agent
        assert await s.scalar(select(func.count()).select_from(CallFieldValue)) == 1  # values stay


async def test_deleting_a_call_removes_its_turns_events_and_values():
    t = await create_test_tenant()
    _, call_id = await _seed_call(t)
    async with tenant_session(t) as s:
        await s.execute(delete(Call).where(Call.id == call_id))
    async with tenant_session(t) as s:
        for model in (CallTurn, CallEvent, CallFieldValue):
            assert await s.scalar(select(func.count()).select_from(model)) == 0
