"""The acknowledgement: what is sent, once per wait, and what each answer from the gateway means for the job."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from lr_engine import around, jobs_of_kind, make_engine, messages_of, seed_text, tasks_of
from lr_gateway import FakeProvider, accepted, consents, events, failure, make_lead, set_settings
from lr_intake import LEAD_NUMBER, OUR_NUMBER
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import DEFAULT_ACK_TEXT, Task
from clinic_lead_response.engine import ack
from clinic_lead_response.engine.ack import _end_for
from clinic_lead_response.engine.queue import LEASE_SECONDS, PostgresJobQueue
from clinic_lead_response.engine.results import Done, Wait
from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.types import MessageStatus, Outcome, SendResult

CUSTOM = "Hi, this is the Maple clinic. We got your text."


async def sent_acks(tenant):
    return [m for m in await messages_of(tenant) if m.direction == "outbound" and m.sender_kind == "ack"]


async def one_job(tenant, kind="ack"):
    (job,) = await jobs_of_kind(tenant, kind)
    return job


# --- the ack that goes out ----------------


async def test_an_ack_goes_to_the_lead_from_our_number_with_the_default_wording(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    assert await engine.run_due(tenant) == 1
    (sent,) = provider.requests
    assert (sent.to, sent.from_number, sent.body, sent.attempt) == (LEAD_NUMBER, OUR_NUMBER, DEFAULT_ACK_TEXT, 1)


async def test_the_ack_is_recorded_and_the_task_and_job_say_so(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    await engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    (message,) = await sent_acks(tenant)
    job = await one_job(tenant)
    assert message.idempotency_key == f"ack:{task.id}" and message.conversation_id == lead.conversation
    assert {e.status for e in await events(tenant, message.id)} == {"sending", "sent"}
    assert task.first_ack_at is not None and abs(task.first_ack_at - clock()) < timedelta(seconds=1)
    assert (job.status, job.last_error_code, job.locked_at) == ("done", None, None)
    assert provider.requests[0].message_id == message.id


async def test_the_trace_id_of_the_text_follows_the_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    job = await one_job(tenant)
    (task,) = await tasks_of(tenant)
    (message,) = await sent_acks(tenant)
    assert job.trace_id is not None
    assert provider.requests[0].trace_id == job.trace_id == task.trace_id == message.trace_id


async def test_the_clinics_own_wording_is_sent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, ack_text=CUSTOM)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert provider.requests[0].body == CUSTOM


async def test_the_wording_is_read_when_the_job_runs_not_saved_with_the_job(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)  # the job exists now, with no settings row at all
    job = await one_job(tenant)
    assert job.payload.keys() == {"message_id"}  # nothing about wording is saved with it
    await set_settings(tenant, ack_text=CUSTOM)  # the clinic edits its wording after the text arrived
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert provider.requests[0].body == CUSTOM


async def test_ai_settings_are_never_read(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(
        tenant,
        ack_text=CUSTOM,
        ai_enabled=True,
        capabilities={"answer_questions": True, "quote_pricing": False},
    )
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert [r.body for r in provider.requests] == [CUSTOM]  # a template, whatever the AI switches say


async def test_quiet_hours_do_not_hold_back_an_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, timezone="UTC")
    engine, provider, clock = make_engine()
    await set_settings(tenant, quiet_hours=around(clock))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_a_lead_with_no_consent_record_is_answered(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)  # no consent row at all: a reply to their own text needs no grant
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert len(provider.requests) == 1 and await consents(tenant, lead.contact) == []


# --- once per wait ----------------


async def test_a_second_text_in_the_wait_gets_no_second_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    await seed_text(tenant, lead, n=2)
    engine, provider, _ = make_engine()
    assert await engine.run_due(tenant) == 2
    assert len(provider.requests) == 1 and len(await sent_acks(tenant)) == 1
    codes = sorted(str(j.last_error_code) for j in await jobs_of_kind(tenant, "ack"))
    assert codes == ["None", "already_acked"]


async def test_a_text_after_the_task_is_handled_starts_a_new_wait_with_a_new_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    engine, provider, clock = make_engine()
    await engine.run_due(tenant)
    async with tenant_session(tenant) as session:
        await session.execute(update(Task).values(status="handled", handled_at=clock()))
    clock.advance(hours=1)
    await seed_text(tenant, lead, n=2, created_at=clock(), run_at=clock())
    await engine.run_due(tenant)
    assert len(provider.requests) == 2 and len(await sent_acks(tenant)) == 2


async def test_a_crash_after_the_send_but_before_the_job_is_marked_done_sends_nothing_twice(make_tenant):
    class DiesBeforeMarkingDone(PostgresJobQueue):
        dies = True

        async def complete(self, job, *, code=None):
            if self.dies:
                self.dies = False
                raise SystemError("the process was killed")
            return await super().complete(job, code=code)

    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    clock = make_engine()[2]
    queue = DiesBeforeMarkingDone(clock=clock)
    engine, provider, _ = make_engine(clock=clock, queue=queue)
    with pytest.raises(SystemError):
        await engine.run_due(tenant)
    assert len(provider.requests) == 1  # it was sent
    assert (await one_job(tenant)).status == "pending"  # but the job was never marked done
    clock.advance(seconds=LEASE_SECONDS)
    assert await engine.run_due(tenant) == 1
    assert len(provider.requests) == 1 and len(await sent_acks(tenant)) == 1
    job = await one_job(tenant)
    # The first run had already stamped the task, so the second run stops at "already acked", before the gateway.
    assert (job.status, job.last_error_code, job.attempts) == ("done", "already_acked", 2)
    assert (await tasks_of(tenant))[0].first_ack_at is not None


async def test_a_crash_after_the_send_but_before_the_task_is_stamped_is_caught_by_the_gateways_key(
    make_tenant, monkeypatch
):
    """The other crash point. The task still says no ack was sent, so the second run gets as far as the gateway, whose
    key ``ack:{task_id}`` answers "duplicate". Still nothing is resent."""
    real = ack.mark_first_ack
    calls = []

    async def dies_once(session, task_id, when):
        calls.append(1)
        if len(calls) == 1:
            raise SystemError("the process was killed")
        return await real(session, task_id, when)

    monkeypatch.setattr(ack, "mark_first_ack", dies_once)
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    await engine.run_due(tenant)  # the handler raises after the send: the engine records a failed attempt
    assert len(provider.requests) == 1 and (await tasks_of(tenant))[0].first_ack_at is None
    job = await one_job(tenant)
    assert (job.status, job.attempts) == ("pending", 1)
    clock.advance(seconds=31)  # past the first backoff
    assert await engine.run_due(tenant) == 1
    assert len(provider.requests) == 1 and len(await sent_acks(tenant)) == 1
    job = await one_job(tenant)
    assert (job.status, job.last_error_code) == ("done", "duplicate")
    assert (await tasks_of(tenant))[0].first_ack_at is not None


async def test_a_crash_before_the_send_sends_it_once_on_the_next_run(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine()
    claimed = await engine.queue.claim(tenant)  # a worker claimed it and died before doing anything
    assert len(claimed) == 1 and provider.requests == []
    clock.advance(seconds=LEASE_SECONDS)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1 and (await one_job(tenant)).status == "done"


# --- the gateway's seven answers ----------------


async def test_retry_puts_the_job_back_without_counting_it_and_the_next_run_resumes_the_same_message(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    provider = FakeProvider(failure(ErrorKind.RETRYABLE, "30003"), accepted("SM" + "2" * 32))
    engine, provider, clock = make_engine(provider)
    await engine.run_due(tenant)
    job = await one_job(tenant)
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)
    assert job.run_at == clock() + timedelta(seconds=3)  # the live lane's first retry delay
    assert (await tasks_of(tenant))[0].first_ack_at is None
    assert await engine.run_due(tenant) == 0  # not due yet
    clock.advance(seconds=3)
    assert await engine.run_due(tenant) == 1
    assert [r.attempt for r in provider.requests] == [1, 2]
    (message,) = await sent_acks(tenant)  # one message, tried twice
    assert {e.status for e in await events(tenant, message.id)} >= {"failed", "sent"}
    assert (await one_job(tenant)).status == "done" and (await tasks_of(tenant))[0].first_ack_at is not None


async def test_retries_stop_when_the_gateway_says_so_and_the_ack_fails_for_good(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine(FakeProvider(failure(ErrorKind.RETRYABLE, "30003")))
    for delay in (3, 15, 45):
        await engine.run_due(tenant)
        clock.advance(seconds=delay)
    await engine.run_due(tenant)
    assert len(provider.requests) == 4  # the first try and three retries
    job = await one_job(tenant)
    assert job.status == "done" and job.last_error_code == "failed_retries_exhausted"
    assert len(await tasks_of(tenant)) == 1  # the lead is still on staff's list


async def test_a_permanent_failure_ends_the_job_and_keeps_the_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine(FakeProvider(failure(ErrorKind.INVALID_NUMBER, "21211")))
    await engine.run_due(tenant)
    job = await one_job(tenant)
    assert (job.status, job.last_error_code) == ("done", "failed_invalid_number")
    task = (await tasks_of(tenant))[0]
    assert task.first_ack_at is None and task.status == "open"


async def test_a_clinic_with_no_sending_number_fails_the_ack_and_keeps_the_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine(number=None)
    await engine.run_due(tenant)
    assert (await one_job(tenant)).last_error_code == "failed_no_from_number" and provider.requests == []


async def test_an_opted_out_contact_is_blocked_and_nothing_is_sent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert provider.requests == []
    assert (await one_job(tenant)).last_error_code == "blocked_opted_out"
    (message,) = await sent_acks(tenant)  # the gateway still records the blocked ack
    assert [e.status for e in await events(tenant, message.id)] == ["blocked"]


async def test_a_contact_with_no_phone_number_is_blocked(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=None)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert provider.requests == [] and (await one_job(tenant)).last_error_code == "blocked_no_phone"
    assert len(await tasks_of(tenant)) == 1


async def test_the_carrier_reporting_an_opt_out_records_the_revocation_and_ends_the_job(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine(FakeProvider(failure(ErrorKind.OPT_OUT, "21610")))
    await engine.run_due(tenant)
    assert (await one_job(tenant)).last_error_code == "failed_opt_out"
    assert [(c.granted, c.source) for c in await consents(tenant, lead.contact)] == [(False, "stop")]
    assert len(await tasks_of(tenant)) == 1


async def test_an_uncertain_send_is_never_resent_by_this_job_or_another(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    await seed_text(tenant, lead, n=2)
    engine, provider, _ = make_engine(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    await engine.run_due(tenant, limit=1)
    assert len(provider.requests) == 1
    first = (await jobs_of_kind(tenant, "ack"))[0]
    assert (first.status, first.last_error_code) == ("done", "uncertain")
    (message,) = await sent_acks(tenant)
    assert [e.status for e in await events(tenant, message.id)] == ["sending"]  # it may or may not have gone out
    await engine.run_due(tenant, limit=1)  # the second text's job: same wait, same key
    assert len(provider.requests) == 1  # still only one try
    assert (await tasks_of(tenant))[0].first_ack_at is None


async def test_a_delivery_receipt_after_an_uncertain_send_settles_it(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, _, _ = make_engine(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    await engine.run_due(tenant)
    (message,) = await sent_acks(tenant)
    result = await engine.gateway.record_receipt(
        tenant, provider_status="delivered", trace_id=uuid.uuid4(), message_id=message.id
    )
    assert result.recorded and result.status is MessageStatus.DELIVERED


# --- what each answer means, stated directly ----------------


NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_the_job_ends_the_way_each_answer_says():
    later = NOW + timedelta(minutes=5)
    table = [
        (SendResult(Outcome.SENT), Done()),
        (SendResult(Outcome.DUPLICATE, status=MessageStatus.SENT), Done("duplicate")),
        (SendResult(Outcome.DUPLICATE, status=MessageStatus.DELIVERED), Done("duplicate")),
        (SendResult(Outcome.DUPLICATE, status=MessageStatus.SENDING), Done("uncertain")),
        (SendResult(Outcome.RETRY, retry_after_seconds=15), Wait(NOW + timedelta(seconds=15))),
        (SendResult(Outcome.FAILED, reason="invalid_number"), Done("failed_invalid_number")),
        (SendResult(Outcome.BLOCKED, reason="opted_out"), Done("blocked_opted_out")),
        (SendResult(Outcome.DEFERRED, until=later, reason="quiet_hours"), Wait(later)),
        (SendResult(Outcome.UNCERTAIN, reason="ambiguous"), Done("uncertain")),
    ]
    for result, end in table:
        assert _end_for(result, NOW) == end


@pytest.mark.parametrize("outcome", list(Outcome))
def test_every_outcome_the_gateway_can_give_has_an_answer(outcome):
    end = _end_for(SendResult(outcome, reason="x", retry_after_seconds=1, until=NOW), NOW)
    assert isinstance(end, Done | Wait)


async def test_a_slow_worker_that_loses_its_lease_changes_nothing_and_the_ack_is_not_sent_twice(make_tenant, caplog):
    """Worker A is still inside the provider call when its lease runs out. Worker B claims the job and runs it. When A
    finally tries to mark the job done it no longer owns it: it is told so, logs it, and leaves B's work alone."""
    caplog.set_level("DEBUG", logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    taken = {}

    async def while_a_is_still_sending(request):
        clock.advance(seconds=LEASE_SECONDS)  # A is slow: its lease ends
        taken["by_b"] = await engine_b.queue.claim(tenant)  # B takes the job

    engine_a, provider, clock = make_engine(FakeProvider(accepted("SM" + "1" * 32), hook=while_a_is_still_sending))
    engine_b, _, _ = make_engine(provider, clock=clock)
    clock.advance(seconds=1)
    await engine_a.run_due(tenant)
    (stolen,) = taken["by_b"]
    job = await one_job(tenant)
    assert (job.status, job.locked_at) == ("pending", stolen.token)  # A did not mark it done: it is B's now
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("job_lease_lost")]
    assert len(lines) == 1 and f"job_id={job.id}" in lines[0] and f"tenant_id={tenant}" in lines[0]
    await engine_b.run_job(stolen)  # B does the job: the ack was already made, so nothing is sent again
    assert len(provider.requests) == 1 and len(await sent_acks(tenant)) == 1
    job = await one_job(tenant)
    assert job.status == "done" and job.last_error_code == "already_acked"
