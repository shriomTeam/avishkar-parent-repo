import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_db.models.core import Patient, Service, StaffRole
from clinic_db.models.reactivation import Run, RunPatient, RunType
from clinic_reactivation.api.runs import RunDetail, _base
from clinic_reactivation.labels import TYPE_INFO, UNCLASSIFIED

router = APIRouter()

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]
VIEWERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK))]
TYPE_KEYS = tuple(k for k in TYPE_INFO if k != UNCLASSIFIED)


class ActiveRun(BaseModel):
    id: uuid.UUID
    status: str
    progress_pct: int


class LatestRun(RunDetail):
    active_run: ActiveRun | None


class TypeOut(BaseModel):
    type_key: str
    label: str
    description: str
    kind: str | None
    available: bool
    patient_count: int | None
    revenue_low_cents: int | None
    revenue_high_cents: int | None
    rate_low: float | None
    rate_high: float | None
    rate_source: str | None
    top_service_name: str | None


class PatientOut(BaseModel):
    patient_id: uuid.UUID
    display_name: str | None
    status: str
    primary_type: str | None
    matched_types: list[str]
    reasons: list[str]
    usual_service_name: str | None
    last_visit_at: datetime | None
    days_since_last_visit: int | None
    likelihood_score: int | None
    revenue_basis_cents: int
    points: dict[str, Any]


class PatientPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientOut]


async def _completed_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run_not_found")
    if run.status != "completed":
        raise HTTPException(409, "run_not_completed")
    return run


@router.get("/runs/latest", response_model=LatestRun, dependencies=VIEWERS)
async def latest_run(session: AsyncSession = Depends(get_session)) -> LatestRun:
    run = await session.scalar(
        select(Run).where(Run.status == "completed").order_by(Run.finished_at.desc(), Run.id.desc()).limit(1)
    )
    if run is None:
        raise HTTPException(404, "no_completed_run")
    active = await session.scalar(
        select(Run).where(Run.status.in_(("queued", "running"))).order_by(Run.queued_at.desc(), Run.id.desc()).limit(1)
    )
    return LatestRun(
        **_base(run),
        summary=run.summary,
        quality=run.quality,
        active_run=ActiveRun(id=active.id, status=active.status, progress_pct=active.progress_pct) if active else None,
    )


def _enabled_type_keys(run_settings: dict | None, summary: dict | None, stored: set[str]) -> list[str]:
    """Every type the run had switched on (from its settings copy), plus any with a stored row or an
    availability flag, in priority order."""
    configured = (run_settings or {}).get("types") or {}
    keys = set(stored) | set((summary or {}).get("types_data_available") or {})
    keys |= {k for k in TYPE_KEYS if (configured.get(k) or {}).get("enabled")}
    keys &= set(TYPE_KEYS)
    return sorted(keys, key=lambda k: ((configured.get(k) or {}).get("priority", 99), k))  # a tie sorts by key


def type_entries(
    run_settings: dict | None, summary: dict | None, rows: Mapping[str, tuple[Any, str | None]]
) -> list[TypeOut]:
    """The per-type rows of a run, shared by the saved results and the file analysis.

    ``rows`` maps a type key to (a row with the RunType fields, the top service's name).
    """
    summary = summary or {}
    availability = summary.get("types_data_available") or {}
    out: list[TypeOut] = []
    for key in _enabled_type_keys(run_settings, summary, set(rows)):
        info = TYPE_INFO[key]
        row = rows.get(key)
        available = bool(availability.get(key, row is not None))
        if row is None or not available:
            out.append(
                TypeOut(
                    type_key=key,
                    label=info.label,
                    description=info.description,
                    kind=info.kind,
                    available=False,
                    patient_count=None,
                    revenue_low_cents=None,
                    revenue_high_cents=None,
                    rate_low=float(row[0].rate_low) if row else None,
                    rate_high=float(row[0].rate_high) if row else None,
                    rate_source=row[0].rate_source if row else None,
                    top_service_name=None,
                )
            )
            continue
        t, service_name = row
        out.append(
            TypeOut(
                type_key=key,
                label=info.label,
                description=info.description,
                kind=t.revenue_kind,
                available=True,
                patient_count=t.patient_count,
                revenue_low_cents=t.revenue_low_cents,
                revenue_high_cents=t.revenue_high_cents,
                rate_low=float(t.rate_low),
                rate_high=float(t.rate_high),
                rate_source=t.rate_source,
                top_service_name=service_name,
            )
        )
    info = TYPE_INFO[UNCLASSIFIED]
    out.append(
        TypeOut(
            type_key=UNCLASSIFIED,
            label=info.label,
            description=info.description,
            kind=None,
            available=True,
            patient_count=summary.get("unclassified_dormant", 0),
            revenue_low_cents=None,
            revenue_high_cents=None,
            rate_low=None,
            rate_high=None,
            rate_source=None,
            top_service_name=None,
        )
    )
    return out


@router.get("/runs/{run_id}/types", response_model=list[TypeOut], dependencies=VIEWERS)
async def run_types(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> list[TypeOut]:
    run = await _completed_run(session, run_id)
    rows = {
        t.type_key: (t, name)
        for t, name in (
            await session.execute(
                select(RunType, Service.name)
                .outerjoin(Service, Service.id == RunType.top_service_id)
                .where(RunType.run_id == run_id)
            )
        ).all()
    }
    return type_entries(run.settings, run.summary, rows)


@router.get("/runs/{run_id}/patients", response_model=PatientPage, dependencies=MANAGERS)
async def run_patients(
    run_id: uuid.UUID,
    type: str | None = None,
    status: Literal["dormant", "at_risk"] | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> PatientPage:
    if type is not None and type != UNCLASSIFIED and type not in TYPE_KEYS:
        raise HTTPException(422, "unknown_type")
    await _completed_run(session, run_id)

    where = [RunPatient.run_id == run_id]
    if type == UNCLASSIFIED:
        where.append(RunPatient.primary_type.is_(None))
    elif type is not None:
        where.append(RunPatient.primary_type == type)
    if status is not None:
        where.append(RunPatient.status == status)

    total = await session.scalar(select(func.count()).select_from(RunPatient).where(*where)) or 0
    rows = (
        await session.execute(
            select(RunPatient, Patient.first_name, Patient.last_name, Service.name)
            .outerjoin(Patient, Patient.id == RunPatient.patient_id)
            .outerjoin(Service, Service.id == RunPatient.usual_service_id)
            .where(*where)
            .order_by(
                RunPatient.likelihood_score.desc().nulls_last(),
                RunPatient.total_spend_cents.desc(),
                RunPatient.patient_id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        PatientOut(
            patient_id=p.patient_id,
            display_name=" ".join(n.strip() for n in (first, last) if n and n.strip()) or None,
            status=p.status,
            primary_type=p.primary_type,
            matched_types=list(p.matched_types or []),
            reasons=list(p.reasons or []),
            usual_service_name=service_name,
            last_visit_at=p.last_visit_at,
            days_since_last_visit=p.days_since_last_visit,
            likelihood_score=p.likelihood_score,
            revenue_basis_cents=p.revenue_basis_cents,
            points=p.points or {},
        )
        for p, first, last, service_name in rows
    ]
    await audit(
        session,
        "reactivation.patients.read",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="reactivation_run",
        entity_id=run_id,
        details={"type": type, "status": status, "limit": limit, "offset": offset, "returned": len(items)},
    )
    return PatientPage(total=total, limit=limit, offset=offset, items=items)
