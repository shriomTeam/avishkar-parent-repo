"""The escalation: the staff target was missed, so the task is flagged for a manager. Nobody is messaged."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from lr_engine import around, jobs_of_kind, make_engine, messages_of, seed_text, tasks_of
from lr_gateway import Clock, FakeProvider, accepted, audit_rows, failure, make_lead, set_settings
from lr_intake import Counter
from lr_wait import go_to, holdings, open_wait, opt_in, opt_out, set_task, staff_reply, timer
from sqlalchemy import select, update

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_db.models.lead_response import Job
from clinic_db.models.ops import AuditLog, OutboxEvent
from clinic_lead_response.engine import escalation
from clinic_lead_response.engine.queue import LEASE_SECONDS, PostgresJobQueue
from clinic_lead_response.gateway.retry import ErrorKind

ACTION = "lead_response.task.escalated"


async def after_the_holding_message(tenant, lead, **kw):
    """A wait whose holding message has already gone out, so the next run is about the escalation alone."""
    wait = await open_wait(tenant, lead, **kw)
    go_to(wait, 16)
    await wait.engine.run_due(tenant)
    return wait


async def states(tenant):
    return {
        j.kind: (j.status, j.cancel_reason)
        for j in await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    }


async def the_task(tenant):
    (task,) = await tasks_of(tenant)
    return task


# --- when it fires ----------------


async def test_the_task_is_flagged_when_the_target_is_up_and_not_before(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30, seconds=-1)
    assert await wait.engine.run_due(tenant) == 0
    assert (await the_task(tenant)).escalation_state == "none"
    go_to(wait, 30)
    assert await wait.engine.run_due(tenant) == 1
    task = await the_task(tenant)
    assert task.escalation_state == "escalated" and task.escalated_at is not None


async def test_the_flag_and_the_time_are_set_and_nothing_else_changes(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    before = await the_task(tenant)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    task = await the_task(tenant)
    assert abs(task.escalated_at - wait.clock()) < timedelta(seconds=1)
    assert (task.status, task.handled_at, task.handled_by_staff_id, task.first_staff_reply_at) == (
        "open",
        None,
        None,
        None,
    )
    assert (task.first_ack_at, task.holding_sent_at, task.received_at, task.priority) == (
        before.first_ack_at,
        before.holding_sent_at,
        before.received_at,
        before.priority,
    )
    job = await timer(tenant, "escalate")
    assert (job.status, job.last_error_code, job.locked_at) == ("done", None, None)


async def test_the_clinics_target_sets_the_time(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, holding_minutes=20, sla_minutes=45)
    wait = await open_wait(tenant, lead)
    go_to(wait, 44)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "none"
    go_to(wait, 45)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_a_lengthened_target_puts_the_job_back_without_counting_it(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))  # made with the default 30 minutes
    await set_settings(tenant, holding_minutes=15, sla_minutes=60)
    go_to(wait, 30)
    assert await wait.engine.run_due(tenant) == 1  # the job fired...
    assert (await the_task(tenant)).escalation_state == "none"  # ...and flagged nothing
    job = await timer(tenant, "escalate")
    assert (job.status, job.attempts) == ("pending", 0)
    assert job.run_at == wait.task.received_at + timedelta(minutes=60)
    assert await audit_rows(tenant, ACTION) == []
    go_to(wait, 59)
    assert await wait.engine.run_due(tenant) == 0
    go_to(wait, 60)
    assert await wait.engine.run_due(tenant) == 1
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_a_shortened_target_reaches_only_waits_that_begin_afterwards(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    await set_settings(tenant, holding_minutes=15, sla_minutes=20)
    go_to(wait, 25)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "none"  # this wait was timed at 30 minutes when it began
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_the_target_is_not_saved_with_the_job(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    assert (await timer(tenant, "escalate")).payload == {"task_id": str(wait.task.id)}


async def test_the_clock_is_wall_time_so_the_hour_of_day_makes_no_difference(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, timezone="UTC")
    wait = await after_the_holding_message(tenant, lead)
    await set_settings(tenant, holding_minutes=15, sla_minutes=30, quiet_hours=around(wait.clock, hours=3))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (
        await the_task(tenant)
    ).escalation_state == "escalated"  # overnight or not, thirty minutes is thirty minutes


async def test_it_still_fires_when_the_ack_failed_and_the_holding_message_never_went(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(failure(ErrorKind.INVALID_NUMBER, "21211"))
    wait = await open_wait(tenant, lead, provider=provider)
    go_to(wait, 31)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"


# --- the role ----------------


async def test_the_audit_row_names_the_role_from_the_settings(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    (row,) = await audit_rows(tenant, ACTION)
    assert row.details["role"] == "office_manager"  # the default


async def test_the_role_is_read_when_the_job_fires(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    await set_settings(
        tenant, holding_minutes=15, sla_minutes=30, escalation_role="owner"
    )  # changed after the wait began
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    (row,) = await audit_rows(tenant, ACTION)
    assert row.details["role"] == "owner"


# --- once per task ----------------


async def test_running_the_job_again_changes_nothing(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    first = await the_task(tenant)
    async with tenant_session(tenant) as session:  # as if the job were run again
        await session.execute(update(Job).where(Job.kind == "escalate").values(status="pending", run_at=wait.clock()))
    wait.clock.advance(minutes=5)
    await wait.engine.run_due(tenant)
    again = await the_task(tenant)
    assert (again.escalation_state, again.escalated_at) == (first.escalation_state, first.escalated_at)
    assert len(await audit_rows(tenant, ACTION)) == 1
    assert (await timer(tenant, "escalate")).last_error_code == "already_escalated"


async def test_a_second_escalation_job_for_the_same_task_flags_nothing_more(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="escalate",
                run_at=wait.task.received_at,
                idempotency_key="escalate:an-extra-one",
                task_id=wait.task.id,
                payload={"task_id": str(wait.task.id)},
            )
        )
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert len(await audit_rows(tenant, ACTION)) == 1
    assert sorted(j.last_error_code or "" for j in await jobs_of_kind(tenant, "escalate")) == ["", "already_escalated"]


async def test_two_workers_at_once_flag_the_task_once(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="escalate",
                run_at=wait.task.received_at,
                idempotency_key="escalate:the-other-worker",
                task_id=wait.task.id,
                payload={"task_id": str(wait.task.id)},
            )
        )
    second, _, _ = make_engine(wait.provider, clock=wait.clock)
    go_to(wait, 30)
    counts = await asyncio.gather(wait.engine.run_due(tenant, limit=1), second.run_due(tenant, limit=1))
    assert sorted(counts) == [1, 1]
    assert len(await audit_rows(tenant, ACTION)) == 1
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_a_task_flagged_by_hand_is_not_flagged_again(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    stamped = wait.task.received_at + timedelta(minutes=10)
    await set_task(tenant, escalation_state="escalated", escalated_at=stamped)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    task = await the_task(tenant)
    assert task.escalated_at == stamped and await audit_rows(tenant, ACTION) == []


# --- when it must not fire ----------------


async def test_a_staff_reply_cancels_it_and_the_flag_stays_off(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    at = wait.task.received_at + timedelta(minutes=20)
    await staff_reply(tenant, lead, at)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    task = await the_task(tenant)
    assert task.escalation_state == "none" and task.escalated_at is None and task.status == "open"
    assert task.first_staff_reply_at == at  # reconciled
    assert (await timer(tenant, "escalate")).cancel_reason == "staff_reply" and await audit_rows(tenant, ACTION) == []


async def test_a_handled_task_is_not_escalated(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    await set_task(tenant, status="handled", handled_at=wait.clock())
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "handled"
    assert (await the_task(tenant)).escalation_state == "none" and await audit_rows(tenant, ACTION) == []


async def test_a_task_closed_in_another_way_is_not_escalated(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    await set_task(tenant, status="cancelled")
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "task_closed"


async def test_a_stop_cancels_it_but_the_task_stays_open(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    task = await the_task(tenant)
    assert (task.status, task.escalation_state, task.handled_at) == ("open", "none", None)
    assert (await timer(tenant, "escalate")).cancel_reason == "stop" and await audit_rows(tenant, ACTION) == []


async def test_a_contact_who_opted_out_before_the_text_is_not_escalated(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    wait = await open_wait(tenant, lead)
    go_to(wait, 31)
    await wait.engine.run_due(tenant)
    assert (await states(tenant))["escalate"] == ("cancelled", "stop") and (await the_task(tenant)).status == "open"


async def test_start_after_stop_lets_the_escalation_happen(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await opt_out(tenant, lead)
    await opt_in(tenant, lead)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_the_order_of_the_rules_is_handled_then_reply_then_stop(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    await opt_out(tenant, lead)
    await set_task(tenant, status="handled", handled_at=wait.clock())
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "handled"


async def test_a_staff_reply_wins_over_a_stop(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await opt_out(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "staff_reply"


async def test_a_reply_from_before_the_wait_or_not_from_staff_does_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at - timedelta(days=2))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (
        await the_task(tenant)
    ).escalation_state == "escalated"  # the ack and the holding message are ours, not staff


async def test_a_reply_in_another_conversation_does_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone="+14155550142")
    other = await make_lead(tenant, phone="+14155550177")
    wait = await after_the_holding_message(tenant, lead)
    await staff_reply(tenant, other, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_a_staff_reply_cancels_the_job_even_when_the_target_was_lengthened(make_tenant):
    """The wait is over, so the job is cancelled now, not put back for later."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    await set_settings(tenant, holding_minutes=15, sla_minutes=90)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=20))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    job = await timer(tenant, "escalate")
    assert (job.status, job.cancel_reason) == ("cancelled", "staff_reply")


