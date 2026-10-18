"""Run lifecycle: requesting a manual run, the stuck-run guard, and the measured return rates a run uses."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import current_tenant, tenant_session
from clinic_core.events import emit
from clinic_core.features import Event, JobContext
from clinic_db.models.core import Service, Tenant
from clinic_db.models.reactivation import CampaignTarget, Run, RunPatient, RunType, Settings
from clinic_reactivation.analysis.engine import ERR_BAD_TIMEZONE, RunFailed, RunResult, analyse
from clinic_reactivation.analysis.facts import BadTimezone, load_facts
from clinic_reactivation.analysis.revenue import MeasuredRate
from clinic_reactivation.analysis.scoring import PastResponse
from clinic_reactivation.analysis.settings import ReactivationSettings

log = logging.getLogger(__name__)

# Event asking the worker to execute a queued run. Payload: {run_id}. Delivery is at least once, so the
# handler (R11) must be idempotent: it does nothing unless the run is still queued.
#
# Contract (kept by `_request_queued`): when a run finishes, completed or failed, RUN_REQUESTED is emitted for the
# practice's queued run, if any, in the same transaction, so a queued run is never orphaned. POST /runs also
# re-emits for a queued run whenever no run is running, which covers a run that was reaped without the job
# getting to promote.
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


# --- executing a run (the RUN_REQUESTED handler) -------------------------------------------------------

ERR_FACTS_QUERY_FAILED = "facts_query_failed"
ERR_BAD_SETTINGS = "bad_settings"
ERR_INTERNAL = "internal_error"
BATCH = 1000  # result rows per INSERT


async def on_run_requested(ctx: JobContext, event: Event) -> None:
    """Event handler. Idempotent: a run that is not queued is skipped, so a duplicate delivery does nothing."""
    try:
        run_id = uuid.UUID(str(event.payload["run_id"]))
    except (KeyError, ValueError):
        log.warning("%s event %s has no usable run_id; dropped", RUN_REQUESTED, event.id)
        return
    await execute_run(ctx.tenant_id, run_id)


async def execute_run(tenant_id: uuid.UUID, run_id: uuid.UUID, *, now: datetime | None = None) -> str:
    """Run the analysis for one queued run. Returns "skipped", "busy", "completed" or "failed".

    Short transactions: claim (queued to running), load (read only), progress updates, then ONE transaction that
    saves every result row and marks the run completed. A failure rolls the save back and a new transaction marks
    the run failed. `now` is the analysis date (as_of); real clock times are used for started_at and finished_at.
    """
    began = time.monotonic()
    as_of = now or datetime.now(UTC)
    outcome, settings_json = await _claim(tenant_id, run_id)
    if settings_json is None:
        return outcome
    try:
        settings = _validated(settings_json)
        loaded = await _load(tenant_id, settings, as_of)
        await _set_progress(tenant_id, run_id, 10)
        result = await asyncio.to_thread(
            analyse,
            loaded.facts,
            settings,
            loaded.measured,
            loaded.responders,
            loaded.previous_dormant_ids,
            as_of,
            loaded.tz_name,
            service_names=loaded.service_names,
            verify_determinism=True,
        )
        await _set_progress(tenant_id, run_id, 60)
        saved = await _save(tenant_id, run_id, result, loaded.previous_run_id)
    except RunFailed as e:
        code, detail = e.error_code, e.detail
    except Exception as e:  # noqa: BLE001 - recorded as internal_error; class name only, never the message
        code, detail = ERR_INTERNAL, type(e).__name__
    else:
        if not saved:
            log.info("run %s was no longer running at save time; nothing saved", run_id)
            return "skipped"
        s = result.summary
        log.info(
            "run %s completed in %.1fs: patients read %s, scored %s, dormant %s",
            run_id, time.monotonic() - began, s["patients_total"], s["patients_scored"], s["dormant_count"],
        )  # fmt: skip
        return "completed"
    await _fail(tenant_id, run_id, code, detail)
    log.warning("run %s failed after %.1fs: %s %s", run_id, time.monotonic() - began, code, detail)
    return "failed"


async def _request_queued(session: AsyncSession) -> None:
    """The orphan rule: when a run finishes, ask for the practice's queued run, in the finishing transaction."""
    queued = await session.scalar(select(Run.id).where(Run.status == "queued").limit(1))
    if queued is not None:
        await emit(session, RUN_REQUESTED, {"run_id": str(queued)})


