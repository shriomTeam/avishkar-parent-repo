import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.audit import audit
from clinic_db.models.core import Patient, Service
from clinic_db.models.reactivation import Run, RunPatient, RunType
from clinic_reactivation import runs as run_service
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.api.roles import MANAGERS, VIEWERS
from clinic_reactivation.api.runs import RunDetail, run_fields
from clinic_reactivation.labels import TYPE_INFO, UNCLASSIFIED

router = APIRouter()

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
    overdue_ratio: float | None
    revenue_kind: str | None  # "new" or "retention"; None when the patient is not sized
    revenue_low_cents: int | None  # an "about" range: this patient's basis times the type's return rates
    revenue_high_cents: int | None
    offer_service_name: str | None  # the recommended service (points.best_offer), by name
    points: dict[str, Any]


class PatientPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientOut]


class ReportPatient(BaseModel):
    """One row of the Dormant patients report. No contact details and none of the scoring internals."""

    patient_id: uuid.UUID
    display_name: str | None
    status: str
    primary_type: str | None
    reasons: list[str]
    usual_service_name: str | None
    last_visit_at: datetime | None
    days_since_last_visit: int | None
    likelihood_score: int | None
    revenue_basis_cents: int
    revenue_kind: str | None
    revenue_low_cents: int | None
    revenue_high_cents: int | None
    offer_service_name: str | None


class SummaryOut(BaseModel):
    """What the summary report prints: totals and groups, the settings the run used, and no patient rows."""

    run_id: uuid.UUID
    finished_at: datetime | None
    settings_version: int
    settings_source: str
    settings: ReactivationSettings
    summary: dict[str, Any]
    types: list[TypeOut]


class ReportOut(BaseModel):
    run_id: uuid.UUID
    total: int
    patients: list[ReportPatient]


