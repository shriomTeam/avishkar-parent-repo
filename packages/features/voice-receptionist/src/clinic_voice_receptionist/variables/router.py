import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_db.models.core import StaffRole
from clinic_db.models.voice import Variable
from clinic_voice_receptionist.variables import service

router = APIRouter(prefix="/inbound", tags=["voice_receptionist"])

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


class VariableIn(BaseModel):
    name: str
    value: str = Field(min_length=1, max_length=service.MAX_VALUE_LENGTH)

    @field_validator("name")
    @classmethod
    def valid_name(cls, v: str) -> str:
        if not service.NAME_RE.match(v):
            raise ValueError("name must be snake_case: lowercase letters, digits, underscores; start with a letter")
        return v

    @field_validator("value")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class VariableUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=service.MAX_VALUE_LENGTH)

    @field_validator("value")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class VariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    value: str
    used_by: list[str] = Field(default_factory=list)  # names of agents whose prompt or first message uses it
    updated_at: datetime


class BuiltinOut(BaseModel):
    name: str
    description: str
    example: str


class VariablesOut(BaseModel):
    custom: list[VariableOut]
    builtin: list[BuiltinOut]


async def _variable_or_404(session: AsyncSession, variable_id: uuid.UUID) -> Variable:
    variable = await session.get(Variable, variable_id)
    if variable is None:
        raise HTTPException(404, "variable not found")
    return variable


async def _out(session: AsyncSession, variable: Variable) -> VariableOut:
    used = await service.usage(session)
    return VariableOut.model_validate(variable).model_copy(update={"used_by": used.get(variable.name, [])})


async def _audit(session: AsyncSession, ctx: RequestContext, action: str, variable_id: uuid.UUID) -> None:
    await audit(
        session, action, actor_type="staff", actor_id=ctx.actor_id, entity_type="voice.variable", entity_id=variable_id
    )


@router.get("/variables", response_model=VariablesOut, dependencies=MANAGERS)
async def list_variables(session: AsyncSession = Depends(get_session)) -> VariablesOut:
    used = await service.usage(session)
    return VariablesOut(
        custom=[
            VariableOut.model_validate(v).model_copy(update={"used_by": used.get(v.name, [])})
            for v in await service.list_variables(session)
        ],
        builtin=[BuiltinOut(name=b.name, description=b.description, example=b.example) for b in service.BUILTINS],
    )


@router.post("/variables", response_model=VariableOut, status_code=201, dependencies=MANAGERS)
async def create_variable(
    body: VariableIn,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> VariableOut:
    try:
        variable = await service.create(session, tenant_id=ctx.tenant_id, name=body.name, value=body.value)
    except service.NameTaken as exc:
        raise HTTPException(409, str(exc)) from None
    except service.VariableError as exc:
        raise HTTPException(422, str(exc)) from None
    await _audit(session, ctx, "voice.variable.created", variable.id)
    return await _out(session, variable)


@router.put("/variables/{variable_id}", response_model=VariableOut, dependencies=MANAGERS)
async def update_variable(
    variable_id: uuid.UUID,
    body: VariableUpdate,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> VariableOut:
    """Only the value can change: the name is what prompts refer to, so renaming would break them."""
    variable = await _variable_or_404(session, variable_id)
    variable.value = body.value
    await session.flush()
    await session.refresh(variable)
    await _audit(session, ctx, "voice.variable.updated", variable.id)
    return await _out(session, variable)


@router.delete("/variables/{variable_id}", status_code=204, dependencies=MANAGERS)
async def delete_variable(
    variable_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    variable = await _variable_or_404(session, variable_id)
    try:
        await service.delete(session, variable)
    except service.InUse as exc:
        raise HTTPException(
            409, f"Used by {', '.join(exc.agents)}. Remove {{{{{variable.name}}}}} from the prompt first."
        ) from None
    await _audit(session, ctx, "voice.variable.deleted", variable_id)