REAP_JOB = "reap_stuck_runs"
REAP_EVERY_SECONDS = 300


async def reap_stuck_runs(ctx: JobContext, data: dict) -> None:
    """Scheduled job. A worker that dies mid-run leaves the run "running", which blocks the queue, and an event
    can be lost (a worker without this handler drops it). So: fail runs stuck past STUCK_AFTER, then, if nothing
    is running, ask again for the queued run. Asking twice is harmless: the handler skips a run already claimed."""
    reaped = await fail_stuck_runs(ctx.session, datetime.now(UTC))
    if reaped:
        log.warning("failed %d stuck run(s) for tenant %s", reaped, ctx.tenant_id)
    if not await ctx.session.scalar(select(Run.id).where(Run.status == "running").limit(1)):
        await _request_queued(ctx.session)


async def _claim(tenant_id: uuid.UUID, run_id: uuid.UUID) -> tuple[str, dict | None]:
    """queued to running under a row lock. Not queued: skipped. Another run running: busy (it will request us)."""
    try:
        async with tenant_session(tenant_id) as session:
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None or run.status != "queued":
                return "skipped", None
            run.status, run.started_at, run.progress_pct = "running", datetime.now(UTC), 0
            await session.flush()  # the unique index refuses here if another run is running
            return "claimed", run.settings
    except IntegrityError as e:
        if "uq_runs_one_running" not in str(e):
            raise
        return "busy", None


def _validated(settings_json: dict) -> ReactivationSettings:
    try:
        return ReactivationSettings.model_validate(settings_json)
    except ValidationError:
        raise RunFailed(ERR_BAD_SETTINGS, "the settings stored on this run no longer pass validation") from None


@dataclass(frozen=True)
class _Loaded:
    tz_name: str
    facts: list
    measured: dict[str, MeasuredRate]
    responders: dict[uuid.UUID, PastResponse]
    previous_run_id: uuid.UUID | None
    previous_dormant_ids: set[uuid.UUID] | None
    service_names: dict[uuid.UUID, str]


async def _load(tenant_id: uuid.UUID, settings: ReactivationSettings, now: datetime) -> _Loaded:
    async with tenant_session(tenant_id) as session:
        tz_name = (await session.get(Tenant, tenant_id)).timezone
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise RunFailed(ERR_BAD_TIMEZONE, "the practice's time zone is not recognised") from None
        try:
            facts = await load_facts(session, now, tz_name, cohort_min=settings.limits.spend_cohort_minimum)
        except BadTimezone:
            raise RunFailed(ERR_BAD_TIMEZONE, "the practice's time zone is not recognised") from None
        except Exception as e:  # noqa: BLE001 - class name only: the message could carry patient data
            raise RunFailed(ERR_FACTS_QUERY_FAILED, type(e).__name__) from None
        measured = await load_measured_rates(session, now, settings.revenue.attribution_window_days)
        previous_run_id, previous_ids = await _previous_dormant(session)
        names = {sid: name for sid, name in (await session.execute(select(Service.id, Service.name))).all()}
        return _Loaded(tz_name, facts, measured, await _past_responders(session), previous_run_id, previous_ids, names)


async def _past_responders(session: AsyncSession) -> dict[uuid.UUID, PastResponse]:
    """Contacted by any past campaign: BOOKED if any of their targets booked, else NOT_BOOKED. Others: absent."""
    rows = await session.execute(
        select(CampaignTarget.patient_id, CampaignTarget.status)
        .where(CampaignTarget.status.in_(("contacted", "booked")))
        .distinct()
    )
    out: dict[uuid.UUID, PastResponse] = {}
    for patient_id, status in rows:
        if status == "booked":
            out[patient_id] = PastResponse.BOOKED
        else:
            out.setdefault(patient_id, PastResponse.NOT_BOOKED)
    return out


