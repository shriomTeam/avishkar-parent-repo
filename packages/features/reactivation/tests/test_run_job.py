import asyncio
from datetime import UTC, datetime

import pytest
from factories import NOW, build_messy_tenant
from sqlalchemy import delete, func, select, update

from clinic_core.database import system_session, tenant_session
from clinic_core.features import Event
from clinic_db.models.core import Patient, Service, Tenant
from clinic_db.models.ops import OutboxEvent
from clinic_db.models.reactivation import Run, RunPatient, RunType
from clinic_reactivation import runs
from clinic_reactivation.analysis.engine import RunFailed, analyse
from clinic_reactivation.analysis.facts import load_facts
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.feature import feature
from clinic_reactivation.runs import RUN_REQUESTED, execute_run, on_run_requested

SETTINGS = ReactivationSettings().model_dump(mode="json")


async def _add_run(tenant, status="queued", settings=None, **kw):
    async with tenant_session(tenant) as s:
        run = Run(
            tenant_id=tenant, trigger="manual", status=status, settings_version=0,
            settings=SETTINGS if settings is None else settings, **kw,
        )  # fmt: skip
        s.add(run)
        await s.flush()
        return run.id


async def _run(tenant, run_id):
    async with tenant_session(tenant) as s:
        return await s.get(Run, run_id)


async def _count(tenant, model, run_id=None):
    async with tenant_session(tenant) as s:
        stmt = select(func.count()).select_from(model)
        if run_id is not None:
            stmt = stmt.where(model.run_id == run_id)
        return await s.scalar(stmt)


async def _events(tenant):
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.event_type == RUN_REQUESTED))).all()
    return [r.payload["run_id"] for r in rows]


@pytest.fixture
async def messy():
    return (await build_messy_tenant()).tenant


# --- a full run -----------------------------------------------------------------------------


async def test_full_run_saves_the_engine_result_and_completes(messy):
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "completed"

    async with tenant_session(messy) as s:
        facts = await load_facts(s, NOW, "America/New_York")
        names = {sid: n for sid, n in (await s.execute(select(Service.id, Service.name))).all()}
    expected = analyse(facts, ReactivationSettings(), {}, {}, None, NOW, "America/New_York", service_names=names)

    run = await _run(messy, run_id)
    assert (run.status, run.progress_pct, run.error_code, run.previous_run_id) == ("completed", 100, None, None)
    assert run.started_at and run.finished_at and run.finished_at >= run.started_at
    assert run.summary == expected.to_dict()["summary"] and run.quality == expected.to_dict()["quality"]
    async with tenant_session(messy) as s:
        saved = {
            r.patient_id: (r.status, r.primary_type, r.likelihood_score, r.change)
            for r in (await s.scalars(select(RunPatient).where(RunPatient.run_id == run_id))).all()
        }
        types = {t.type_key: (t.patient_count, t.revenue_low_cents) for t in (await s.scalars(select(RunType))).all()}
    assert saved == {p.patient_id: (p.status, p.primary_type, p.likelihood_score, p.change) for p in expected.patients}
    assert types == {t.type_key: (t.patient_count, t.revenue_low_cents) for t in expected.types}
    assert len(saved) > 0 and all(change == "first_run" for *_, change in saved.values())


async def test_rows_are_inserted_in_batches(messy, monkeypatch):
    monkeypatch.setattr(runs, "BATCH", 3)
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "completed"
    summary = (await _run(messy, run_id)).summary
    assert await _count(messy, RunPatient, run_id) == summary["dormant_count"] + summary["at_risk_count"] > 3


# --- failures -------------------------------------------------------------------------------


async def _assert_failed(tenant, run_id, code, detail=None):
    run = await _run(tenant, run_id)
    assert (run.status, run.error_code) == ("failed", code)
    assert run.finished_at is not None and run.summary is None
    if detail is not None:
        assert run.error_detail == detail
    assert await _count(tenant, RunPatient, run_id) == 0 and await _count(tenant, RunType, run_id) == 0


@pytest.mark.parametrize("code", ["invariant_failed", "too_many_patient_errors"])
async def test_run_failed_from_the_engine_keeps_its_code_and_saves_no_rows(messy, monkeypatch, code):
    def boom(*a, **k):
        raise RunFailed(code, "counts only")

    monkeypatch.setattr(runs, "analyse", boom)
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, code, "counts only")


