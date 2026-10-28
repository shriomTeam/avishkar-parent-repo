import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_core.database import tenant_session
from clinic_db.models.core import StaffRole
from clinic_db.models.voice import Agent, Call
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound import service
from clinic_voice_receptionist.inbound.call_setup import build_snapshot, expire_stale_calls
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.events import INPUT_RATE, OUTPUT_RATE
from clinic_voice_receptionist.inbound.live.storage import CONTENT_TYPE, belongs_to, store_for
from clinic_voice_receptionist.inbound.schemas import (
    AgentIn,
    AgentOut,
    CallDetailOut,
    CallSummaryOut,
    CapturedValueOut,
    EventOut,
    FieldOut,
    TestCallOut,
    ToolExecutionOut,
    TurnOut,
)

router = APIRouter(prefix="/inbound", tags=["voice_receptionist"])

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


async def _audit(session: AsyncSession, ctx: RequestContext, action: str, entity_type: str, entity_id: uuid.UUID):
    await audit(
        session, action, actor_type="staff", actor_id=ctx.actor_id, entity_type=entity_type, entity_id=entity_id
    )


def _unknown_variables_message(names: list[str]) -> str:
    listed = ", ".join("{{" + n + "}}" for n in names)
    return f"Unknown variables: {listed}. Add them on the Variables page, or remove them from the text."


async def _agents_out(session: AsyncSession, agents: list[Agent]) -> list[AgentOut]:
    ids = [a.id for a in agents]
    fields = await service.fields_by_agent(session, ids)
    tool_ids = await service.tool_ids_by_agent(session, ids)
    return [
        AgentOut.model_validate(a, from_attributes=True).model_copy(
            update={"fields": [FieldOut.model_validate(f) for f in fields[a.id]], "tool_ids": tool_ids[a.id]}
        )
        for a in agents
    ]


async def _agent_out(session: AsyncSession, agent: Agent) -> AgentOut:
    return (await _agents_out(session, [agent]))[0]


