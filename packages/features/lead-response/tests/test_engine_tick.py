"""The tick: the gates, the sweep, the due jobs, and the proofs that two ticks never run a job twice."""

import asyncio
import logging
import uuid
from datetime import timedelta

from lr_engine import jobs_of_kind, seed_text, tasks_of
from lr_gateway import FakeProvider, failure, make_lead
from lr_host import another_worker, make_host
from lr_intake import LEAD_NUMBER, Counter, Intake, sid, twilio_pairs
from lr_wait import holdings, staff_reply
from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_db.models.lead_response import MessageEvent
from clinic_lead_response.engine import sweep
from clinic_lead_response.engine.tick import (
    BATCH,
    MAX_JOBS_PER_TICK,
    TICK_EVERY_SECONDS,
    TICK_JOB,
    EngineScheduler,
    TickReport,
)
from clinic_lead_response.gateway.retry import ErrorKind


async def lead_with_text(tenant, n=1, phone=None):
    lead = await make_lead(tenant, phone=phone or f"+1415555{n:04d}")
    await seed_text(tenant, lead, n=n)
    return lead


def test_the_numbers_the_worker_will_use():
    assert (TICK_JOB, TICK_EVERY_SECONDS, BATCH, MAX_JOBS_PER_TICK) == ("tick", 60, 10, 100)


# --- what one tick does ----------------


async def test_a_tick_runs_the_clinics_due_jobs(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant)
    report = await host.scheduler.tick(tenant)
    assert report == TickReport(ran=True, stuck_expired=0, jobs_run=1)
    assert len(host.provider.requests) == 1 and len(await tasks_of(tenant)) == 1


async def test_the_timers_fire_on_later_ticks(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant)
    await host.scheduler.tick(tenant)
    (task,) = await tasks_of(tenant)
    host.clock.now = task.received_at + timedelta(minutes=15, seconds=1)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1  # the holding message
    host.clock.now = task.received_at + timedelta(minutes=30, seconds=1)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1  # the escalation
    (task,) = await tasks_of(tenant)
    assert task.holding_sent_at is not None and task.escalation_state == "escalated"


