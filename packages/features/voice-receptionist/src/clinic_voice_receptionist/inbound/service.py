import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.voice import (
    Agent,
    AgentField,
    AgentTool,
    Call,
    CallEvent,
    CallFieldValue,
    CallTurn,
    Tool,
    ToolExecution,
)
from clinic_voice_receptionist.inbound.schemas import AgentIn, FieldIn
from clinic_voice_receptionist.variables import service as variables

MAX_EVENTS_RETURNED = 5000  # a 10-minute call is well under this; the cap only guards the response size


class NameTaken(Exception):
    pass


class UnknownTool(Exception):
    pass


class UnknownVariables(Exception):
    def __init__(self, names: list[str]):
        super().__init__(", ".join(names))
        self.names = names


async def get_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    return await session.get(Agent, agent_id)


async def agent_fields(session: AsyncSession, agent_id: uuid.UUID) -> list[AgentField]:
    q = select(AgentField).where(AgentField.agent_id == agent_id).order_by(AgentField.position)
    return list((await session.scalars(q)).all())


async def fields_by_agent(session: AsyncSession, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[AgentField]]:
    out: dict[uuid.UUID, list[AgentField]] = {a: [] for a in agent_ids}
    q = select(AgentField).where(AgentField.agent_id.in_(agent_ids)).order_by(AgentField.position)
    for f in (await session.scalars(q)).all():
        out[f.agent_id].append(f)
    return out


async def tool_ids_by_agent(session: AsyncSession, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {a: [] for a in agent_ids}
    q = select(AgentTool.agent_id, AgentTool.tool_id).where(AgentTool.agent_id.in_(agent_ids))
    for agent_id, tool_id in (await session.execute(q)).all():
        out[agent_id].append(tool_id)
    return out


async def attached_tools(session: AsyncSession, agent_id: uuid.UUID) -> list[Tool]:
    """The agent's tools that are switched on. These are what a new call is allowed to use."""
    q = (
        select(Tool)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(AgentTool.agent_id == agent_id, Tool.enabled.is_(True))
        .order_by(Tool.name)
    )
    return list((await session.scalars(q)).all())


async def _sync_tools(session: AsyncSession, agent: Agent, wanted: list[uuid.UUID]) -> None:
    wanted_set = set(wanted)
    if wanted_set:
        known = set((await session.scalars(select(Tool.id).where(Tool.id.in_(wanted_set)))).all())
        if known != wanted_set:
            raise UnknownTool()
    current = {
        row.tool_id: row
        for row in (await session.scalars(select(AgentTool).where(AgentTool.agent_id == agent.id))).all()
    }
    for tool_id, row in current.items():
        if tool_id not in wanted_set:
            await session.delete(row)
    for tool_id in wanted_set - set(current):
        session.add(AgentTool(tenant_id=agent.tenant_id, agent_id=agent.id, tool_id=tool_id))


async def list_agents(session: AsyncSession) -> list[Agent]:
    return list((await session.scalars(select(Agent).order_by(Agent.created_at.desc()))).all())


async def _name_taken(session: AsyncSession, name: str, *, except_id: uuid.UUID | None = None) -> bool:
    q = select(func.count()).select_from(Agent).where(Agent.name == name)
    if except_id:
        q = q.where(Agent.id != except_id)
    return bool(await session.scalar(q))


async def _sync_fields(session: AsyncSession, agent: Agent, wanted: list[FieldIn]) -> None:
    """Match the stored fields to ``wanted`` by key, so captured values keep pointing at their field."""
    existing = {f.key: f for f in await agent_fields(session, agent.id)}
    for position, item in enumerate(wanted):
        values = item.model_dump(exclude={"key"}) | {"position": position}
        if item.key in existing:
            stored = existing.pop(item.key)
            for name, value in values.items():
                setattr(stored, name, value)
        else:
            session.add(AgentField(tenant_id=agent.tenant_id, agent_id=agent.id, key=item.key, **values))
    for removed in existing.values():
        await session.delete(removed)


async def save_agent(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    body: AgentIn,
    model: str,
    agent: Agent | None = None,
    staff_id: uuid.UUID | None = None,
) -> Agent:
    if await _name_taken(session, body.name, except_id=agent.id if agent else None):
        raise NameTaken(body.name)
    if missing := await variables.unknown_names(session, body.prompt, body.greeting):
        raise UnknownVariables(missing)
    values = body.model_dump(exclude={"fields", "tool_ids"})
    if agent is None:
        agent = Agent(tenant_id=tenant_id, model=model, created_by_staff_id=staff_id, **values)
        session.add(agent)
        await session.flush()
    else:
        for name, value in values.items():
            setattr(agent, name, value)
    await _sync_fields(session, agent, body.fields)
    await _sync_tools(session, agent, body.tool_ids)
    await session.flush()
    await session.refresh(agent)  # picks up server-side timestamps
    return agent


async def list_calls(
    session: AsyncSession, *, agent_id: uuid.UUID | None, limit: int, offset: int
) -> list[tuple[Call, int]]:
    """Calls newest first, each with how many details the agent captured."""
    captured = select(CallFieldValue.call_id, func.count().label("n")).group_by(CallFieldValue.call_id).subquery()
    q = (
        select(Call, func.coalesce(captured.c.n, 0))
        .outerjoin(captured, captured.c.call_id == Call.id)
        .order_by(Call.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if agent_id:
        q = q.where(Call.agent_id == agent_id)
    return [(call, n) for call, n in (await session.execute(q)).all()]


async def call_detail(session: AsyncSession, call_id: uuid.UUID, *, include_events: bool):
    call = await session.get(Call, call_id)
    if call is None:
        return None
    turns = (await session.scalars(select(CallTurn).where(CallTurn.call_id == call_id).order_by(CallTurn.seq))).all()
    values = (
        await session.execute(
            select(CallFieldValue.key, AgentField.label, CallFieldValue.value)
            .join(AgentField, AgentField.id == CallFieldValue.agent_field_id, isouter=True)
            .where(CallFieldValue.call_id == call_id)
            .order_by(CallFieldValue.created_at)
        )
    ).all()
    executions = (
        await session.scalars(
            select(ToolExecution)
            .where(ToolExecution.call_id == call_id)
            .order_by(ToolExecution.created_at, ToolExecution.id)
        )
    ).all()
    events = []
    if include_events:
        q = select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq).limit(MAX_EVENTS_RETURNED)
        events = list((await session.scalars(q)).all())
    return call, list(turns), list(values), events, list(executions)