async def test_cancelling_the_escalation_also_cancels_a_holding_message_still_waiting(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)  # the holding message has NOT gone out
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 31)
    await wait.engine.run_due(tenant)
    assert await states(tenant) == {"holding": ("cancelled", "staff_reply"), "escalate": ("cancelled", "staff_reply")}
    assert holdings(wait.provider) == []


async def test_a_job_for_a_task_that_does_not_exist_is_cancelled(make_tenant):
    tenant = await make_tenant()
    engine, provider, clock = make_engine()
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="escalate",
                run_at=clock(),
                idempotency_key="escalate:x",
                payload={"task_id": str(uuid.uuid4())},
            )
        )
    await engine.run_due(tenant)
    job = await timer(tenant, "escalate")
    assert (job.status, job.cancel_reason) == ("cancelled", "task_missing") and await audit_rows(tenant, ACTION) == []


async def test_a_job_with_a_broken_payload_is_cancelled(make_tenant):
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="escalate",
                run_at=clock(),
                idempotency_key="escalate:y",
                payload={"task_id": "nope"},
            )
        )
    await engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "bad_payload"


# --- the second look, in the transaction that writes ----------------


def between_the_two_looks(monkeypatch, before):
    """Run ``before`` after the decision and before the second look, as a change landing in between would."""
    real = escalation._escalate

    async def escalate(engine, job, task_id, trace_id):
        await before()
        return await real(engine, job, task_id, trace_id)

    monkeypatch.setattr(escalation, "_escalate", escalate)