async def _agent_or_404(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await service.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return agent


@router.get("/agents", response_model=list[AgentOut], dependencies=MANAGERS)
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[AgentOut]:
    return await _agents_out(session, await service.list_agents(session))


@router.post("/agents", response_model=AgentOut, status_code=201, dependencies=MANAGERS)
async def create_agent(
    body: AgentIn, ctx: RequestContext = Depends(get_request_context), session: AsyncSession = Depends(get_session)
) -> AgentOut:
    try:
        agent = await service.save_agent(session, tenant_id=ctx.tenant_id, body=body, model=get_voice_settings().model)
    except service.NameTaken:
        raise HTTPException(409, "An agent with this name already exists.") from None
    except service.UnknownTool:
        raise HTTPException(422, "One of the selected tools no longer exists.") from None
    except service.UnknownVariables as exc:
        raise HTTPException(422, _unknown_variables_message(exc.names)) from None
    await audit(
        session,
        "voice.agent.created",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.agent",
        entity_id=agent.id,
    )
    return await _agent_out(session, agent)


@router.get("/agents/{agent_id}", response_model=AgentOut, dependencies=MANAGERS)
async def get_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> AgentOut:
    return await _agent_out(session, await _agent_or_404(session, agent_id))


@router.put("/agents/{agent_id}", response_model=AgentOut, dependencies=MANAGERS)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> AgentOut:
    agent = await _agent_or_404(session, agent_id)
    try:
        await service.save_agent(session, tenant_id=ctx.tenant_id, body=body, model=agent.model, agent=agent)
    except service.NameTaken:
        raise HTTPException(409, "An agent with this name already exists.") from None
    except service.UnknownTool:
        raise HTTPException(422, "One of the selected tools no longer exists.") from None
    except service.UnknownVariables as exc:
        raise HTTPException(422, _unknown_variables_message(exc.names)) from None
    await audit(
        session,
        "voice.agent.updated",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.agent",
        entity_id=agent.id,
    )
    return await _agent_out(session, agent)


@router.delete("/agents/{agent_id}", status_code=204, dependencies=MANAGERS)
async def delete_agent(
    agent_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Calls stay (they keep a snapshot of the agent); only the agent and its field list go."""
    agent = await _agent_or_404(session, agent_id)
    await session.execute(delete(Agent).where(Agent.id == agent.id))
    await audit(
        session,
        "voice.agent.deleted",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.agent",
        entity_id=agent_id,
    )


@router.get("/calls", response_model=list[CallSummaryOut])
async def list_calls(
    agent_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CallSummaryOut]:
    calls = await service.list_calls(session, agent_id=agent_id, limit=limit, offset=offset)
    return [
        CallSummaryOut.model_validate(c, from_attributes=True).model_copy(
            update={"agent_name": c.agent_snapshot.get("name", ""), "captured_count": captured}
        )
        for c, captured in calls
    ]


@router.get("/calls/{call_id}", response_model=CallDetailOut)
async def get_call(
    call_id: uuid.UUID,
    include_events: bool = False,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> CallDetailOut:
    found = await service.call_detail(session, call_id, include_events=include_events)
    if found is None:
        raise HTTPException(404, "call not found")
    call, turns, values, events, executions = found
    # Transcripts are PHI: record who opened one.
    await audit(
        session,
        "voice.call.viewed",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.call",
        entity_id=call_id,
    )
    return CallDetailOut(
        **CallSummaryOut.model_validate(call, from_attributes=True).model_dump(
            exclude={"agent_name", "captured_count"}
        ),
        agent_name=call.agent_snapshot.get("name", ""),
        captured_count=len(values),
        model=call.model,
        usage=call.usage,
        turns=[TurnOut.model_validate(t) for t in turns],
        values=[CapturedValueOut(key=k, label=label, value=v) for k, label, v in values],
        events=[EventOut.model_validate(e) for e in events],
        tool_executions=[ToolExecutionOut.model_validate(e) for e in executions],
    )


@router.get("/calls/{call_id}/recording")
async def get_recording(
    call_id: uuid.UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The call's audio. The file is found from the call row, never from anything in the request."""
    call = await session.get(Call, call_id)  # row-level security limits this to the clinic's own calls
    name = call.recording_object if call and call.recording_status == "saved" else None
    if call is None or name is None or call.tenant_id != ctx.tenant_id or not belongs_to(name, ctx.tenant_id):
        raise HTTPException(404, "recording not found")
    store = store_for(request.app, get_voice_settings())
    data = await store.get(name) if store else None
    if data is None:
        raise HTTPException(404, "recording not found")
    await _audit(session, ctx, "voice.recording.played", "voice.call", call_id)  # recordings are PHI: who listened
    return Response(data, media_type=CONTENT_TYPE, headers={"Cache-Control": "private, no-store"})


MAX_OPEN_TEST_CALLS = 3


@router.post("/agents/{agent_id}/test-call", response_model=TestCallOut, status_code=201, dependencies=MANAGERS)
async def start_test_call(
    agent_id: uuid.UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> TestCallOut:
    """Create the call record and a one-time ticket the browser uses to open the call WebSocket."""
    agent = await _agent_or_404(session, agent_id)
    if not agent.is_active:
        raise HTTPException(409, "agent is not active")
    voice = get_voice_settings()
    if agent.save_recording and store_for(request.app, voice) is None:
        raise HTTPException(409, "This agent records calls, but recording storage is not set up on this server.")
    now = datetime.now(UTC)
    await expire_stale_calls(session, voice, now)
    open_calls = await session.scalar(
        select(func.count())
        .select_from(Call)
        .where(Call.is_test.is_(True), Call.status.in_(("connecting", "in_progress")))
    )
    if open_calls >= MAX_OPEN_TEST_CALLS:
        raise HTTPException(429, "too many calls in progress; end one and try again")
    # A browser test has no caller number.
    snapshot = await build_snapshot(session, agent, ctx.tenant_id, caller_number=None, now=now)
    call = Call(
        auth_session_id=ctx.session_id,
        tenant_id=ctx.tenant_id,
        agent_id=agent.id,
        agent_snapshot=snapshot,
        direction="inbound",
        channel="browser_test",
        is_test=True,
        status="connecting",
        model=agent.model,
    )
    # The browser opens the call WebSocket the moment it has the ticket. The request's own transaction only commits
    # after the response has gone out, so the call and its ticket are saved in a transaction of their own that is
    # finished before we answer. Otherwise the WebSocket can arrive first and be refused as an unknown ticket.
    async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as own:
        own.add(call)
        await own.flush()
        ticket = tickets.mint(call)
    await _audit(session, ctx, "voice.test_call.started", "voice.call", call.id)
    return TestCallOut(
        call_id=call.id,
        ticket=ticket,
        ws_path="/features/voice_receptionist/inbound/live",
        input_rate=INPUT_RATE,
        output_rate=OUTPUT_RATE,
        max_seconds=voice.max_call_seconds,
    )
