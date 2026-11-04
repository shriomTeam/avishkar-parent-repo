"""The holding message: once per wait, at the clinic's timer, read when it fires."""

from datetime import timedelta

import pytest
from lr_engine import add_outbound, around, jobs_of_kind, make_engine, messages_of, seed_text, tasks_of
from lr_gateway import FakeProvider, accepted, events, failure, make_lead, set_settings
from lr_wait import go_to, holdings, open_wait, set_task, timer
from sqlalchemy import update

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_db.models.lead_response import Job
from clinic_lead_response.engine import holding
from clinic_lead_response.engine.holding import DAILY_HOLDING_CAP, HOLDING_TEXT_PLACEHOLDER
from clinic_lead_response.engine.queue import LEASE_SECONDS, PostgresJobQueue
from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.status import current_status

SID = "SM" + "1" * 32


async def holding_messages(tenant):
    return [m for m in await messages_of(tenant) if m.sender_kind == "holding"]


# --- when it is sent ----------------


async def test_the_holding_message_goes_out_when_the_timer_is_up_and_not_before(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15, seconds=-1)  # a second before the default 15 minutes
    assert await wait.engine.run_due(tenant) == 0 and holdings(wait.provider) == []
    go_to(wait, 15)
    assert await wait.engine.run_due(tenant) == 1
    assert len(holdings(wait.provider)) == 1


