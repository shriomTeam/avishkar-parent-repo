import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_core.database import current_tenant
from clinic_db.models.core import StaffRole, Tenant
from clinic_db.models.reactivation import Run, Settings
from clinic_reactivation.analysis.settings import ReactivationSettings, compute_next_run

router = APIRouter()

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]
SUMMARY_VIEWERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK))]


class SettingsOut(BaseModel):
    version: int
    config: ReactivationSettings
    defaults: ReactivationSettings = ReactivationSettings()  # what "reset to defaults" means
    next_run_at: datetime | None
    timezone: str
    updated_by: str | None


class LastRunOut(BaseModel):
    id: uuid.UUID
    trigger: str
    status: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress_pct: int


class ScheduleOut(BaseModel):
    next_run_at: datetime | None
    settings_version: int
    last_run: LastRunOut | None


async def _timezone(session: AsyncSession) -> str:
    return (await session.get(Tenant, current_tenant(session))).timezone


async def _current(session: AsyncSession) -> Settings | None:
    return await session.scalar(select(Settings).where(Settings.tenant_id == current_tenant(session)))


def config_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """Which settings differ, as ``{setting, from, to}`` with dotted names, in name order.

    Numbers, switches and fixed words only. A setting that holds a map (rebooking days by category or service) is
    named without its keys or values, because the keys are the clinic's own words.
    """
    changes: list[dict[str, Any]] = []

    def walk(path: str, a: Any, b: Any) -> None:
        if isinstance(a, dict) and isinstance(b, dict) and not path.startswith("dormant.rebooking_days_by_"):
            for key in sorted(a.keys() | b.keys()):
                walk(f"{path}.{key}" if path else key, a.get(key), b.get(key))
        elif a != b:
            if isinstance(a, dict) or isinstance(b, dict):
                changes.append({"setting": path})
            else:
                changes.append({"setting": path, "from": a, "to": b})

    walk("", old, new)
    return changes


def _parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().removeprefix("W/").strip('"')
    return int(value) if value.isdigit() else None


@router.get("/settings", response_model=SettingsOut, dependencies=MANAGERS)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    row, tz = await _current(session), await _timezone(session)
    if row is None:
        return SettingsOut(version=0, config=ReactivationSettings(), next_run_at=None, timezone=tz, updated_by=None)
    return SettingsOut(
        version=row.version,
        config=ReactivationSettings.model_validate(row.config),
        next_run_at=row.next_run_at,
        timezone=tz,
        updated_by=row.updated_by,
    )


@router.put("/settings", response_model=SettingsOut, dependencies=MANAGERS)
async def put_settings(
    body: ReactivationSettings,
    if_match: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> SettingsOut:
    stale = HTTPException(412, "settings changed since you loaded them; reload and retry")
    row = await _current(session)
    current_version = row.version if row else 0
    if _parse_if_match(if_match) != current_version:
        raise stale

    tz = await _timezone(session)
    try:
        next_run_at = compute_next_run(body.schedule, tz, datetime.now(UTC))
    except ZoneInfoNotFoundError:
        raise HTTPException(409, f"the practice's time zone {tz!r} is not recognised") from None
    config = body.model_dump(mode="json")
    new_version = current_version + 1
    try:
        before = ReactivationSettings.model_validate(row.config).model_dump(mode="json") if row else None
    except ValueError:
        before = None  # a stored config that no longer validates: every setting counts as changed
    changes = config_changes(before if before is not None else ReactivationSettings().model_dump(mode="json"), config)

    if row is None:
        row = Settings(
            tenant_id=current_tenant(session),
            version=new_version,
            config=config,
            next_run_at=next_run_at,
            updated_by=ctx.actor_id,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            raise stale from None  # another first save won the race
    else:
        result = await session.execute(
            update(Settings)
            .where(Settings.id == row.id, Settings.version == current_version)
            .values(
                version=new_version,
                config=config,
                next_run_at=next_run_at,
                updated_by=ctx.actor_id,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            raise stale  # a concurrent save got there first

    await audit(
        session,
        "reactivation.settings.saved",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="reactivation_settings",
        entity_id=row.id,
        details={"from_version": current_version, "to_version": new_version, "changes": changes},
    )
    return SettingsOut(version=new_version, config=body, next_run_at=next_run_at, timezone=tz, updated_by=ctx.actor_id)


@router.get("/schedule", response_model=ScheduleOut, dependencies=SUMMARY_VIEWERS)
async def get_schedule(session: AsyncSession = Depends(get_session)) -> ScheduleOut:
    row = await _current(session)
    last = await session.scalar(select(Run).order_by(Run.queued_at.desc()).limit(1))
    return ScheduleOut(
        next_run_at=row.next_run_at if row else None,
        settings_version=row.version if row else 0,
        last_run=LastRunOut(
            id=last.id,
            trigger=last.trigger,
            status=last.status,
            queued_at=last.queued_at,
            started_at=last.started_at,
            finished_at=last.finished_at,
            progress_pct=last.progress_pct,
        )
        if last
        else None,
    )
