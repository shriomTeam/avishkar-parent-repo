"""The fast path after an inbound text: the task and its timers before the 200, the send in the background, the job row
as the safety net, and nothing at all while the engine switch is off."""

import asyncio
import gc
import logging
import uuid
from datetime import UTC, datetime, timedelta

from lr_engine import add_outbound, jobs_of_kind, messages_of, tasks_of
from lr_gateway import FakeProvider, accepted, make_lead
from lr_host import Held, make_host
from lr_intake import LEAD_NUMBER, OUR_NUMBER, Counter, Intake, sid, twilio_pairs

from clinic_lead_response.engine import ack
from clinic_lead_response.engine.queue import LEASE_SECONDS
from clinic_lead_response.intake.service import Accepted, Outcome

SID = "SM" + "1" * 32
# With the switch on, the work before the 200: the intake's own 8 (known lead) or 12 (new lead), the two gates (2), the
# claim (4) and ack.prepare (the task, its two timers and the decision), measured.
KNOWN_LEAD_BEFORE_THE_200 = 22
NEW_LEAD_BEFORE_THE_200 = 27
NUMBERS = ["+14155550142", "+14155550143", "+14155550144", "+14155550145"]


async def text(intake, tenant, body="Hello, are you open?", n=1, sender=LEAD_NUMBER):
    response = await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=body, From=sender))
    assert response.status_code == 200
    return response


async def only_ack_job(tenant):
    (job,) = await jobs_of_kind(tenant, "ack")
    return job


# --- before the 200 ----------------


async def test_the_task_and_timers_exist_when_the_200_is_sent_and_the_send_is_still_to_come(monkeypatch, make_tenant):
    held = Held()
    host = make_host(spawn=held)
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.first_ack_at is None
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1
    job = await only_ack_job(tenant)
    assert job.status == "pending" and job.locked_at is not None and job.run_at > host.clock()  # leased
    assert host.provider.requests == [] and len(held.items) == 1  # the send is waiting to be started
    held.discard()


async def test_the_task_is_there_before_the_provider_is_called(monkeypatch, make_tenant):
    tenant = await make_tenant()
    seen = {}

    async def at_the_moment_of_sending(request):
        seen["tasks"] = len(await tasks_of(tenant))
        seen["timers"] = len(await jobs_of_kind(tenant, "holding")) + len(await jobs_of_kind(tenant, "escalate"))

    host = make_host(FakeProvider(accepted(SID), hook=at_the_moment_of_sending))
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    await host.fast.drain()
    assert seen == {"tasks": 1, "timers": 2} and len(host.provider.requests) == 1


