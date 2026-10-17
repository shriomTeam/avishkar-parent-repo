import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_db.models.core import StaffRole
from clinic_db.models.reactivation import Run
from clinic_reactivation import runs as run_service

router = APIRouter()

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]
VIEWERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK))]

HEADLINE_KEYS = (
    "patients_total",
    "dormant_count",
    "at_risk_count",
    "new_revenue_low_cents",
    "new_revenue_high_cents",
    "retention_value_cents",
    "at_risk_revenue_cents",
)


class RunOut(BaseModel):
    id: uuid.UUID
    trigger: str
    status: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress_pct: int
    error_code: str | None
    settings_version: int
    settings_source: str


class RunListItem(RunOut):
    headline: dict[str, Any] | None


class RunDetail(RunOut):
    summary: dict[str, Any] | None
    quality: dict[str, Any] | None


class RunRequested(RunOut):
    # "idempotency_key": same key as an earlier request; "already_queued": a queued run was returned instead.
    deduplicated: str | None


def _base(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "queued_at": run.queued_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "progress_pct": run.progress_pct,
        "error_code": run.error_code,
        "settings_version": run.settings_version,
        "settings_source": run_service.settings_source(run),
    }


@router.post("/runs", response_model=RunRequested, status_code=202, dependencies=MANAGERS)
async def request_run(
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=100),
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> RunRequested:
    """Run now. 202 for a new run; 200 when this repeats an earlier request or a run is already queued."""
    request = await run_service.request_manual(
        session, actor_id=ctx.actor_id, idempotency_key=idempotency_key or None, now=datetime.now(UTC)
    )
    if not request.created:
        response.status_code = 200
    return RunRequested(**_base(request.run), deduplicated=request.deduplicated)


@router.get("/runs", response_model=list[RunListItem], dependencies=VIEWERS)
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[RunListItem]:
    runs = (await session.scalars(select(Run).order_by(Run.queued_at.desc(), Run.id.desc()).limit(20))).all()
    return [
        RunListItem(
            **_base(r),
            headline={k: r.summary[k] for k in HEADLINE_KEYS if k in r.summary} if r.summary else None,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=RunDetail, dependencies=VIEWERS)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> RunDetail:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return RunDetail(**_base(run), summary=run.summary, quality=run.quality)
