from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.database import current_tenant
from clinic_db.models.core import Tenant
from clinic_db.models.lead_response import PracticeSettings
from clinic_lead_response.roles import SETTINGS_EDITORS, SETTINGS_READERS
from clinic_lead_response.settings_audit import audit_settings_saved
from clinic_lead_response.settings_model import AI_AVAILABLE, LeadResponseSettings
from clinic_lead_response.settings_store import columns_from_settings, current_row, settings_from_row

router = APIRouter()

UNIQUE_VIOLATION = "23505"


class LeadResponseSettingsOut(BaseModel):
    version: int
    config: LeadResponseSettings
    defaults: LeadResponseSettings = LeadResponseSettings()  # what "reset to defaults" means
    timezone: str  # the clinic's time zone; hours are read in it. Changed in the workspace settings, not here.
    updated_by: str | None  # the staff id who saved this version, never a name or an email
    updated_at: datetime | None


def _parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().removeprefix("W/").strip('"')
    return int(value) if value.isdigit() else None


def _flat(settings: LeadResponseSettings) -> dict[str, Any]:
    """Setting names for the audit row: the capabilities are spread out (a fixed vocabulary), the rest stay whole."""
    columns = columns_from_settings(settings)
    capabilities = columns.pop("capabilities")
    return {**columns, **{f"capabilities.{name}": on for name, on in capabilities.items()}}


async def _timezone(session: AsyncSession) -> str:
    return (await session.get(Tenant, current_tenant(session))).timezone


def _out(row: PracticeSettings | None, timezone: str) -> LeadResponseSettingsOut:
    return LeadResponseSettingsOut(
        version=row.version if row else 0,
        config=settings_from_row(row),
        timezone=timezone,
        updated_by=row.created_by if row else None,
        updated_at=row.created_at if row else None,
    )


@router.get("/settings", response_model=LeadResponseSettingsOut, dependencies=SETTINGS_READERS)
async def get_settings(session: AsyncSession = Depends(get_session)) -> LeadResponseSettingsOut:
    return _out(await current_row(session), await _timezone(session))


@router.put("/settings", response_model=LeadResponseSettingsOut, dependencies=SETTINGS_EDITORS)
async def put_settings(
    body: LeadResponseSettings,
    if_match: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> LeadResponseSettingsOut:
    stale = HTTPException(412, "settings changed since you loaded them; reload and retry")
    row = await current_row(session)
    current_version = row.version if row else 0
    # A stale save is refused even when nothing in it changed.
    if _parse_if_match(if_match) != current_version:
        raise stale
    if body.uses_ai() and not AI_AVAILABLE:
        raise HTTPException(422, "ai_settings_not_available_yet")

    before = settings_from_row(row)
    timezone = await _timezone(session)
    if body == before:
        return _out(row, timezone)  # current version, nothing changed: no new version and no audit entry

    new_version = current_version + 1
    new_row = PracticeSettings(
        tenant_id=current_tenant(session), version=new_version, created_by=ctx.actor_id, **columns_from_settings(body)
    )
    try:
        async with session.begin_nested():
            session.add(new_row)
            await session.flush()
    except IntegrityError as exc:
        # Two saves of the same version race on the unique (tenant_id, version): the loser is simply stale.
        if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise stale from None
        raise

    await audit_settings_saved(
        session,
        actor_id=ctx.actor_id,
        settings_id=new_row.id,
        from_version=current_version,
        to_version=new_version,
        before=_flat(before),
        after=_flat(body),
    )
    return _out(new_row, timezone)