async def test_the_ack_goes_out_in_the_background_and_the_job_is_finished(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    await host.fast.drain()
    (sent,) = host.provider.requests
    assert (sent.to, sent.from_number) == (LEAD_NUMBER, OUR_NUMBER)
    job = await only_ack_job(tenant)
    assert (job.status, job.last_error_code, job.locked_at) == ("done", None, None)
    assert (await tasks_of(tenant))[0].first_ack_at is not None
    assert [m.sender_kind for m in await messages_of(tenant)] == ["contact", "ack"]


async def test_the_200_does_not_wait_for_the_provider(monkeypatch, make_tenant):
    release = asyncio.Event()

    async def slow_provider(request):
        await release.wait()

    host = make_host(FakeProvider(accepted(SID), hook=slow_provider))
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    response = await asyncio.wait_for(intake.post(tenant, twilio_pairs()), timeout=10)  # would hang if it waited
    assert response.status_code == 200 and host.fast.pending == 1
    release.set()
    await host.fast.drain()
    assert len(host.provider.requests) == 1 and host.fast.pending == 0


async def test_it_is_the_same_code_as_the_job_handler(monkeypatch, make_tenant):
    """The fast path calls ack.prepare and ack.deliver, which ack.handle is made of: there is one implementation."""
    calls = []
    real_prepare, real_deliver = ack.prepare, ack.deliver

    async def prepare(*args, **kwargs):
        calls.append("prepare")
        return await real_prepare(*args, **kwargs)

    async def deliver(*args, **kwargs):
        calls.append("deliver")
        return await real_deliver(*args, **kwargs)

    monkeypatch.setattr(ack, "prepare", prepare)
    monkeypatch.setattr(ack, "deliver", deliver)
    host = make_host()
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    await host.fast.drain()
    assert calls == ["prepare", "deliver"]


# --- failures never change the answer ----------------


async def test_a_background_failure_cannot_change_the_200_and_leaves_a_retry(monkeypatch, make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    real = ack.deliver
    calls = []

    async def fails_once(engine, job, ready):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError(f"cannot reach {LEAD_NUMBER} Zebra-Quartz")
        return await real(engine, job, ready)

    monkeypatch.setattr(ack, "deliver", fails_once)
    host = make_host()
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)  # the 200 was asserted inside `text`
    await host.fast.drain()
    job = await only_ack_job(tenant)
    assert (job.status, job.attempts, job.last_error_code, job.locked_at) == ("pending", 1, "RuntimeError", None)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("fast_path_failed")]
    assert f"tenant_id={tenant}" in line and "job_id=" in line and "reason=RuntimeError" in line
    assert LEAD_NUMBER not in line and "Zebra" not in line
    host.clock.advance(seconds=31)  # past the first backoff
    assert (await host.scheduler.tick(tenant)).jobs_run == 1
    assert len(host.provider.requests) == 1  # the retry sent it, once


async def test_a_failure_in_the_cheap_part_leaves_a_retry_and_the_200(monkeypatch, make_tenant):
    real = ack.prepare
    calls = []

    async def fails_once(engine, job):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the database blinked")
        return await real(engine, job)

    monkeypatch.setattr(ack, "prepare", fails_once)
    host = make_host()
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    job = await only_ack_job(tenant)
    assert (job.status, job.attempts, job.last_error_code) == ("pending", 1, "RuntimeError") and host.fast.pending == 0
    host.clock.advance(seconds=31)
    await host.scheduler.tick(tenant)
    assert len(host.provider.requests) == 1