def patient_value_range(
    basis_cents: int, kind: str | None, rate_low: Any, rate_high: Any
) -> tuple[int | None, int | None]:
    """One patient's about-range, shared by the saved list and the file analysis so they cannot differ.

    A retention type is money already paid, so it is the basis itself. A new-revenue type is the basis times
    the type's return-rate range, each end rounded half up to a cent. No basis, no type or no rate: not sized.
    Patients' ranges are rounded one by one, so they need not add up exactly to the type's total.
    """
    if kind is None or basis_cents <= 0:
        return None, None
    if kind == "retention":
        return basis_cents, basis_cents
    if rate_low is None or rate_high is None:
        return None, None

    def scaled(rate: Any) -> int:
        return int((Decimal(basis_cents) * Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    return scaled(rate_low), scaled(rate_high)


def offer_service_id(points: dict[str, Any] | None) -> str | None:
    offer = (points or {}).get("best_offer") or {}
    return offer.get("service_id") if isinstance(offer, dict) else None


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
        **run_fields(run),
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


async def _type_rows(session: AsyncSession, run_id: uuid.UUID) -> dict[str, tuple[Any, str | None]]:
    return {
        t.type_key: (t, name)
        for t, name in (
            await session.execute(
                select(RunType, Service.name)
                .outerjoin(Service, Service.id == RunType.top_service_id)
                .where(RunType.run_id == run_id)
            )
        ).all()
    }


@router.get("/runs/{run_id}/types", response_model=list[TypeOut], dependencies=VIEWERS)
async def run_types(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> list[TypeOut]:
    run = await _completed_run(session, run_id)
    return type_entries(run.settings, run.summary, await _type_rows(session, run_id))


@router.get("/runs/{run_id}/summary", response_model=SummaryOut, dependencies=MANAGERS)
async def run_summary(
    run_id: uuid.UUID,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> SummaryOut:
    """Everything the summary report (PDF) needs, with no patient rows: group totals, the headline figures and the
    settings the run used. One audit entry holding counts only."""
    run = await _completed_run(session, run_id)
    try:
        settings = ReactivationSettings.model_validate(run.settings or {})
    except ValueError:
        raise HTTPException(409, "bad_settings") from None
    types = type_entries(run.settings, run.summary, await _type_rows(session, run_id))
    await audit(
        session,
        "reactivation.summary_report.export",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="reactivation_run",
        entity_id=run_id,
        details={"dormant_count": (run.summary or {}).get("dormant_count"), "groups": len(types)},
    )
    response.headers["Cache-Control"] = "no-store"
    return SummaryOut(
        run_id=run_id,
        finished_at=run.finished_at,
        settings_version=run.settings_version,
        settings_source=run_service.settings_source(run),
        settings=settings,
        summary=run.summary or {},
        types=types,
    )


async def _patient_items(session: AsyncSession, run_id: uuid.UUID, rows: list[Any]) -> list[PatientOut]:
    """The API shape of run_patients rows, shared by the paged list and the report so they cannot differ.

    Each row is (RunPatient, first_name, last_name, usual service name)."""
    rates = {t.type_key: t for t in (await session.scalars(select(RunType).where(RunType.run_id == run_id))).all()}
    offer_ids = {sid for p, *_ in rows if (sid := offer_service_id(p.points))}
    offer_names = {}
    if offer_ids:
        offer_names = {
            str(sid): name
            for sid, name in (
                await session.execute(select(Service.id, Service.name).where(Service.id.in_(offer_ids)))
            ).all()
        }

    def sized(p: RunPatient) -> tuple[int | None, int | None]:
        rate = rates.get(p.primary_type) if p.status == "dormant" and p.primary_type else None
        if rate is None:
            return None, None
        return patient_value_range(p.revenue_basis_cents, rate.revenue_kind, rate.rate_low, rate.rate_high)

    items = []
    for p, first, last, service_name in rows:
        low, high = sized(p)
        items.append(
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
                overdue_ratio=float(p.overdue_ratio) if p.overdue_ratio is not None else None,
                revenue_kind=rates[p.primary_type].revenue_kind if low is not None else None,
                revenue_low_cents=low,
                revenue_high_cents=high,
                offer_service_name=offer_names.get(offer_service_id(p.points) or ""),
                points=p.points or {},
            )
        )
    return items


@router.get("/runs/{run_id}/patients", response_model=PatientPage, dependencies=MANAGERS)
async def run_patients(
    run_id: uuid.UUID,
    type: str | None = None,
    status: Literal["dormant", "at_risk"] | None = None,
    # Search text can appear in request logs (the URL is logged by proxies and load balancers), so it is never
    # written to the audit entry; only whether a search was used is recorded.
    q: str | None = Query(default=None, max_length=100),
    reachable: bool | None = None,
    sort: Literal["likelihood", "value", "overdue"] = "likelihood",
    dir: Literal["asc", "desc"] = "desc",  # noqa: A002 - the query parameter is called dir
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
    term = (q or "").strip()
    if term:
        full_name = func.concat_ws(" ", Patient.first_name, Patient.last_name)
        where.append(
            or_(
                full_name.icontains(term, autoescape=True),
                cast(RunPatient.patient_id, String).istartswith(term, autoescape=True),
            )
        )
    if reachable:
        where.append(RunPatient.points["reachable"]["either"].as_boolean().is_(True))

    joined = select(RunPatient).outerjoin(Patient, Patient.id == RunPatient.patient_id).where(*where)
    total = await session.scalar(select(func.count()).select_from(joined.subquery())) or 0

    key = {
        "likelihood": RunPatient.likelihood_score,
        "value": RunPatient.revenue_basis_cents,
        "overdue": RunPatient.overdue_ratio,
    }[sort]
    primary = key.desc().nulls_last() if dir == "desc" else key.asc().nulls_last()
    rows = (
        await session.execute(
            select(RunPatient, Patient.first_name, Patient.last_name, Service.name)
            .outerjoin(Patient, Patient.id == RunPatient.patient_id)
            .outerjoin(Service, Service.id == RunPatient.usual_service_id)
            .where(*where)
            .order_by(
                primary,
                RunPatient.likelihood_score.desc().nulls_last(),
                RunPatient.total_spend_cents.desc(),
                RunPatient.patient_id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items = await _patient_items(session, run_id, rows)
    await audit(
        session,
        "reactivation.patients.read",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="reactivation_run",
        entity_id=run_id,
        details={
            "type": type,
            "status": status,
            "limit": limit,
            "offset": offset,
            "returned": len(items),
            "sort": sort,
            "dir": dir,
            "reachable": bool(reachable),
            "searched": bool(term),
        },
    )
    return PatientPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/runs/{run_id}/report", response_model=ReportOut, dependencies=MANAGERS)
async def run_report(
    run_id: uuid.UUID,
    response: Response,
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> ReportOut:
    """Every dormant patient of a completed run, for the Export report button, in one call.

    The patient list pages 100 at a time and writes an audit row per page; a report of up to 25,000 patients would
    write hundreds. This is one read and one audit entry holding counts only. Names are patient data, so the response
    is never cached."""
    await _completed_run(session, run_id)
    # Under row-level security the planner picks a nested-loop join here, which took 10 s for 12,000 patients and
    # over 30 s for 25,000; as in the facts query, a hash join takes well under a second.
    await session.execute(text("SET LOCAL enable_nestloop = off"))
    rows = (
        await session.execute(
            select(RunPatient, Patient.first_name, Patient.last_name, Service.name)
            .outerjoin(Patient, Patient.id == RunPatient.patient_id)
            .outerjoin(Service, Service.id == RunPatient.usual_service_id)
            .where(RunPatient.run_id == run_id, RunPatient.status == "dormant")
            .order_by(
                RunPatient.likelihood_score.desc().nulls_last(),
                RunPatient.total_spend_cents.desc(),
                RunPatient.patient_id,
            )
        )
    ).all()
    items = await _patient_items(session, run_id, rows)
    patients = [
        ReportPatient.model_validate(i.model_dump(exclude={"points", "matched_types", "overdue_ratio"})) for i in items
    ]
    await audit(
        session,
        "reactivation.report.export",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="reactivation_run",
        entity_id=run_id,
        details={"patients": len(patients), "groups": len({p.primary_type for p in patients})},
    )
    response.headers["Cache-Control"] = "no-store"
    return ReportOut(run_id=run_id, total=len(patients), patients=patients)
