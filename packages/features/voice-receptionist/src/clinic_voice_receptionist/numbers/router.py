"""Phone numbers: search, buy, assign to an agent and release. Buying costs money, so only managers can do it."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_core.database import tenant_session
from clinic_db.models.core import StaffRole
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.numbers import service
from clinic_voice_receptionist.numbers.client import client_for, voice_url
from clinic_voice_receptionist.numbers.twilio import NumbersClient, TwilioError

router = APIRouter(prefix="/inbound/numbers", tags=["voice_receptionist"])

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


class NumberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    number: str
    kind: str
    provider: str
    agent_id: uuid.UUID | None
    created_at: datetime


class NumbersOut(BaseModel):
    numbers: list[NumberOut]
    enabled: bool  # false when Twilio is not set up on this server
    calls_enabled: bool  # false when this server has no public address for Twilio to send incoming calls to
    max_numbers: int


class AvailableOut(BaseModel):
    number: str
    locality: str
    region: str
    kind: str


class BuyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str = Field(max_length=20)
    agent_id: uuid.UUID | None = None


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID | None = None


def _client(request: Request) -> NumbersClient | None:
    return client_for(request.app)


def _required_client(request: Request) -> NumbersClient:
    client = _client(request)
    if client is None:
        raise HTTPException(409, "Phone numbers are not set up on this server yet.")
    return client


def _voice_url() -> str | None:
    return voice_url()


@router.get("", response_model=NumbersOut)
async def list_numbers(request: Request, session: AsyncSession = Depends(get_session)) -> NumbersOut:
    return NumbersOut(
        numbers=[NumberOut.model_validate(n) for n in await service.list_numbers(session)],
        enabled=_client(request) is not None,
        calls_enabled=_voice_url() is not None,
        max_numbers=get_voice_settings().max_numbers_per_clinic,
    )


@router.get("/available", response_model=list[AvailableOut], dependencies=MANAGERS)
async def search_numbers(
    request: Request,
    kind: Literal["local", "toll_free"] = "local",
    area_code: str | None = Query(default=None, pattern=r"^[2-9]\d{2}$"),
    contains: str | None = Query(default=None, pattern=r"^\d{1,7}$"),
) -> list[AvailableOut]:
    """Numbers that can be bought right now. Searching is free."""
    try:
        found = await _required_client(request).search(kind=kind, area_code=area_code, contains=contains)
    except TwilioError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return [AvailableOut(number=n.number, locality=n.locality, region=n.region, kind=n.kind) for n in found]


@router.post("", response_model=NumberOut, status_code=201, dependencies=MANAGERS)
async def buy_number(body: BuyIn, request: Request, ctx: RequestContext = Depends(get_request_context)) -> NumberOut:
    """Buy the number. The purchase is committed before the answer goes back, and undone if it cannot be saved."""
    client = _required_client(request)
    bought: str | None = None
    try:
        async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as session:
            row = await service.buy(
                session,
                tenant_id=ctx.tenant_id,
                staff_id=_staff_id(ctx),
                number=body.number,
                agent_id=body.agent_id,
                client=client,
                settings=get_voice_settings(),
                voice_url=_voice_url(),
            )
            bought = row.provider_sid
            await audit(
                session,
                "voice.number.purchased",
                actor_type="staff",
                actor_id=ctx.actor_id,
                entity_type="voice.phone_number",
                entity_id=row.id,
            )
            out = NumberOut.model_validate(row)
    except service.NumberError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except TwilioError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except Exception:
        if bought:  # the purchase went through but could not be saved (for example at commit)
            await service.give_back(client, bought)
        raise
    return out


@router.put("/{number_id}", response_model=NumberOut, dependencies=MANAGERS)
async def assign_number(
    number_id: uuid.UUID,
    body: AssignIn,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> NumberOut:
    try:
        row = await service.assign(session, number_id, body.agent_id, client=_client(request), voice_url=_voice_url())
    except (service.NumberError, TwilioError) as exc:
        raise HTTPException(exc.status, str(exc)) from None
    await audit(
        session,
        "voice.number.assigned",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.phone_number",
        entity_id=row.id,
    )
    return NumberOut.model_validate(row)


@router.delete("/{number_id}", status_code=204, dependencies=MANAGERS)
async def release_number(
    number_id: uuid.UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        row = await service.release(session, number_id, _required_client(request))
    except service.NumberError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except TwilioError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    await audit(
        session,
        "voice.number.released",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.phone_number",
        entity_id=row.id,
    )


def _staff_id(ctx: RequestContext) -> uuid.UUID | None:
    try:
        return uuid.UUID(ctx.actor_id)
    except ValueError:
        return None
