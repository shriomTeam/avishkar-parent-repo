"""The two gates in front of all engine work: the switch, and the clinic having the feature."""

from datetime import timedelta

from lr_engine import add_job, all_jobs, get_job, jobs_of_kind, make_engine, seed_text, tasks_of
from lr_gateway import make_lead
from lr_intake import Counter

from clinic_core.database import system_session
from clinic_core.entitlements import set_feature
from clinic_lead_response.config import get_intake_settings
from clinic_lead_response.engine.service import Engine


async def untouched(tenant, job_id) -> bool:
    job = await get_job(tenant, job_id)
    return (job.status, job.attempts, job.locked_at, job.finished_at) == ("pending", 0, None, None)


# --- the switch ----------------


async def test_with_the_switch_off_nothing_is_claimed_or_sent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine(enabled=False)
    clock.advance(minutes=5)
    assert await engine.run_due(tenant) == 0
    assert provider.requests == [] and await tasks_of(tenant) == []
    (job,) = await jobs_of_kind(tenant, "ack")
    assert await untouched(tenant, job.id)


async def test_with_the_switch_off_no_statement_touches_the_jobs(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, _, _ = make_engine(enabled=False)
    with Counter() as statements:
        await engine.run_due(tenant)
    assert statements == []  # not even a connection


async def test_switching_on_later_loses_nothing(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    state = {"on": False}
    engine, provider, clock = make_engine(enabled=lambda: state["on"])
    clock.advance(minutes=30)
    assert await engine.run_due(tenant) == 0
    state["on"] = True
    assert await engine.run_due(tenant) == 1
    assert len(provider.requests) == 1 and len(await tasks_of(tenant)) == 1


async def test_the_switch_is_looked_at_for_every_batch_not_remembered(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    state = {"on": True}
    engine, provider, clock = make_engine(enabled=lambda: state["on"])
    await seed_text(tenant, lead, n=1)
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 1
    state["on"] = False  # switched off while running
    await seed_text(tenant, lead, n=2)
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 0
    assert len(provider.requests) == 1
    assert any(j.status == "pending" for j in await jobs_of_kind(tenant, "ack"))


async def test_by_default_the_engine_reads_the_real_switch_and_it_is_off(make_tenant, monkeypatch):
    monkeypatch.delenv("LEAD_RESPONSE_ENGINE_ENABLED", raising=False)
    get_intake_settings.cache_clear()
    try:
        tenant = await make_tenant()
        lead = await make_lead(tenant)
        await seed_text(tenant, lead)
        provider_engine, provider, clock = make_engine()
        engine = Engine(provider_engine.gateway, clock=clock)  # no `enabled` given: the environment decides
        clock.advance(seconds=1)
        assert await engine.run_due(tenant) == 0 and provider.requests == []
        monkeypatch.setenv("LEAD_RESPONSE_ENGINE_ENABLED", "true")
        get_intake_settings.cache_clear()
        assert await engine.run_due(tenant) == 1 and len(provider.requests) == 1
    finally:
        get_intake_settings.cache_clear()


# --- the feature ----------------


async def test_a_clinic_without_the_feature_is_never_touched(make_tenant):
    tenant = await make_tenant(())
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    clock.advance(minutes=5)
    assert await engine.run_due(tenant) == 0
    assert provider.requests == [] and await tasks_of(tenant) == []
    (job,) = await jobs_of_kind(tenant, "ack")
    assert await untouched(tenant, job.id)


async def test_a_feature_switched_off_is_not_enough_to_run(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 0 and provider.requests == []


async def test_an_expired_feature_is_not_enough_to_run(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", expires_at=clock() - timedelta(days=1))
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 0 and provider.requests == []


async def test_the_feature_is_checked_again_for_every_batch(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    await seed_text(tenant, lead, n=1)
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 1
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    await seed_text(tenant, lead, n=2)
    clock.advance(seconds=1)
    assert await engine.run_due(tenant) == 0
    assert len(provider.requests) == 1


async def test_the_two_gates_cost_one_statement_set(make_tenant):
    tenant = await make_tenant()
    engine, _, _ = make_engine()
    with Counter() as statements:
        assert await engine.may_run(tenant) is True
    assert len(statements) <= 2  # set_config and the feature read


# --- clinics apart ----------------


async def test_running_one_clinic_leaves_every_other_clinics_jobs_alone(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a, lead_b = await make_lead(a), await make_lead(b)
    await seed_text(a, lead_a)
    await seed_text(b, lead_b)
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    assert await engine.run_due(a) == 1
    assert len(provider.requests) == 1 and len(await tasks_of(a)) == 1 and await tasks_of(b) == []
    (job_b,) = await jobs_of_kind(b, "ack")
    assert await untouched(b, job_b.id)


async def test_a_task_for_a_text_is_made_in_that_texts_own_clinic(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a, lead_b = await make_lead(a), await make_lead(b)
    await seed_text(a, lead_a, n=1)
    await seed_text(b, lead_b, n=1)  # the very same provider sid in two clinics
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    await engine.run_due(a)
    await engine.run_due(b)
    (task_a,), (task_b,) = await tasks_of(a), await tasks_of(b)
    assert task_a.conversation_id == lead_a.conversation and task_b.conversation_id == lead_b.conversation
    assert {r.to for r in provider.requests} == {"+14155550142"} and len(provider.requests) == 2


# --- which jobs the engine takes ----------------


async def test_only_the_kinds_with_a_handler_are_claimed(make_tenant):
    tenant = await make_tenant()
    ids = {kind: await add_job(tenant, kind=kind) for kind in ("holding", "escalate", "help", "follow_up")}
    engine, provider, clock = make_engine()
    clock.advance(minutes=1)
    assert await engine.run_due(tenant) == 0
    for kind, job_id in ids.items():
        assert await untouched(tenant, job_id), kind
    assert provider.requests == []


async def test_the_limit_caps_the_batch(make_tenant):
    tenant = await make_tenant()
    leads = [await make_lead(tenant, phone=f"+1415555{n:04d}") for n in range(1, 6)]
    for n, lead in enumerate(leads, start=1):
        await seed_text(tenant, lead, n=n)
    engine, provider, clock = make_engine()
    clock.advance(seconds=1)
    assert await engine.run_due(tenant, limit=2) == 2
    assert await engine.run_due(tenant, limit=10) == 3
    assert len(provider.requests) == 5 and len(await all_jobs(tenant)) == 5 + 10  # 5 acks, 5 holding, 5 escalate


async def test_a_job_that_is_not_due_yet_waits(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    await seed_text(tenant, lead, run_at=clock() + timedelta(minutes=5))
    assert await engine.run_due(tenant) == 0
    clock.advance(minutes=5)
    assert await engine.run_due(tenant) == 1 and len(provider.requests) == 1
