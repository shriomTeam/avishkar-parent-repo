import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_db.models.core import StaffRole
from clinic_db.models.voice import Tool, ToolExecution
from clinic_voice_receptionist.inbound.schemas import (
    CatalogItemOut,
    InternalToolIn,
    ToolExecutionOut,
    ToolIn,
    ToolOut,
    ToolTestIn,
    ToolTestOut,
)
from clinic_voice_receptionist.tools import service
from clinic_voice_receptionist.tools.runner import build_request, execute
from clinic_voice_receptionist.tools.schema import check_args

router = APIRouter(prefix="/inbound", tags=["voice_receptionist"])

# Finish tool transactions before sending success: callers immediately reload the catalog.
MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


async def _tool_or_404(session: AsyncSession, tool_id: uuid.UUID) -> Tool:
    tool = await session.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(404, "tool not found")
    return tool


async def _audit(session: AsyncSession, ctx: RequestContext, action: str, tool_id: uuid.UUID) -> None:
    await audit(session, action, actor_type="staff", actor_id=ctx.actor_id, entity_type="voice.tool", entity_id=tool_id)


@router.get("/tools", response_model=list[ToolOut], dependencies=MANAGERS)
async def list_tools(session: AsyncSession = Depends(get_session, scope="function")) -> list[ToolOut]:
    return [service.tool_out(t) for t in await service.list_tools(session)]


@router.get("/tools/catalog", response_model=list[CatalogItemOut], dependencies=MANAGERS)
async def tool_catalog(session: AsyncSession = Depends(get_session, scope="function")) -> list[dict]:
    """The internal tools a clinic can add, and which it already has."""
    return await service.catalog(session)


@router.post("/tools/internal", response_model=ToolOut, status_code=201, dependencies=MANAGERS)
async def add_internal_tool(
    body: InternalToolIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ToolOut:
    try:
        tool = await service.add_builtin(session, ctx.tenant_id, body.builtin_key)
    except service.ToolNameTaken as exc:
        raise HTTPException(409, str(exc)) from None
    except service.ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    await _audit(session, ctx, "voice.tool.created", tool.id)
    return service.tool_out(tool)


@router.post("/tools", response_model=ToolOut, status_code=201, dependencies=MANAGERS)
async def create_tool(
    body: ToolIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ToolOut:
    try:
        tool = await service.save_tool(session, tenant_id=ctx.tenant_id, body=body)
    except service.ToolNameTaken as exc:
        raise HTTPException(409, str(exc)) from None
    except service.ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    await _audit(session, ctx, "voice.tool.created", tool.id)
    return service.tool_out(tool)


@router.get("/tools/{tool_id}", response_model=ToolOut, dependencies=MANAGERS)
async def get_tool(tool_id: uuid.UUID, session: AsyncSession = Depends(get_session, scope="function")) -> ToolOut:
    return service.tool_out(await _tool_or_404(session, tool_id))


@router.put("/tools/{tool_id}", response_model=ToolOut, dependencies=MANAGERS)
async def update_tool(
    tool_id: uuid.UUID,
    body: ToolIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ToolOut:
    tool = await _tool_or_404(session, tool_id)
    try:
        await service.save_tool(session, tenant_id=ctx.tenant_id, body=body, tool=tool)
    except service.ToolNameTaken as exc:
        raise HTTPException(409, str(exc)) from None
    except service.ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    await _audit(session, ctx, "voice.tool.updated", tool.id)
    return service.tool_out(tool)


@router.delete("/tools/{tool_id}", status_code=204, dependencies=MANAGERS)
async def delete_tool(
    tool_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> None:
    """Agents stop using it; past executions keep the tool's name. An internal tool can be added again later."""
    tool = await _tool_or_404(session, tool_id)
    await session.execute(delete(Tool).where(Tool.id == tool.id))
    await _audit(session, ctx, "voice.tool.deleted", tool_id)


@router.post("/tools/{tool_id}/test", response_model=ToolTestOut, dependencies=MANAGERS)
async def test_tool(
    tool_id: uuid.UUID,
    body: ToolTestIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ToolTestOut:
    """Really call the endpoint with sample input, through the same safeguards a live call uses."""
    tool = await _tool_or_404(session, tool_id)
    if tool.kind == "builtin":
        raise HTTPException(409, "Built-in tools run during calls. Take a test call to try them.")
    args, errors = check_args(tool.input_schema, body.input)
    if errors:
        raise HTTPException(422, "; ".join(f"{path} {message}" for path, message in errors.items()))
    await _audit(session, ctx, "voice.tool.tested", tool.id)
    request, problem = build_request(
        tool,
        args,
        values=body.field_values,
        call={"id": "test-call", "caller_number": body.caller_number or "+15555550100"},
        labels={},
    )
    if problem:
        raise HTTPException(422, problem.get("error") or "; ".join(f"{k} {v}" for k, v in problem["invalid"].items()))
    outcome = await execute(
        tool,
        args,
        tenant_id=ctx.tenant_id,
        call_id=None,
        key=f"test:{uuid.uuid4()}",
        database_url=ctx.database_url,
        request=request,
    )
    return ToolTestOut(
        ok=outcome.success,
        status=outcome.response.get("status"),
        duration_ms=outcome.duration_ms,
        response=outcome.response.get("response"),
        error=outcome.error,
    )


@router.get("/tool-executions", response_model=list[ToolExecutionOut])
async def recent_executions(
    limit: int = Query(default=25, ge=1, le=100), session: AsyncSession = Depends(get_session, scope="function")
) -> list[ToolExecutionOut]:
    q = select(ToolExecution).order_by(ToolExecution.created_at.desc()).limit(limit)
    return [ToolExecutionOut.model_validate(e) for e in (await session.scalars(q)).all()]