async def _previous_dormant(session: AsyncSession) -> tuple[uuid.UUID | None, set[uuid.UUID] | None]:
    """The latest completed run and its dormant patients, or (None, None) when it cannot be used.

    Unusable means no completed run, no integer summary.dormant_count, or fewer stored dormant rows than that
    count (the patient rows were purged, or a patient was deleted). A count of 0 is a real, empty previous run.
    """
    previous = (
        await session.execute(
            select(Run.id, Run.summary)
            .where(Run.status == "completed")
            .order_by(Run.finished_at.desc(), Run.id.desc())
            .limit(1)
        )
    ).first()
    if previous is None:
        return None, None
    expected = (previous.summary or {}).get("dormant_count")
    if not isinstance(expected, int) or isinstance(expected, bool):
        return None, None
    ids = set(
        await session.scalars(
            select(RunPatient.patient_id).where(RunPatient.run_id == previous.id, RunPatient.status == "dormant")
        )
    )
    if len(ids) < expected:
        return None, None
    return previous.id, ids


async def _set_progress(tenant_id: uuid.UUID, run_id: uuid.UUID, pct: int) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(update(Run).where(Run.id == run_id, Run.status == "running").values(progress_pct=pct))


async def _insert_patients(session: AsyncSession, run: Run, result: RunResult, as_json: list[dict]) -> None:
    rows = [
        {
            "tenant_id": run.tenant_id,
            "run_id": run.id,
            "patient_id": p.patient_id,
            "status": p.status,
            "primary_type": p.primary_type,
            "matched_types": list(p.matched_types),
            "last_visit_at": p.last_visit_at,
            "days_since_last_visit": p.days_since_last_visit,
            "overdue_ratio": p.overdue_ratio,
            "visit_count": p.visit_count,
            "total_spend_cents": p.total_spend_cents,
            "usual_service_id": p.usual_service_id,
            "usual_provider_id": p.usual_provider_id,
            "revenue_basis_cents": p.revenue_basis_cents,
            "revenue_kind": p.revenue_kind,
            "likelihood_score": p.likelihood_score,
            "points": j["points"],
            "change": p.change,
            "reasons": list(p.reasons),
        }
        for p, j in zip(result.patients, as_json, strict=True)
    ]
    for i in range(0, len(rows), BATCH):
        await session.execute(insert(RunPatient), rows[i : i + BATCH])


async def _insert_types(session: AsyncSession, run: Run, result: RunResult) -> None:
    rows = [
        {"tenant_id": run.tenant_id, "run_id": run.id, **{f.name: getattr(t, f.name) for f in fields(t)}}
        for t in result.types
    ]
    for i in range(0, len(rows), BATCH):
        await session.execute(insert(RunType), rows[i : i + BATCH])


async def _save(tenant_id: uuid.UUID, run_id: uuid.UUID, result: RunResult, previous_run_id: uuid.UUID | None) -> bool:
    """Every result row and the completed status in one transaction. False if the run is no longer running."""
    data = result.to_dict()
    async with tenant_session(tenant_id) as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.status != "running":
            return False
        await _insert_patients(session, run, result, data["patients"])
        await _insert_types(session, run, result)
        run.summary, run.quality = data["summary"], data["quality"]
        run.previous_run_id, run.progress_pct = previous_run_id, 100
        run.status, run.finished_at = "completed", datetime.now(UTC)
        await session.flush()
        await _request_queued(session)
    return True


async def _fail(tenant_id: uuid.UUID, run_id: uuid.UUID, code: str, detail: str) -> None:
    async with tenant_session(tenant_id) as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.status != "running":
            return
        run.status, run.error_code, run.error_detail = "failed", code, detail or None
        run.finished_at = datetime.now(UTC)
        await session.flush()
        await _request_queued(session)
