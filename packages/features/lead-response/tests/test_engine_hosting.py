"""How the platform worker hosts the engine: the job, the schedule, and the hook, as the platform lists and calls
them."""

from datetime import timedelta

from lr_engine import jobs_of_kind, seed_text, tasks_of
from lr_gateway import make_lead
from lr_host import make_host
from lr_intake import Counter, Intake, sid, twilio_pairs

from clinic_core.database import tenant_session
from clinic_core.features import JobContext, Schedule, job_name, load_features
from clinic_lead_response import runtime
from clinic_lead_response.engine.tick import TICK_EVERY_SECONDS, TICK_JOB
from clinic_lead_response.feature import feature


def test_the_feature_registers_one_job_and_one_schedule_of_sixty_seconds():
    assert set(feature.jobs) == {"tick"} and feature.jobs["tick"] is runtime.worker_handler
    assert list(feature.schedules) == [Schedule("tick", 60)]
    assert (TICK_JOB, TICK_EVERY_SECONDS) == ("tick", 60)


def test_there_is_no_loop_inside_the_api():
    assert feature.on_startup is None  # the engine is hosted by the worker only


def test_the_feature_is_still_not_available_so_nothing_is_offered_to_a_clinic():
    assert feature.available is False


def worker_job_table():
    """What apps/worker builds from the installed features (``_job_handlers`` there), written out the same way."""
    return {job_name(f.key, name): handler for f in load_features().values() for name, handler in f.jobs.items()}


def test_the_worker_would_list_the_tick_under_the_name_it_enqueues():
    table = worker_job_table()
    assert table["lead_response.tick"] is runtime.worker_handler
    assert job_name(feature.key, TICK_JOB) == "lead_response.tick"


def test_every_schedule_of_every_installed_feature_names_a_job_the_worker_can_run():
    table = worker_job_table()
    for installed in load_features().values():
        for schedule in installed.schedules:
            assert job_name(installed.key, schedule.job) in table, (installed.key, schedule.job)


def test_our_schedule_is_listed_among_the_installed_features():
    ours = load_features()["lead_response"]
    assert [(s.job, s.every_seconds) for s in ours.schedules] == [("tick", 60)]


async def test_the_worker_calls_the_job_the_way_it_calls_any_feature_job(make_tenant, monkeypatch):
    """apps/worker: ``handler(JobContext(tenant_id=..., session=...), data)`` inside a tenant session."""
    host = make_host()
    monkeypatch.setattr(runtime, "get_scheduler", lambda: host.scheduler)
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    handler = worker_job_table()["lead_response.tick"]
    async with tenant_session(tenant) as session:
        await handler(JobContext(tenant_id=tenant, session=session), {})
    assert len(host.provider.requests) == 1 and len(await tasks_of(tenant)) == 1


async def test_called_for_real_with_the_switch_off_the_job_does_nothing(make_tenant):
    runtime.get_scheduler.cache_clear()
    runtime.get_engine.cache_clear()
    try:
        tenant = await make_tenant()
        async with tenant_session(tenant) as session:
            ctx = JobContext(tenant_id=tenant, session=session)
            with Counter() as statements:
                await runtime.worker_handler(ctx, {})
        assert statements == []
    finally:
        runtime.get_scheduler.cache_clear()
        runtime.get_engine.cache_clear()


async def test_the_features_own_route_calls_the_hook_when_a_text_is_stored(make_tenant, monkeypatch):
    """Proof that feature.py passes the hook: the feature's real router, the shared fast path swapped for a test one."""
    host = make_host()
    monkeypatch.setattr(runtime, "get_fast_path", lambda: host.fast)
    tenant = await make_tenant()
    response = await Intake(monkeypatch).post(tenant, twilio_pairs(MessageSid=sid(1)))  # the feature's own router
    assert response.status_code == 200
    await host.fast.drain()
    assert len(host.provider.requests) == 1 and len(await tasks_of(tenant)) == 1


async def test_by_default_the_features_route_does_nothing_beyond_storing_the_text(make_tenant, monkeypatch):
    runtime.get_fast_path.cache_clear()
    runtime.get_engine.cache_clear()
    try:
        tenant = await make_tenant()
        intake = Intake(monkeypatch)
        with Counter() as statements:
            response = await intake.post(tenant, twilio_pairs(MessageSid=sid(1)))
        assert response.status_code == 200 and len(statements) == 12  # a new lead, exactly as before the engine existed
        assert await tasks_of(tenant) == []
        (job,) = await jobs_of_kind(tenant, "ack")
        assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)
    finally:
        runtime.get_fast_path.cache_clear()
        runtime.get_engine.cache_clear()


def test_the_shared_objects_are_built_once():
    runtime.get_engine.cache_clear()
    runtime.get_scheduler.cache_clear()
    runtime.get_fast_path.cache_clear()
    try:
        assert runtime.get_engine() is runtime.get_engine()
        assert runtime.get_scheduler() is runtime.get_scheduler()
        assert runtime.get_fast_path() is runtime.get_fast_path()
        assert runtime.get_scheduler()._engine is runtime.get_engine()
        assert runtime.get_fast_path()._engine is runtime.get_engine()
        assert runtime.get_engine().gateway is runtime.get_gateway()  # the same gateway intake uses
    finally:
        runtime.get_engine.cache_clear()
        runtime.get_scheduler.cache_clear()
        runtime.get_fast_path.cache_clear()


def test_the_timer_is_never_asked_to_fire_more_often_than_the_worker_can_tick():
    # the worker looks at its schedules every 30 seconds, so 60 is a whole number of its looks
    assert TICK_EVERY_SECONDS % 30 == 0 and timedelta(seconds=TICK_EVERY_SECONDS) == timedelta(minutes=1)