async def test_a_hook_that_itself_fails_is_logged_by_the_route_and_the_200_stands(monkeypatch, make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    host = make_host()
    tenant = await make_tenant()

    async def broken(tenant_id):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(host.engine, "may_run", broken)
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    assert "after_commit_failed" in " ".join(r.getMessage() for r in caplog.records)
    assert len(await messages_of(tenant)) == 1  # the text is stored


async def test_a_slow_cheap_part_is_handed_to_the_tick_and_the_200_is_not_late(monkeypatch, make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    real = ack.prepare
    calls = []

    async def slow_once(engine, job):
        calls.append(1)
        if len(calls) == 1:
            await asyncio.Event().wait()  # never finishes
        return await real(engine, job)

    monkeypatch.setattr(ack, "prepare", slow_once)
    host = make_host(cheap_part_seconds=0.05)
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    job = await only_ack_job(tenant)
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None) and job.run_at <= host.clock()
    assert host.fast.pending == 0 and host.provider.requests == []
    assert any("reason=cheap_part_slow" in r.getMessage() for r in caplog.records)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1 and len(host.provider.requests) == 1


# --- the background tasks are bounded and kept ----------------


async def test_no_more_than_the_limit_of_sends_run_at_once_and_the_rest_go_to_the_tick(monkeypatch, make_tenant):
    release = asyncio.Event()
    state = {"now": 0, "high": 0}

    async def hold(request):
        state["now"] += 1
        state["high"] = max(state["high"], state["now"])
        await release.wait()
        state["now"] -= 1

    host = make_host(FakeProvider(accepted(SID), hook=hold), max_background=2)
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    for n, sender in enumerate(NUMBERS[:3], start=1):
        await text(intake, tenant, n=n, sender=sender)
    for _ in range(50):  # let the started sends reach the provider
        if state["now"] == 2:
            break
        await asyncio.sleep(0)
    jobs = await jobs_of_kind(tenant, "ack")
    leased = [j for j in jobs if j.locked_at is not None]
    handed_back = [j for j in jobs if j.locked_at is None]
    assert host.fast.pending == 2 and len(leased) == 2 and len(handed_back) == 1
    assert handed_back[0].attempts == 0 and handed_back[0].run_at <= host.clock()
    release.set()
    await host.fast.drain()
    assert state["high"] <= 2
    await host.scheduler.tick(tenant)
    assert len(host.provider.requests) == 3 and {j.status for j in await jobs_of_kind(tenant, "ack")} == {"done"}


async def test_a_finished_send_frees_its_slot(monkeypatch, make_tenant):
    host = make_host(max_background=1)
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    for n, sender in enumerate(NUMBERS, start=1):
        await text(intake, tenant, n=n, sender=sender)
        await host.fast.drain()
    assert len(host.provider.requests) == 4  # one slot was enough, one after another
    assert {j.status for j in await jobs_of_kind(tenant, "ack")} == {"done"}


async def test_a_failed_send_frees_its_slot_too(monkeypatch, make_tenant):
    async def boom(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(ack, "deliver", boom)
    host = make_host(max_background=1)
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    for n, sender in enumerate(NUMBERS[:3], start=1):
        await text(intake, tenant, n=n, sender=sender)
        await host.fast.drain()
    # every one of them got as far as being started (none was handed back for want of a slot)
    assert all(j.attempts == 1 and j.last_error_code == "RuntimeError" for j in await jobs_of_kind(tenant, "ack"))


async def test_a_background_send_is_kept_by_a_strong_reference_until_it_finishes(monkeypatch, make_tenant):
    release = asyncio.Event()

    async def hold(request):
        await release.wait()

    host = make_host(FakeProvider(accepted(SID), hook=hold))
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    gc.collect()
    assert host.fast.pending == 1
    release.set()
    await host.fast.drain()
    gc.collect()
    assert host.fast.pending == 0 and len(host.provider.requests) == 1
    assert (await only_ack_job(tenant)).status == "done"


# --- the job row is the safety net ----------------


async def test_a_frozen_instance_is_recovered_by_the_tick_through_the_lease_and_nothing_goes_twice(
    monkeypatch, make_tenant
):
    """The instance answered and was frozen before the background send ran. The lease runs out, a tick sends the ack
    once, and when the frozen instance wakes and runs its send, the gateway's key makes it a duplicate."""
    held = Held()
    host = make_host(spawn=held)
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    assert host.provider.requests == [] and len(held.items) == 1
    assert (await host.scheduler.tick(tenant)).jobs_run == 0  # still leased: another worker leaves it alone
    host.clock.advance(seconds=LEASE_SECONDS)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1  # the lease ran out: the tick takes it
    assert len(host.provider.requests) == 1
    job = await only_ack_job(tenant)
    assert (job.status, job.attempts) == ("done", 2)
    await held.thaw()  # the frozen instance wakes up
    assert (
        len(host.provider.requests) == 1 and len([m for m in await messages_of(tenant) if m.sender_kind == "ack"]) == 1
    )
    assert (await only_ack_job(tenant)).status == "done"  # and it changed nothing: its lease was lost


async def test_a_crash_between_the_intake_commit_and_the_hook_still_ends_with_the_task_first(monkeypatch, make_tenant):
    """The process dies after the text is committed and before the hook runs: nothing but the job row exists. The tick's
    job handler makes the task and its timers, and only then sends."""
    tenant = await make_tenant()

    async def never_runs(accepted):
        return None

    host = make_host()
    await text(Intake(monkeypatch, hook=never_runs), tenant)
    assert await tasks_of(tenant) == [] and (await only_ack_job(tenant)).status == "pending"
    seen = {}

    async def at_the_moment_of_sending(request):
        seen["tasks"] = len(await tasks_of(tenant))
        seen["timers"] = len(await jobs_of_kind(tenant, "holding")) + len(await jobs_of_kind(tenant, "escalate"))

    host.provider.hook = at_the_moment_of_sending
    assert (await host.scheduler.tick(tenant)).jobs_run == 1
    assert seen == {"tasks": 1, "timers": 2}  # created first, by the job handler, before any send
    assert len(host.provider.requests) == 1


async def test_a_tick_does_not_take_a_job_the_fast_path_has_leased(monkeypatch, make_tenant):
    held = Held()
    host = make_host(spawn=held)
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    before = await only_ack_job(tenant)
    report = await host.scheduler.tick(tenant)
    after = await only_ack_job(tenant)
    assert report.jobs_run == 0 and (after.locked_at, after.run_at, after.attempts) == (
        before.locked_at,
        before.run_at,
        before.attempts,
    )
    held.discard()


# --- what it does and does not do ----------------


async def test_two_texts_from_one_lead_before_the_first_send_finishes_still_make_one_ack(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    await text(intake, tenant, n=1)
    await text(intake, tenant, n=2, body="Hello? Anyone there?")
    await host.fast.drain()
    await host.scheduler.tick(tenant)
    assert len(host.provider.requests) == 1 and len(await tasks_of(tenant)) == 1
    assert {j.status for j in await jobs_of_kind(tenant, "ack")} == {"done"}


async def test_an_opted_out_contact_gets_a_task_and_a_blocked_ack(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    await make_lead(tenant, consent=(False, "stop"))
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    await host.fast.drain()
    assert host.provider.requests == [] and len(await tasks_of(tenant)) == 1
    assert (await only_ack_job(tenant)).last_error_code == "blocked_opted_out"


async def test_when_no_ack_is_due_the_job_is_finished_in_the_hook_and_nothing_is_started(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await add_outbound(tenant, lead, sender_kind="staff", created_at=datetime.now(UTC) + timedelta(hours=1))
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    assert host.fast.pending == 0 and host.provider.requests == []
    job = await only_ack_job(tenant)
    assert (job.status, job.last_error_code) == ("done", "staff_replied") and len(await tasks_of(tenant)) == 1


async def test_an_ack_for_another_leads_job_is_not_mixed_up_with_this_one(monkeypatch, make_tenant):
    host = make_host()
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    await text(intake, tenant, n=1, sender=NUMBERS[0])
    await text(intake, tenant, n=2, sender=NUMBERS[1])
    await host.fast.drain()
    assert sorted(r.to for r in host.provider.requests) == sorted(NUMBERS[:2])
    assert len(await tasks_of(tenant)) == 2


# --- when it does nothing ----------------


def fake_accepted(tenant, **kw):
    base = {"outcome": Outcome.STORED, "message_id": uuid.uuid4(), "ack_queued": True, "tenant_id": tenant}
    return Accepted(**{**base, **kw})


async def test_an_older_caller_that_gives_no_tenant_gets_nothing_done(make_tenant):
    host = make_host()
    with Counter() as statements:
        await host.fast.after_commit(fake_accepted(None))
    assert statements == []


async def test_a_text_with_no_ack_queued_gets_nothing_done(make_tenant):
    host = make_host()
    tenant = await make_tenant()
    with Counter() as statements:
        await host.fast.after_commit(fake_accepted(tenant, ack_queued=False))
    assert statements == []


async def test_with_the_switch_off_the_hook_reads_nothing_at_all(make_tenant):
    host = make_host(enabled=False)
    tenant = await make_tenant()
    with Counter() as statements:
        await host.fast.after_commit(fake_accepted(tenant))
    assert statements == []


async def test_a_clinic_without_the_feature_costs_only_the_feature_check(make_tenant):
    host = make_host()
    tenant = await make_tenant(())
    with Counter() as statements:
        await host.fast.after_commit(fake_accepted(tenant))
    assert len(statements) == 2 and host.provider.requests == []  # set_config and the feature read, nothing claimed


async def test_with_the_switch_off_the_text_is_stored_and_its_job_waits_untouched(monkeypatch, make_tenant):
    host = make_host(enabled=False)
    tenant = await make_tenant()
    await text(Intake(monkeypatch, hook=host.fast.after_commit), tenant)
    assert await tasks_of(tenant) == [] and host.provider.requests == [] and host.fast.pending == 0
    job = await only_ack_job(tenant)
    assert (job.status, job.attempts, job.locked_at) == ("pending", 0, None)


# --- the intake statement counts with the switch OFF are exactly what they were ----------------


async def counted(intake, tenant, **kw):
    with Counter() as statements:
        await text(intake, tenant, **kw)
    return len(statements)


async def test_with_the_switch_off_every_intake_statement_count_is_exactly_what_it_was(monkeypatch, make_tenant):
    host = make_host(enabled=False)
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    tenant = await make_tenant()
    assert await counted(intake, tenant, n=1, body="Hello") == 12  # a text from a new lead
    assert await counted(intake, tenant, n=2, body="And another") == 8  # a text from a known lead
    assert await counted(intake, tenant, n=2, body="And another") == 5  # a retry of that text
    with Counter() as statements:
        await intake.post(tenant, twilio_pairs(MessageSid=sid(9)), sign=False)
    assert statements == []  # a refused request


async def test_with_the_switch_off_the_keyword_counts_are_exactly_what_they_were(monkeypatch, make_tenant):
    host = make_host(enabled=False)
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    tenant = await make_tenant()
    assert await counted(intake, tenant, n=1, body="STOP") == 14  # STOP from a new lead
    other = await make_tenant()
    await text(intake, other, n=1, body="hello")
    assert await counted(intake, other, n=2, body="START") == 10  # START from a known lead
    assert await counted(intake, other, n=3, body="HELP") == 12  # HELP from a known lead
    assert await counted(intake, tenant, n=1, body="STOP") == 7  # a retried STOP that already took effect


async def test_with_the_switch_on_a_keyword_text_still_costs_what_it_did(monkeypatch, make_tenant):
    host = make_host(enabled=True)
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    tenant = await make_tenant()
    assert await counted(intake, tenant, n=1, body="STOP") == 14  # no ack is queued, so the hook does nothing
    assert await jobs_of_kind(tenant, "ack") == []


async def test_with_the_switch_on_a_retry_of_a_stored_text_costs_what_it_did(monkeypatch, make_tenant):
    host = make_host(enabled=True)
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    tenant = await make_tenant()
    await text(intake, tenant, n=1)
    await host.fast.drain()
    assert await counted(intake, tenant, n=1) == 5  # the route does not call the hook for a duplicate


async def test_with_the_switch_on_the_work_before_the_200_stays_small(monkeypatch, make_tenant):
    held = Held()
    host = make_host(enabled=True, spawn=held)
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    tenant = await make_tenant()
    await text(intake, tenant, n=1, sender=NUMBERS[0])
    known = await counted(intake, tenant, n=2, sender=NUMBERS[0], body="a second text")
    new_lead = await counted(intake, tenant, n=3, sender=NUMBERS[1], body="a new lead")
    held.discard()
    print(f"\nbefore the 200: a known lead {known} statements, a new lead {new_lead}")
    # intake (8 / 12) + the two gates (2) + the claim (4) + ack.prepare (task, timers and the decision)
    assert known <= KNOWN_LEAD_BEFORE_THE_200 and new_lead <= NEW_LEAD_BEFORE_THE_200
