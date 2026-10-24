"""Workspace-scoped audit history, filters and bounded-memory CSV export."""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, tuple_

from clinic_core.auth.dependencies import CurrentSession, get_settings
from clinic_core.tenancy.management import workspace_access
from clinic_core.tenancy.schemas import WorkspaceAuditOut
from clinic_db.models.core import Staff
from clinic_db.models.ops import AuditLog

router = APIRouter()


class AuditFilters(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    actor: str | None = None
    action: str | None = None


def filters(
    start_date: date | None = None,
    end_date: date | None = None,
    actor: str | None = Query(None, max_length=150),
    action: str | None = Query(None, max_length=100),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, detail="invalid_date_range")
    if end_date == date.max:
        raise HTTPException(422, detail="invalid_end_date")
    return AuditFilters(start_date=start_date, end_date=end_date, actor=actor, action=action)


def conditions(workspace_id, tenant, query):
    clauses = [AuditLog.tenant_id == workspace_id]
    zone = ZoneInfo(tenant.timezone)
    if query.start_date:
        clauses.append(AuditLog.occurred_at >= datetime.combine(query.start_date, time.min, zone))
    if query.end_date:
        clauses.append(AuditLog.occurred_at < datetime.combine(query.end_date + timedelta(days=1), time.min, zone))
    if query.actor:
        kind, separator, ident = query.actor.partition(":")
        if not separator or not kind:
            raise HTTPException(422, detail="invalid_actor")
        clauses.extend([AuditLog.actor_type == kind, AuditLog.actor_id == (ident or None)])
    if query.action:
        clauses.append(AuditLog.action == query.action)
    return clauses


class AuditOption(BaseModel):
    value: str
    label: str


class AuditOptions(BaseModel):
    actors: list[AuditOption]
    events: list[str]


class AuditPage(BaseModel):
    items: list[WorkspaceAuditOut]
    total: int
    next_cursor: str | None
    page_size: int


async def staff_names(db, workspace_id):
    members = (await db.scalars(select(Staff).where(Staff.tenant_id == workspace_id))).all()
    names = {str(member.id): member.name for member in members}
    # Older invitation acceptance events stored auth.users.id as a staff actor.
    # Resolve only through this workspace's memberships, including inactive ones;
    # never look up arbitrary actor IDs in the global user directory.
    for member in members:
        if member.user_id:
            names.setdefault(str(member.user_id), member.name)
    return names


def actor_label(row, names):
    return (names.get(row.actor_id) or "Unknown member") if row.actor_type == "staff" else row.actor_type


@router.get("/{workspace_id}/audit/options", response_model=AuditOptions)
async def options(workspace_id: UUID, request: Request, principal: CurrentSession):
    async with workspace_access(principal.user.id, workspace_id, get_settings(request), manage=True) as (db, _, _):
        names = await staff_names(db, workspace_id)
        actors = (
            await db.execute(
                select(AuditLog.actor_type, AuditLog.actor_id).where(AuditLog.tenant_id == workspace_id).distinct()
            )
        ).all()
        events = (
            await db.scalars(
                select(AuditLog.action).where(AuditLog.tenant_id == workspace_id).distinct().order_by(AuditLog.action)
            )
        ).all()
        return AuditOptions(
            actors=sorted(
                [
                    AuditOption(value=f"{row.actor_type}:{row.actor_id or ''}", label=actor_label(row, names))
                    for row in actors
                ],
                key=lambda item: (item.label, item.value),
            ),
            events=events,
        )


@router.get("/{workspace_id}/audit", response_model=AuditPage)
async def activity(
    workspace_id: UUID,
    request: Request,
    principal: CurrentSession,
    query: AuditFilters = Depends(filters),
    before: int | None = Query(None, gt=0, le=9223372036854775807),
):
    async with workspace_access(principal.user.id, workspace_id, get_settings(request), manage=True) as (db, tenant, _):
        clauses = conditions(workspace_id, tenant, query)
        total = await db.scalar(select(func.count()).select_from(AuditLog).where(*clauses))
        if before is not None:
            anchor = await db.scalar(select(AuditLog).where(AuditLog.tenant_id == workspace_id, AuditLog.id == before))
            if anchor is None:
                raise HTTPException(422, detail="invalid_audit_cursor")
            clauses.append(tuple_(AuditLog.occurred_at, AuditLog.id) < (anchor.occurred_at, anchor.id))

        rows = (
            await db.scalars(
                select(AuditLog).where(*clauses).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(51)
            )
        ).all()
        next_cursor = str(rows[49].id) if len(rows) > 50 else None
        rows = rows[:50]
        names = await staff_names(db, workspace_id)
        return AuditPage(
            items=[
                WorkspaceAuditOut(
                    id=str(row.id),
                    action=row.action,
                    actor=actor_label(row, names),
                    occurred_at=row.occurred_at.isoformat(),
                )
                for row in rows
            ],
            total=total,
            next_cursor=next_cursor,
            page_size=50,
        )


def csv_line(values):
    output = io.StringIO(newline="")
    # Prevent spreadsheet formula execution in user-controlled actor names.
    csv.writer(output).writerow(
        [
            "'" + str(value)
            if str(value).startswith(("\t", "\r")) or str(value).lstrip().startswith(("=", "+", "-", "@"))
            else str(value)
            for value in values
        ]
    )
    return output.getvalue()


@router.get(
    "/{workspace_id}/audit/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def export(
    workspace_id: UUID, request: Request, principal: CurrentSession, query: AuditFilters = Depends(filters)
):
    settings = get_settings(request)
    # Authorize and validate before sending response headers.
    async with workspace_access(principal.user.id, workspace_id, settings, manage=True) as (db, tenant, _):
        conditions(workspace_id, tenant, query)
        ceiling = await db.scalar(select(func.max(AuditLog.id)).where(AuditLog.tenant_id == workspace_id)) or 0

    async def content():
        yield "\ufeff" + csv_line(
            ["ID", "Event", "Actor", "Actor type", "Actor ID", "Entity type", "Entity ID", "Time (UTC)"]
        )
        cursor = None
        while True:
            # Recheck membership on every batch; never load all history into memory.
            async with workspace_access(principal.user.id, workspace_id, settings, manage=True) as (db, tenant, _):
                clauses = conditions(workspace_id, tenant, query) + [AuditLog.id <= ceiling]
                if cursor:
                    clauses.append(tuple_(AuditLog.occurred_at, AuditLog.id) < cursor)
                rows = (
                    await db.scalars(
                        select(AuditLog)
                        .where(*clauses)
                        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                        .limit(500)
                    )
                ).all()
                names = await staff_names(db, workspace_id)
                batch = [
                    csv_line(
                        [
                            row.id,
                            row.action,
                            actor_label(row, names),
                            row.actor_type,
                            row.actor_id or "",
                            row.entity_type or "",
                            row.entity_id or "",
                            row.occurred_at.astimezone(UTC).isoformat(),
                        ]
                    )
                    for row in rows
                ]
                if rows:
                    cursor = (rows[-1].occurred_at, rows[-1].id)
            yield "".join(batch)
            if len(rows) < 500:
                break

    return StreamingResponse(
        content(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="workspace-audit.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