async def test_a_tick_with_nothing_due_runs_nothing(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    assert await host.scheduler.tick(tenant) == TickReport(ran=True, stuck_expired=0, jobs_run=0)


async def test_the_stuck_message_sweep_is_part_of_the_tick(make_tenant):
    host = make_host(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    tenant = await make_tenant()
    await lead_with_text(tenant)
    await host.scheduler.tick(tenant)  # the ack's answer never arrived: the message is left sending
    host.clock.advance(seconds=121)
    report = await host.scheduler.tick(tenant)
    assert report.stuck_expired == 1
    async with tenant_session(tenant) as session:
        statuses = set(await session.scalars(select(MessageEvent.status)))
    assert "failed" in statuses and len(host.provider.requests) == 1  # settled, and never resent


async def test_a_tick_sweeps_before_it_runs_the_jobs(make_tenant, monkeypatch):
    order = []
    host = make_host()
    real_sweep, real_run = sweep.expire_stuck, host.engine.run_due

    async def sweeping(*args, **kwargs):
        order.append("sweep")
        return await real_sweep(*args, **kwargs)

    async def running(*args, **kwargs):
        order.append("run")
        return await real_run(*args, **kwargs)

    monkeypatch.setattr(sweep, "expire_stuck", sweeping)
    monkeypatch.setattr(host.engine, "run_due", running)
    tenant = await make_tenant()
    await host.scheduler.tick(tenant)
    assert order == ["sweep", "run"]


async def test_a_tick_takes_up_to_the_cap_in_batches_and_leaves_the_rest_for_the_next(make_tenant):
    host = make_host(max_jobs=20, batch=10)
    tenant = await make_tenant()
    for n in range(1, 26):
        await lead_with_text(tenant, n=n)
    assert (await host.scheduler.tick(tenant)).jobs_run == 20
    assert len([j for j in await jobs_of_kind(tenant, "ack") if j.status == "pending"]) == 5
    assert (await host.scheduler.tick(tenant)).jobs_run >= 5
    assert {j.status for j in await jobs_of_kind(tenant, "ack")} == {"done"}


async def test_one_failing_job_does_not_stop_the_others(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant, n=1)
    await lead_with_text(tenant, n=2)
    real = host.engine.handlers["ack"]
    calls = []

    async def poison_the_first(engine, job):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("one bad job")
        return await real(engine, job)

    host.engine.handlers["ack"] = poison_the_first
    assert (await host.scheduler.tick(tenant)).jobs_run == 2
    statuses = sorted(j.status for j in await jobs_of_kind(tenant, "ack"))
    assert statuses == ["done", "pending"] and len(host.provider.requests) == 1


async def test_the_report_counts_what_happened(make_tenant):
    host = make_host(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    tenant = await make_tenant()
    await lead_with_text(tenant, n=1)
    await host.scheduler.tick(tenant)
    host.clock.advance(seconds=121)
    await lead_with_text(tenant, n=2)
    report = await host.scheduler.tick(tenant)
    assert (report.ran, report.stuck_expired) == (True, 1) and report.jobs_run >= 1


# --- the gates ----------------


async def test_with_the_switch_off_the_tick_does_nothing_at_all_not_one_statement(make_tenant):
    host = make_host(enabled=False)
    tenant = await make_tenant()
    await lead_with_text(tenant)
    host.clock.advance(hours=2)
    with Counter() as statements:
        report = await host.scheduler.tick(tenant)
    assert statements == [] and report == TickReport()
    (job,) = await jobs_of_kind(tenant, "ack")
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)


async def test_a_clinic_without_the_feature_costs_the_feature_check_and_nothing_else(make_tenant):
    host = make_host()
    tenant = await make_tenant(())
    await lead_with_text(tenant)
    host.clock.advance(hours=2)
    with Counter() as statements:
        report = await host.scheduler.tick(tenant)
    assert len(statements) == 2 and report == TickReport()  # set_config and the feature read; no claim, no sweep
    assert host.provider.requests == [] and await tasks_of(tenant) == []
    assert (await jobs_of_kind(tenant, "ack"))[0].status == "pending"


async def test_a_feature_that_was_switched_off_stops_the_tick_for_that_clinic(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant, n=1)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    await lead_with_text(tenant, n=2)
    host.clock.advance(hours=1)
    assert (await host.scheduler.tick(tenant)).ran is False and len(host.provider.requests) == 1


async def test_the_gates_are_asked_once_per_tick_not_once_per_step(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    with Counter() as statements:
        await host.scheduler.tick(tenant)
    asked = [s for s in statements if "core.tenant_features" in s]
    print(f"\nidle tick: {len(statements)} statements")
    assert len(asked) == 1 and len(statements) <= IDLE_TICK


# set_config and the feature read (the gates), the stuck-message read (2), and an empty claim (4)
IDLE_TICK = 8


async def test_ticking_one_clinic_leaves_the_others_alone(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    host = make_host()
    await lead_with_text(a)
    await lead_with_text(b)
    host.clock.advance(seconds=1)
    await host.scheduler.tick(a)
    assert len(await tasks_of(a)) == 1 and await tasks_of(b) == []
    assert (await jobs_of_kind(b, "ack"))[0].status == "pending"


# --- two ticks at once ----------------


async def test_two_ticks_at_once_run_each_job_once(make_tenant):
    host = make_host()
    other = another_worker(host)
    tenant = await make_tenant()
    for n in range(1, 7):
        await lead_with_text(tenant, n=n)
    first, second = await asyncio.gather(host.scheduler.tick(tenant), other.scheduler.tick(tenant))
    assert first.jobs_run + second.jobs_run >= 6
    assert len(host.provider.requests) == 6  # one ack per lead, none twice
    jobs = await jobs_of_kind(tenant, "ack")
    assert {j.status for j in jobs} == {"done"} and {j.attempts for j in jobs} == {1}


async def test_five_ticks_at_once_still_send_one_ack_per_lead(make_tenant):
    host = make_host()
    workers = [host] + [another_worker(host) for _ in range(4)]
    tenant = await make_tenant()
    for n in range(1, 5):
        await lead_with_text(tenant, n=n)
    await asyncio.gather(*[w.scheduler.tick(tenant) for w in workers])
    assert len(host.provider.requests) == 4
    assert sorted(r.to for r in host.provider.requests) == sorted({r.to for r in host.provider.requests})


async def test_two_ticks_at_once_escalate_a_task_once(make_tenant):
    host = make_host()
    other = another_worker(host)
    tenant = await make_tenant()
    await lead_with_text(tenant)
    await host.scheduler.tick(tenant)
    (task,) = await tasks_of(tenant)
    host.clock.now = task.received_at + timedelta(minutes=31)
    await asyncio.gather(host.scheduler.tick(tenant), other.scheduler.tick(tenant))
    (task,) = await tasks_of(tenant)
    assert task.escalation_state == "escalated" and len(holdings(host.provider)) == 1


async def test_a_tick_and_the_fast_path_do_not_both_run_the_same_job(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    response = await intake.post(tenant, twilio_pairs(MessageSid=sid(1)))
    assert response.status_code == 200
    await asyncio.gather(host.fast.drain(), host.scheduler.tick(tenant))
    assert len(host.provider.requests) == 1
    assert {j.status for j in await jobs_of_kind(tenant, "ack")} == {"done"}


# --- recovery ----------------


async def test_a_job_whose_worker_died_is_run_by_a_later_tick(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant)
    claimed = await host.engine.queue.claim(tenant, kinds=["ack"])  # a worker took it and died
    assert len(claimed) == 1 and host.provider.requests == []
    assert (await host.scheduler.tick(tenant)).jobs_run == 0  # still inside its lease
    host.clock.advance(seconds=121)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1 and len(host.provider.requests) == 1


async def test_a_tick_is_safe_to_repeat(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await lead_with_text(tenant)
    await host.scheduler.tick(tenant)
    again = await host.scheduler.tick(tenant)
    assert again.jobs_run == 0 and len(host.provider.requests) == 1


async def test_a_staff_reply_before_the_timer_stops_the_timers_on_the_next_tick(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    lead = await lead_with_text(tenant)
    await host.scheduler.tick(tenant)
    (task,) = await tasks_of(tenant)
    await staff_reply(tenant, lead, task.received_at + timedelta(minutes=2))
    host.clock.now = task.received_at + timedelta(minutes=31)
    await host.scheduler.tick(tenant)
    assert holdings(host.provider) == [] and (await tasks_of(tenant))[0].escalation_state == "none"


# --- logs and privacy ----------------


async def test_a_tick_that_did_work_logs_ids_and_nothing_personal_and_an_idle_one_logs_nothing(make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    host = make_host()
    tenant = await make_tenant()
    await host.scheduler.tick(tenant)
    assert not [r for r in caplog.records if r.getMessage().startswith("tick ")]
    await lead_with_text(tenant)
    await host.scheduler.tick(tenant)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("tick ")]
    assert f"tenant_id={tenant}" in line and "trace_id=" in line and "outcome=worked" in line
    assert LEAD_NUMBER not in line and LEAD_NUMBER[1:] not in line


async def test_the_scheduler_is_an_interface_anything_with_a_tick_can_fill(make_tenant):
    class Other:
        async def tick(self, tenant_id: uuid.UUID) -> TickReport:
            return TickReport(ran=True)

    assert (await Other().tick(uuid.uuid4())).ran is True
    assert hasattr(EngineScheduler, "tick")