async def test_facts_query_failure_records_the_class_name_only(messy, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("patient Jane Doe 1980-01-01")

    monkeypatch.setattr(runs, "load_facts", boom)
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, "facts_query_failed", "RuntimeError")


async def test_unknown_timezone_fails_with_bad_timezone(messy):
    async with system_session() as s:
        await s.execute(update(Tenant).where(Tenant.id == messy).values(timezone="Mars/Olympus"))
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, "bad_timezone")


async def test_stored_settings_that_fail_validation_end_failed_with_bad_settings(messy):
    run_id = await _add_run(messy, settings={"unknown_setting": 1})
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, "bad_settings")


async def test_unexpected_exception_is_internal_error_without_the_message(messy, monkeypatch):
    def boom(*a, **k):
        raise ValueError("patient Jane Doe")

    monkeypatch.setattr(runs, "analyse", boom)
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, "internal_error", "ValueError")


async def test_crash_during_the_save_leaves_no_partial_rows(messy, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(runs, "_insert_types", boom)  # runs after the patient rows are inserted
    run_id = await _add_run(messy)
    assert await execute_run(messy, run_id, now=NOW) == "failed"
    await _assert_failed(messy, run_id, "internal_error", "RuntimeError")


# --- idempotency and claiming -----------------------------------------------------------------


async def test_duplicate_deliveries_run_once(messy):
    run_id = await _add_run(messy)
    outcomes = await asyncio.gather(*(execute_run(messy, run_id, now=NOW) for _ in range(3)))
    assert sorted(outcomes) == ["completed", "skipped", "skipped"]
    summary = (await _run(messy, run_id)).summary
    assert await _count(messy, RunPatient, run_id) == summary["dormant_count"] + summary["at_risk_count"]


async def test_completed_and_failed_runs_are_not_rerun(messy, monkeypatch):
    done = await _add_run(messy)
    assert await execute_run(messy, done, now=NOW) == "completed"
    finished = (await _run(messy, done)).finished_at
    assert await execute_run(messy, done, now=NOW) == "skipped"
    assert (await _run(messy, done)).finished_at == finished

    bad = await _add_run(messy, settings={"x": 1})
    assert await execute_run(messy, bad, now=NOW) == "failed"
    assert await execute_run(messy, bad, now=NOW) == "skipped"


async def test_running_run_is_skipped(messy):
    run_id = await _add_run(messy, "running", started_at=datetime.now(UTC))
    assert await execute_run(messy, run_id, now=NOW) == "skipped"
    assert (await _run(messy, run_id)).status == "running"


async def test_claim_while_another_run_is_running_leaves_this_run_queued(messy):
    running = await _add_run(messy, "running", started_at=datetime.now(UTC))
    queued = await _add_run(messy)
    assert await execute_run(messy, queued, now=NOW) == "busy"
    run = await _run(messy, queued)
    assert (run.status, run.started_at) == ("queued", None)
    assert (await _run(messy, running)).status == "running"
    assert await _count(messy, RunPatient) == 0 and await _events(messy) == []


# --- previous run ---------------------------------------------------------------------------------


async def test_second_run_links_the_first_and_reports_change_since_last(messy):
    first = await _add_run(messy)
    await execute_run(messy, first, now=NOW)
    second = await _add_run(messy)
    assert await execute_run(messy, second, now=NOW) == "completed"

    run = await _run(messy, second)
    first_dormant = (await _run(messy, first)).summary["dormant_count"]
    assert run.previous_run_id == first
    assert (run.summary["first_run"], run.summary["newly_dormant"]) == (False, 0)
    assert run.summary["unchanged_dormant"] == first_dormant > 0
    async with tenant_session(messy) as s:
        dormant = (
            await s.scalars(
                select(RunPatient.change).where(RunPatient.run_id == second, RunPatient.status == "dormant")
            )
        ).all()
    assert set(dormant) == {"unchanged"}


async def test_patient_dormant_before_and_at_risk_now_is_returned_since_last(messy):
    first = await _add_run(messy)
    await execute_run(messy, first, now=NOW)
    async with tenant_session(messy) as s:
        at_risk = await s.scalar(
            select(RunPatient.patient_id).where(RunPatient.run_id == first, RunPatient.status == "at_risk")
        )
        await s.execute(
            update(RunPatient)
            .where(RunPatient.run_id == first, RunPatient.patient_id == at_risk)
            .values(status="dormant")
        )
        run = await s.get(Run, first)
        run.summary = {**run.summary, "dormant_count": run.summary["dormant_count"] + 1}
    second = await _add_run(messy)
    await execute_run(messy, second, now=NOW)
    assert (await _run(messy, second)).summary["returned_since_last"] == 1
    async with tenant_session(messy) as s:
        change = await s.scalar(
            select(RunPatient.change).where(RunPatient.run_id == second, RunPatient.patient_id == at_risk)
        )
    assert change == "returned_since_last"


@pytest.mark.parametrize("damage", ["purge_rows", "drop_count"])
async def test_previous_run_without_usable_dormant_ids_counts_as_no_previous_run(messy, damage):
    first = await _add_run(messy)
    await execute_run(messy, first, now=NOW)
    async with tenant_session(messy) as s:
        if damage == "purge_rows":
            await s.execute(delete(RunPatient).where(RunPatient.run_id == first))
        else:
            run = await s.get(Run, first)
            run.summary = {k: v for k, v in run.summary.items() if k != "dormant_count"}
    second = await _add_run(messy)
    await execute_run(messy, second, now=NOW)
    run = await _run(messy, second)
    assert (run.previous_run_id, run.summary["first_run"]) == (None, True)


async def test_previous_run_with_zero_dormant_is_a_real_empty_previous_run(messy):
    empty = await _add_run(messy, "completed", summary={"dormant_count": 0}, finished_at=datetime.now(UTC))
    second = await _add_run(messy)
    await execute_run(messy, second, now=NOW)
    run = await _run(messy, second)
    assert (run.previous_run_id, run.summary["first_run"]) == (empty, False)
    assert run.summary["newly_dormant"] == run.summary["dormant_count"] > 0


# --- the orphan rule ---------------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["completed", "failed"])
async def test_run_queued_behind_a_running_one_is_requested_when_it_finishes(messy, monkeypatch, outcome):
    first = await _add_run(messy)
    holder = {}
    real_load, real_analyse = runs.load_facts, runs.analyse

    async def load_then_queue_another(*a, **k):
        holder["queued"] = await _add_run(messy)  # arrives while the first run is running
        return await real_load(*a, **k)

    def analyse_or_fail(*a, **k):
        if outcome == "failed":
            raise RunFailed("invariant_failed", "x")
        return real_analyse(*a, **k)

    monkeypatch.setattr(runs, "load_facts", load_then_queue_another)
    monkeypatch.setattr(runs, "analyse", analyse_or_fail)
    assert await execute_run(messy, first, now=NOW) == outcome
    assert await _events(messy) == [str(holder["queued"])]
    assert (await _run(messy, holder["queued"])).status == "queued"


async def test_nothing_is_requested_when_no_run_is_queued(messy):
    await execute_run(messy, await _add_run(messy), now=NOW)
    assert await _events(messy) == []


# --- tenancy and wiring -------------------------------------------------------------------------------


async def test_two_practices_do_not_see_each_other(messy):
    other = (await build_messy_tenant()).tenant
    a, b = await _add_run(messy), await _add_run(other)
    await asyncio.gather(execute_run(messy, a, now=NOW), execute_run(other, b, now=NOW))
    assert await _run(messy, b) is None and await _run(other, a) is None
    for tenant, run_id in ((messy, a), (other, b)):
        async with tenant_session(tenant) as s:
            mine = set((await s.scalars(select(Patient.id))).all())
            rows = (await s.scalars(select(RunPatient))).all()
        assert rows and {r.run_id for r in rows} == {run_id} and {r.patient_id for r in rows} <= mine
        assert all(r.tenant_id == tenant for r in rows)


async def test_handler_is_registered_and_runs_the_run(messy):
    assert on_run_requested in feature.event_handlers[RUN_REQUESTED]
    run_id = await _add_run(messy)
    event = Event(id=1, tenant_id=messy, type=RUN_REQUESTED, payload={"run_id": str(run_id)}, created_at=NOW)
    await on_run_requested(type("Ctx", (), {"tenant_id": messy})(), event)
    assert (await _run(messy, run_id)).status in ("completed", "failed")
    await on_run_requested(type("Ctx", (), {"tenant_id": messy})(), event)  # duplicate delivery: nothing happens


@pytest.mark.parametrize("payload", [{}, {"run_id": "not-a-uuid"}])
async def test_malformed_event_is_dropped_without_error(messy, payload):
    event = Event(id=1, tenant_id=messy, type=RUN_REQUESTED, payload=payload, created_at=NOW)
    await on_run_requested(type("Ctx", (), {"tenant_id": messy})(), event)