async def test_the_wording_is_the_placeholder_and_it_goes_to_the_lead_from_our_number(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    (sent,) = holdings(wait.provider)
    assert HOLDING_TEXT_PLACEHOLDER == "Thank you for your patience. Our team has your message."
    assert (sent.to, sent.from_number, sent.body) == ("+14155550142", "+14155550100", HOLDING_TEXT_PLACEHOLDER)


async def test_the_message_is_recorded_and_the_task_and_job_say_so(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    (message,) = await holding_messages(tenant)
    (task,) = await tasks_of(tenant)
    job = await timer(tenant, "holding")
    assert message.idempotency_key == f"holding:{task.id}" and message.conversation_id == lead.conversation
    assert message.direction == "outbound" and message.trace_id == task.trace_id
    assert current_status((e.attempt, e.status) for e in await events(tenant, message.id)).value == "sent"
    assert task.holding_sent_at is not None and task.status == "open"
    assert (job.status, job.last_error_code, job.locked_at) == ("done", None, None)


async def test_the_clinics_timer_sets_the_time(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, holding_minutes=20, sla_minutes=45)
    wait = await open_wait(tenant, lead)
    go_to(wait, 19)
    assert await wait.engine.run_due(tenant) == 0
    go_to(wait, 20)
    assert await wait.engine.run_due(tenant) == 1 and len(holdings(wait.provider)) == 1


async def test_it_still_goes_out_when_the_ack_failed_for_good(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead, provider=FakeProvider(failure(ErrorKind.INVALID_NUMBER, "21211")))
    assert (await tasks_of(tenant))[0].first_ack_at is None  # the ack never went out
    wait.provider.script = [accepted(SID)]  # but the number works for a later message
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


# --- the timer is read when the job fires ----------------


async def test_a_lengthened_timer_puts_the_job_back_without_counting_it(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)  # made with the default 15 minutes
    await set_settings(tenant, holding_minutes=40, sla_minutes=60)  # the clinic changes its mind afterwards
    go_to(wait, 15)
    assert await wait.engine.run_due(tenant) == 1  # the job fired...
    assert holdings(wait.provider) == []  # ...and sent nothing
    job = await timer(tenant, "holding")
    assert (job.status, job.attempts) == ("pending", 0)
    assert job.run_at == wait.task.received_at + timedelta(minutes=40)
    go_to(wait, 39)
    assert await wait.engine.run_due(tenant) == 0
    go_to(wait, 40)
    assert await wait.engine.run_due(tenant) == 1 and len(holdings(wait.provider)) == 1


async def test_a_shortened_timer_reaches_only_waits_that_begin_afterwards(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await set_settings(tenant, holding_minutes=5, sla_minutes=30)
    go_to(wait, 6)
    assert await wait.engine.run_due(tenant) == 0  # this wait was timed at 15 minutes when it began
    go_to(wait, 15)
    assert await wait.engine.run_due(tenant) == 1 and len(holdings(wait.provider)) == 1


async def test_the_timer_is_not_saved_with_the_job_so_a_new_setting_is_always_seen(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    job = await timer(tenant, "holding")
    assert job.payload == {"task_id": str(wait.task.id)}  # no minutes, no wording
    await set_settings(tenant, holding_minutes=25, sla_minutes=50)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "holding")).run_at == wait.task.received_at + timedelta(minutes=25)


# --- a second text during the wait ----------------


async def test_a_second_text_does_not_restart_or_extend_the_timer(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    before = await timer(tenant, "holding")
    go_to(wait, 10)
    await seed_text(tenant, lead, n=2, created_at=wait.clock(), run_at=wait.clock())
    wait.clock.advance(seconds=1)
    await wait.engine.run_due(tenant)  # the second text's ack job runs: "already acked"
    after = await timer(tenant, "holding")
    assert (after.run_at, after.status, after.attempts) == (before.run_at, "pending", 0)
    assert len(await jobs_of_kind(tenant, "holding")) == 1
    go_to(wait, 15)  # 15 minutes after the FIRST text, only 5 after the second
    assert await wait.engine.run_due(tenant) == 1 and len(holdings(wait.provider)) == 1


async def test_it_is_still_one_holding_message_however_many_texts_the_lead_sends(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    for n in range(2, 7):
        go_to(wait, n)
        await seed_text(tenant, lead, n=n, created_at=wait.clock(), run_at=wait.clock())
        wait.clock.advance(seconds=1)
        await wait.engine.run_due(tenant)
    go_to(wait, 16)
    await wait.engine.run_due(tenant)
    go_to(wait, 45)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1 and len(await holding_messages(tenant)) == 1


# --- once per wait ----------------


async def test_running_the_holding_job_again_sends_nothing_more(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    async with tenant_session(tenant) as session:  # as if the job were run again
        await session.execute(update(Job).where(Job.kind == "holding").values(status="pending", run_at=wait.clock()))
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1
    assert (await timer(tenant, "holding")).last_error_code == "already_sent"


async def test_a_second_holding_job_for_the_same_wait_sends_nothing(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="holding",
                run_at=wait.task.received_at,
                idempotency_key="holding:an-extra-one",
                task_id=wait.task.id,
                payload={"task_id": str(wait.task.id)},
            )
        )
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_a_new_wait_after_the_old_one_is_handled_gets_its_own_holding_message(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    await set_task(tenant, status="handled", handled_at=wait.clock())
    wait.clock.advance(hours=3)
    await seed_text(tenant, lead, n=2, created_at=wait.clock(), run_at=wait.clock())
    wait.clock.advance(seconds=1)
    await wait.engine.run_due(tenant)
    second = (await tasks_of(tenant))[1]
    wait.clock.now = second.received_at + timedelta(minutes=15, seconds=1)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 2 and len(await holding_messages(tenant)) == 2


# --- quiet hours and consent ----------------


async def test_quiet_hours_do_not_hold_it_back(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, timezone="UTC")
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await set_settings(tenant, holding_minutes=15, sla_minutes=30, quiet_hours=around(wait.clock))
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_a_lead_with_no_consent_record_still_gets_it(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)  # a reply to their own text needs no grant
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


# --- the cap ----------------


def test_the_cap_is_two_holding_messages_a_day():
    assert DAILY_HOLDING_CAP == 2


async def test_two_holding_messages_today_means_no_third(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    for hours in (2, 3):
        await add_outbound(tenant, lead, sender_kind="holding", created_at=wait.clock() - timedelta(hours=hours))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert (await timer(tenant, "holding")).last_error_code == "capped"
    assert len(await tasks_of(tenant)) == 1 and (await tasks_of(tenant))[0].status == "open"


async def test_one_earlier_holding_message_leaves_room(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await add_outbound(tenant, lead, sender_kind="holding", created_at=wait.clock() - timedelta(hours=2))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_holding_messages_older_than_a_day_do_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    for hours in (25, 30, 50):
        await add_outbound(tenant, lead, sender_kind="holding", created_at=wait.clock() - timedelta(hours=hours))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_only_holding_messages_count_towards_the_holding_cap(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    for kind in ("ack", "help", "staff", "followup"):
        await add_outbound(tenant, lead, sender_kind=kind, created_at=wait.clock() - timedelta(hours=3))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


# --- what each answer from the gateway means ----------------


async def test_retry_puts_the_job_back_and_the_next_run_resumes_the_same_message(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(SID), failure(ErrorKind.RETRYABLE, "30003"), accepted(SID))
    wait = await open_wait(tenant, lead, provider=provider)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    job = await timer(tenant, "holding")
    assert (job.status, job.attempts) == ("pending", 0) and job.run_at == wait.clock() + timedelta(seconds=3)
    wait.clock.advance(seconds=3)
    assert await wait.engine.run_due(tenant) == 1
    assert len(holdings(provider)) == 2  # the same message, tried twice
    assert len(await holding_messages(tenant)) == 1
    assert (await timer(tenant, "holding")).status == "done" and (await tasks_of(tenant))[0].holding_sent_at


async def test_a_permanent_failure_ends_the_job_and_leaves_the_task_open(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(SID), failure(ErrorKind.INVALID_NUMBER, "21211"))
    wait = await open_wait(tenant, lead, provider=provider)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    job = await timer(tenant, "holding")
    assert (job.status, job.last_error_code) == ("done", "failed_invalid_number")
    task = (await tasks_of(tenant))[0]
    assert task.holding_sent_at is None and task.status == "open"


async def test_a_contact_with_no_phone_number_is_blocked(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=None)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert (await timer(tenant, "holding")).last_error_code == "blocked_no_phone"


async def test_an_uncertain_send_is_never_resent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(SID), failure(ErrorKind.AMBIGUOUS, "timeout"))
    wait = await open_wait(tenant, lead, provider=provider)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(provider)) == 1
    assert (await timer(tenant, "holding")).last_error_code == "uncertain"
    (message,) = await holding_messages(tenant)
    assert [e.status for e in await events(tenant, message.id)] == ["sending"]
    go_to(wait, 60)
    await wait.engine.run_due(tenant)
    assert len(holdings(provider)) == 1


async def test_a_crash_after_the_send_but_before_the_job_is_marked_done_sends_nothing_twice(make_tenant):
    class Dies(PostgresJobQueue):
        armed = False

        async def complete(self, job, *, code=None):
            if self.armed and job.kind == "holding":
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
    (task,) = await tasks_of(tenant)
    clock.now = task.received_at + timedelta(minutes=15, seconds=1)
    queue.armed = True
    with pytest.raises(SystemError):
        await engine.run_due(tenant)
    assert len(holdings(provider)) == 1
    clock.advance(seconds=LEASE_SECONDS)
    await engine.run_due(tenant)
    assert len(holdings(provider)) == 1 and len(await holding_messages(tenant)) == 1
    assert (await timer(tenant, "holding")).last_error_code == "already_sent"


async def test_a_crash_after_the_send_but_before_the_task_is_stamped_is_caught_by_the_gateways_key(
    make_tenant, monkeypatch
):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    real = holding.mark_holding_sent
    calls = []

    async def dies_once(session, task_id, when):
        calls.append(1)
        if len(calls) == 1:
            raise SystemError("the process was killed")
        return await real(session, task_id, when)

    monkeypatch.setattr(holding, "mark_holding_sent", dies_once)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)  # the handler raises after the send: a failed attempt
    assert len(holdings(wait.provider)) == 1 and (await tasks_of(tenant))[0].holding_sent_at is None
    wait.clock.advance(seconds=31)  # past the first backoff
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1 and len(await holding_messages(tenant)) == 1
    job = await timer(tenant, "holding")
    assert (job.status, job.last_error_code) == ("done", "duplicate")
    assert (await tasks_of(tenant))[0].holding_sent_at is not None


# --- the gates ----------------


async def test_with_the_switch_off_the_holding_job_waits_untouched(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    state = {"on": False}
    wait.engine._enabled = lambda: state["on"]
    go_to(wait, 30)
    assert await wait.engine.run_due(tenant) == 0 and holdings(wait.provider) == []
    job = await timer(tenant, "holding")
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)
    state["on"] = True
    assert await wait.engine.run_due(tenant) == 1 and len(holdings(wait.provider)) == 1  # nothing was lost


async def test_a_clinic_without_the_feature_gets_no_holding_message(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    go_to(wait, 30)
    assert await wait.engine.run_due(tenant) == 0 and holdings(wait.provider) == []