async def test_a_staff_reply_between_the_decision_and_the_write_is_caught(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)

    async def reply():
        await staff_reply(tenant, lead, wait.clock() - timedelta(seconds=0.2))

    between_the_two_looks(monkeypatch, reply)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "none" and await audit_rows(tenant, ACTION) == []
    assert (await timer(tenant, "escalate")).cancel_reason == "staff_reply"


async def test_a_task_handled_between_the_decision_and_the_write_is_caught(make_tenant, monkeypatch):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))

    async def handle():
        await set_task(tenant, status="handled", handled_at=wait.clock())

    between_the_two_looks(monkeypatch, handle)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "handled" and await audit_rows(tenant, ACTION) == []


async def test_a_stop_between_the_decision_and_the_write_is_caught(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)

    async def stop():
        await opt_out(tenant, lead)

    between_the_two_looks(monkeypatch, stop)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).cancel_reason == "stop" and (await the_task(tenant)).status == "open"


async def test_the_second_look_holds_a_lock_on_the_task_row(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30)
    with Counter() as statements:
        await wait.engine.run_due(tenant)
    locked = [s for s in statements if "FROM lead_response.tasks" in s and "FOR UPDATE" in s]
    assert len(locked) == 1


async def test_a_reply_landing_after_the_second_look_cannot_stop_the_flag(make_tenant, monkeypatch):
    """The residual window, written down: the second look is done, the write is about to commit."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await after_the_holding_message(tenant, lead)
    real_audit = escalation.audit

    async def audit_after_a_reply(*args, **kwargs):
        await staff_reply(tenant, lead, wait.clock())
        return await real_audit(*args, **kwargs)

    monkeypatch.setattr(escalation, "audit", audit_after_a_reply)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated" and len(await audit_rows(tenant, ACTION)) == 1


async def test_the_flag_and_the_audit_row_are_written_together_or_not_at_all(make_tenant, monkeypatch):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    real = escalation.audit
    calls = []

    async def dies_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise SystemError("the process was killed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(escalation, "audit", dies_once)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    task = await the_task(tenant)
    assert (task.escalation_state, task.escalated_at) == ("none", None) and await audit_rows(tenant, ACTION) == []
    job = await timer(tenant, "escalate")
    assert (job.status, job.attempts) == ("pending", 1)
    wait.clock.advance(seconds=31)  # past the first backoff
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated" and len(await audit_rows(tenant, ACTION)) == 1


async def test_a_crash_after_the_flag_but_before_the_job_is_marked_done_flags_nothing_twice(make_tenant):
    class Dies(PostgresJobQueue):
        armed = False

        async def complete(self, job, *, code=None):
            if self.armed and job.kind == "escalate":
                self.armed = False
                raise SystemError("the process was killed")
            return await super().complete(job, code=code)

    tenant = await make_tenant()
    lead = await make_lead(tenant)
    clock = make_engine()[2]
    queue = Dies(clock=clock)
    engine, provider, _ = make_engine(clock=clock, queue=queue)
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    task = await the_task(tenant)
    clock.now = task.received_at + timedelta(minutes=16)
    await engine.run_due(tenant)
    clock.now = task.received_at + timedelta(minutes=30, seconds=1)
    queue.armed = True
    with pytest.raises(SystemError):
        await engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"
    clock.advance(seconds=LEASE_SECONDS)
    await engine.run_due(tenant)
    assert len(await audit_rows(tenant, ACTION)) == 1
    assert (await timer(tenant, "escalate")).last_error_code == "already_escalated"


# --- what it must not do ----------------


async def test_escalating_calls_the_provider_not_even_once(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    before = len(wait.provider.requests)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"
    assert len(wait.provider.requests) == before


async def test_escalating_makes_no_message_of_any_kind(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    before = len(await messages_of(tenant))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert len(await messages_of(tenant)) == before


async def test_escalating_emits_no_platform_event(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(OutboxEvent.id).limit(1)) is None


async def test_the_escalation_is_the_only_audit_row_and_the_task_stays_open(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    async with tenant_session(tenant) as session:
        actions = list(await session.scalars(select(AuditLog.action)))
    assert actions == [ACTION]
    assert (await the_task(tenant)).status == "open"


# --- the gates and other clinics ----------------


async def test_with_the_switch_off_nothing_is_flagged_and_nothing_is_lost(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    state = {"on": False}
    wait.engine._enabled = lambda: state["on"]
    go_to(wait, 40)
    assert await wait.engine.run_due(tenant) == 0
    assert (await the_task(tenant)).escalation_state == "none" and await audit_rows(tenant, ACTION) == []
    job = await timer(tenant, "escalate")
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)
    state["on"] = True
    assert await wait.engine.run_due(tenant) == 1
    assert (await the_task(tenant)).escalation_state == "escalated"


async def test_a_clinic_without_the_feature_is_not_escalated(make_tenant):
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    go_to(wait, 40)
    assert await wait.engine.run_due(tenant) == 0
    assert (await the_task(tenant)).escalation_state == "none"


async def test_escalating_one_clinic_leaves_the_others_alone(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    wait_a = await after_the_holding_message(a, await make_lead(a))
    wait_b = await after_the_holding_message(b, await make_lead(b))
    go_to(wait_a, 30)
    assert await wait_a.engine.run_due(a) == 1
    assert (await the_task(a)).escalation_state == "escalated" and len(await audit_rows(a, ACTION)) == 1
    assert (await the_task(b)).escalation_state == "none" and await audit_rows(b, ACTION) == []
    assert (await timer(b, "escalate")).status == "pending"
    go_to(wait_b, 30)
    await wait_b.engine.run_due(b)
    assert len(await audit_rows(b, ACTION)) == 1 and len(await audit_rows(a, ACTION)) == 1


async def test_the_engine_has_a_handler_for_escalation(make_tenant):
    engine, _, _ = make_engine()
    assert "escalate" in engine.handlers


async def test_a_wait_that_ends_in_an_ack_that_went_out_is_escalated_all_the_same(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead, provider=FakeProvider(accepted("SM" + "1" * 32)))
    assert (await the_task(tenant)).first_ack_at is not None
    go_to(wait, 31)
    await wait.engine.run_due(tenant)
    assert (await the_task(tenant)).escalation_state == "escalated"  # an ack is not an answer from a person


async def test_two_workers_that_both_decided_to_escalate_flag_the_task_once(make_tenant, monkeypatch):
    """The race forced: both workers pass the decision while the task is not yet flagged. One of them is held back until
    the other has written; it must then find the task already flagged, leave its time alone and write no audit row. The
    two workers use clocks five minutes apart, so a time overwritten by the second would show."""
    tenant = await make_tenant()
    wait = await after_the_holding_message(tenant, await make_lead(tenant))
    other_key = "escalate:the-held-back-worker"
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="escalate",
                run_at=wait.task.received_at,
                idempotency_key=other_key,
                task_id=wait.task.id,
                payload={"task_id": str(wait.task.id)},
            )
        )
    written = asyncio.Event()
    first_time = {}
    real = escalation._escalate

    async def escalate(engine, job, task_id, trace_id):
        if job.idempotency_key == other_key:
            await written.wait()  # decided, and now waiting for the other worker to write first
        result = await real(engine, job, task_id, trace_id)
        if job.idempotency_key != other_key:
            first_time["at"] = (await the_task(tenant)).escalated_at
            written.set()
        return result

    monkeypatch.setattr(escalation, "_escalate", escalate)
    go_to(wait, 30)
    later = Clock(wait.clock() + timedelta(minutes=5))
    second, _, _ = make_engine(wait.provider, clock=later)
    results = await asyncio.gather(wait.engine.run_due(tenant, limit=1), second.run_due(tenant, limit=1))
    assert sorted(results) == [1, 1]
    task = await the_task(tenant)
    assert task.escalation_state == "escalated" and task.escalated_at == first_time["at"]
    assert len(await audit_rows(tenant, ACTION)) == 1
    codes = sorted(j.last_error_code or "" for j in await jobs_of_kind(tenant, "escalate"))
    assert codes == ["", "already_escalated"]


async def test_a_job_with_no_task_in_its_payload_at_all_is_cancelled(make_tenant):
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    async with tenant_session(tenant) as session:
        session.add(Job(tenant_id=tenant, kind="escalate", run_at=clock(), idempotency_key="escalate:z", payload={}))
    await engine.run_due(tenant)
    job = await timer(tenant, "escalate")
    assert (job.status, job.cancel_reason, job.attempts) == ("cancelled", "bad_payload", 1)
