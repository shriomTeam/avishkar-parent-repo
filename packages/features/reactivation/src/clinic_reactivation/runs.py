"""Run lifecycle: requesting a manual run, the stuck-run guard, and the measured return rates a run uses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import current_tenant
from clinic_core.events import emit
from clinic_db.models.reactivation import Run, Settings
from clinic_reactivation.analysis.revenue import MeasuredRate
from clinic_reactivation.analysis.settings import ReactivationSettings

# Event asking the worker to execute a queued run. Payload: {run_id}. Delivery is at least once, so the
# handler (R11) must be idempotent: it does nothing unless the run is still queued.
#
# R11 CONTRACT: when a run finishes (completed or failed), the handler must emit RUN_REQUESTED for the
# practice's queued run, if any, so a queued run is never orphaned. POST /runs also re-emits for a queued run
# whenever no run is running, which covers a run that was reaped without the handler getting to promote.
RUN_REQUESTED = "reactivation.run.requested"

# Pulled forward from the reaper. The build spec's check_due uses 45 minutes and "run_timeout"; reconcile there.
STUCK_AFTER = timedelta(minutes=30)
ERR_TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class RunRequest:
    run: Run
    created: bool
    deduplicated: str | None  # "idempotency_key" | "already_queued" | None
    settings_source: str  # "saved" | "defaults"


async def fail_stuck_runs(session: AsyncSession, now: datetime) -> int:
    """Mark runs that have been running too long as failed, so they stop blocking the queue."""
    result = await session.execute(
        update(Run)
        .where(
            Run.status == "running",
            func.coalesce(Run.started_at, Run.queued_at) < now - STUCK_AFTER,
        )
        .values(status="failed", error_code=ERR_TIMED_OUT, finished_at=now)
    )
    return result.rowcount


def settings_source(run: Run) -> str:
    return "defaults" if run.settings_version == 0 else "saved"


async def _by_key(session: AsyncSession, key: str | None) -> Run | None:
    if key is None:
        return None
    return await session.scalar(select(Run).where(Run.idempotency_key == key))


async def _queued(session: AsyncSession) -> Run | None:
    return await session.scalar(select(Run).where(Run.status == "queued"))


async def request_manual(
    session: AsyncSession, *, actor_id: str, idempotency_key: str | None, now: datetime
) -> RunRequest:
    """Create a queued manual run, or return the one this request is a repeat of.

    Order: stuck-run guard, same key, existing queued run, else insert. A queued run is (re-)requested
    whenever nothing is running, however it was found.
    """
    await fail_stuck_runs(session, now)

    run, dedup = await _by_key(session, idempotency_key), "idempotency_key"
    if run is None:
        run, dedup = await _queued(session), "already_queued"

    saved = await session.scalar(select(Settings))
    created = False
    if run is None:
        # No saved row is version 0, with the defaults copied in; version 0 therefore always means defaults.
        config = saved.config if saved else ReactivationSettings().model_dump(mode="json")
        run = Run(
            tenant_id=current_tenant(session),
            trigger="manual",
            status="queued",
            requested_by=actor_id,
            idempotency_key=idempotency_key,
            settings_version=saved.version if saved else 0,
            settings=config,
        )
        try:
            async with session.begin_nested():
                session.add(run)
                await session.flush()
            created, dedup = True, None
        except IntegrityError:
            # Lost a race on the key or the queued slot: return the winner.
            run, dedup = await _by_key(session, idempotency_key), "idempotency_key"
            if run is None:
                run, dedup = await _queued(session), "already_queued"
            if run is None:
                raise

    if created:
        await audit(
            session,
            "reactivation.run.requested",
            actor_type="staff",
            actor_id=actor_id,
            entity_type="reactivation_run",
            entity_id=run.id,
            details={"trigger": "manual", "settings_version": run.settings_version},
        )
    if run.status == "queued" and not await session.scalar(select(Run.id).where(Run.status == "running").limit(1)):
        await emit(session, RUN_REQUESTED, {"run_id": str(run.id)})
    return RunRequest(run=run, created=created, deduplicated=dedup, settings_source=settings_source(run))


# Contacted: distinct patients whose target was texted (contacted or booked). Pending targets were skipped
# at launch and opted-out targets asked to stop, so neither counts. Booked: distinct among them whose
# booking was recorded inside the attribution window after launch. Only campaigns created from a run type
# (type_key set, no free-form audience) whose window has fully elapsed feed a rate. "No audience" is SQL NULL
# or JSON null: SQLAlchemy stores an explicit Python None in a JSONB column as JSON null.
_MEASURED_SQL = text(
    """
SELECT c.type_key,
       count(DISTINCT t.patient_id) FILTER (WHERE t.status IN ('contacted', 'booked')) AS contacted,
       count(DISTINCT t.patient_id) FILTER (
         WHERE t.status = 'booked'
           AND t.booked_at >= c.launched_at
           AND t.booked_at <= c.launched_at + make_interval(days => CAST(:window AS integer))
       ) AS booked
FROM reactivation.campaigns c
JOIN reactivation.campaign_targets t ON t.campaign_id = c.id
WHERE c.tenant_id = :tenant_id AND t.tenant_id = :tenant_id
  AND c.type_key IS NOT NULL
  AND (c.audience IS NULL OR jsonb_typeof(c.audience) = 'null')
  AND c.launched_at IS NOT NULL
  AND c.launched_at + make_interval(days => CAST(:window AS integer)) <= CAST(:now AS timestamptz)
GROUP BY c.type_key
"""
)


async def load_measured_rates(session: AsyncSession, now: datetime, window_days: int) -> dict[str, MeasuredRate]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rows = await session.execute(
        _MEASURED_SQL, {"now": now, "window": window_days, "tenant_id": current_tenant(session)}
    )
    return {
        row.type_key: MeasuredRate(booked=min(int(row.booked), int(row.contacted)), contacted=int(row.contacted))
        for row in rows
    }
