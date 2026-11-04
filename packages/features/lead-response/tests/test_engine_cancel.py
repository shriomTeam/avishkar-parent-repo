"""When the timers must stand down: a staff reply, a handled task, or a STOP. Checked when a job fires, and again
immediately before the gateway is called."""

import uuid
from datetime import timedelta

from lr_engine import add_outbound, jobs_of_kind, make_engine, seed_text, tasks_of
from lr_gateway import make_lead
from lr_wait import go_to, holdings, open_wait, opt_in, opt_out, set_task, staff_reply, timer
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job, Task
from clinic_lead_response.engine import holding
from clinic_lead_response.engine.waits import cancel_timers


async def states(tenant):
    return {
        j.kind: (j.status, j.cancel_reason)
        for j in await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    }


# --- a staff reply ----------------


async def test_a_staff_reply_cancels_the_holding_and_escalation_jobs(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    replied = await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=2))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert await states(tenant) == {"holding": ("cancelled", "staff_reply"), "escalate": ("cancelled", "staff_reply")}
    assert replied


async def test_the_staff_reply_is_noted_on_the_task_and_the_task_stays_open(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    at = wait.task.received_at + timedelta(minutes=2)
    await staff_reply(tenant, lead, at)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    assert task.first_staff_reply_at == at and task.status == "open" and task.handled_at is None


async def test_the_earliest_reply_is_the_one_noted(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    first = wait.task.received_at + timedelta(minutes=2)
    await staff_reply(tenant, lead, first + timedelta(minutes=5))
    await staff_reply(tenant, lead, first)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await tasks_of(tenant))[0].first_staff_reply_at == first


async def test_a_time_the_reply_api_already_wrote_is_never_overwritten(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    written = wait.task.received_at + timedelta(minutes=1)
    await set_task(tenant, first_staff_reply_at=written)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=2))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await tasks_of(tenant))[0].first_staff_reply_at == written


async def test_a_reply_from_before_the_wait_does_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at - timedelta(days=2))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1 and (await tasks_of(tenant))[0].first_staff_reply_at is None


async def test_only_a_staff_message_counts_as_an_answer(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    for kind in ("ack", "holding", "help", "followup"):
        await add_outbound(tenant, lead, sender_kind=kind, created_at=wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_a_reply_in_another_conversation_does_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone="+14155550142")
    other = await make_lead(tenant, phone="+14155550177")
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, other, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_a_reply_a_moment_before_the_timer_is_still_seen(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await staff_reply(tenant, lead, wait.clock() - timedelta(seconds=0.5))
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []


# --- a handled task ----------------


async def test_a_handled_task_cancels_both_jobs(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await set_task(tenant, status="handled", handled_at=wait.clock())
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert await states(tenant) == {"holding": ("cancelled", "handled"), "escalate": ("cancelled", "handled")}


async def test_a_task_closed_in_another_way_cancels_with_its_own_reason(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await set_task(tenant, status="cancelled")
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert await states(tenant) == {"holding": ("cancelled", "task_closed"), "escalate": ("cancelled", "task_closed")}


async def test_handled_wins_over_a_staff_reply_and_a_stop(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    await opt_out(tenant, lead)
    await set_task(tenant, status="handled", handled_at=wait.clock())
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await states(tenant))["holding"] == ("cancelled", "handled")


async def test_a_staff_reply_wins_over_a_stop(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await states(tenant))["holding"] == ("cancelled", "staff_reply")


# --- a STOP ----------------


async def test_a_stop_cancels_the_automatic_messages_but_the_task_stays_open(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert await states(tenant) == {"holding": ("cancelled", "stop"), "escalate": ("cancelled", "stop")}
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.handled_at is None and task.first_staff_reply_at is None


async def test_a_stop_the_carrier_reported_counts_the_same(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead, source="stop")  # what a 21610 receipt records
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await states(tenant))["holding"] == ("cancelled", "stop")


async def test_a_contact_who_opted_out_before_the_text_gets_no_holding_message_either(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == [] and (await states(tenant))["holding"] == ("cancelled", "stop")
    assert (await tasks_of(tenant))[0].status == "open"


async def test_start_after_stop_lets_the_holding_message_go_out(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    await opt_in(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1


async def test_a_stop_cancels_before_the_timer_is_even_up(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await timer(tenant, "escalate")).status == "cancelled"  # the sibling went with it


# --- what cancelling touches ----------------


async def test_cancelling_one_task_leaves_another_tasks_timers_alone(make_tenant):
    tenant = await make_tenant()
    one = await make_lead(tenant, phone="+14155550142")
    two = await make_lead(tenant, phone="+14155550177")
    engine, provider, clock = make_engine()
    await seed_text(tenant, one, n=1)
    await seed_text(tenant, two, n=2)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    first, second = await tasks_of(tenant)
    await staff_reply(tenant, one, first.received_at + timedelta(minutes=1))
    clock.now = max(first.received_at, second.received_at) + timedelta(minutes=15, seconds=1)
    await engine.run_due(tenant)
    by_task = {}
    for job in await jobs_of_kind(tenant, "holding"):
        by_task[job.task_id] = (job.status, job.cancel_reason)
    assert by_task[first.id] == ("cancelled", "staff_reply") and by_task[second.id] == ("done", None)


async def test_a_timer_that_already_finished_is_not_rewritten(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    async with tenant_session(tenant) as session:
        await session.execute(
            Job.__table__.update().where(Job.kind == "escalate").values(status="done", finished_at=wait.clock())
        )
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await states(tenant))["escalate"] == ("done", None)


async def test_cancelling_never_touches_the_ack_job(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await seed_text(
        tenant, lead, n=2, created_at=wait.clock() + timedelta(minutes=1), run_at=wait.clock() + timedelta(days=1)
    )
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    pending_acks = [j for j in await jobs_of_kind(tenant, "ack") if j.status == "pending"]
    assert len(pending_acks) == 1


async def test_cancel_timers_spares_the_job_that_is_deciding(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    holding_job = await timer(tenant, "holding")
    async with tenant_session(tenant) as session:
        count = await cancel_timers(session, wait.task.id, "stop", now=wait.clock(), keep=holding_job.id)
    assert count == 1
    assert await states(tenant) == {"holding": ("pending", None), "escalate": ("cancelled", "stop")}


async def test_running_the_cancelled_wait_again_changes_nothing(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at + timedelta(minutes=1))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    before = await states(tenant)
    go_to(wait, 60)
    assert await wait.engine.run_due(tenant) == 0
    assert await states(tenant) == before


# --- jobs that cannot be run ----------------


async def test_a_holding_job_for_a_task_that_does_not_exist_is_cancelled(make_tenant):
    tenant = await make_tenant()
    engine, provider, clock = make_engine()
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="holding",
                run_at=clock(),
                idempotency_key="holding:x",
                payload={"task_id": str(uuid.uuid4())},
            )
        )
    await engine.run_due(tenant)
    job = await timer(tenant, "holding")
    assert (job.status, job.cancel_reason) == ("cancelled", "task_missing") and provider.requests == []


async def test_a_holding_job_with_a_broken_payload_is_cancelled(make_tenant):
    tenant = await make_tenant()
    engine, provider, clock = make_engine()
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="holding",
                run_at=clock(),
                idempotency_key="holding:y",
                payload={"task_id": "nope"},
            )
        )
    await engine.run_due(tenant)
    assert (await timer(tenant, "holding")).cancel_reason == "bad_payload"


# --- the second look, immediately before the gateway ----------------


def second_look_after(monkeypatch, before):
    """Run ``before`` after the first decision and before the second look, as a staff reply landing in between would."""
    real = holding._recheck

    async def recheck(engine, job, plan):
        await before(plan)
        return await real(engine, job, plan)

    monkeypatch.setattr(holding, "_recheck", recheck)


async def test_a_staff_reply_between_the_decision_and_the_send_is_caught_by_the_second_look(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)

    async def reply_now(plan):
        await staff_reply(tenant, lead, wait.clock() - timedelta(seconds=0.2))

    second_look_after(monkeypatch, reply_now)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert (await states(tenant))["holding"] == ("cancelled", "staff_reply")


async def test_a_task_handled_between_the_decision_and_the_send_is_caught(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)

    async def handle_now(plan):
        await set_task(tenant, status="handled", handled_at=wait.clock())

    second_look_after(monkeypatch, handle_now)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == [] and (await states(tenant))["holding"] == ("cancelled", "handled")


async def test_a_stop_between_the_decision_and_the_send_is_caught(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)

    async def stop_now(plan):
        await opt_out(tenant, lead)

    second_look_after(monkeypatch, stop_now)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == [] and (await states(tenant))["holding"] == ("cancelled", "stop")


async def test_the_second_look_is_made_right_before_the_provider_is_called(make_tenant, monkeypatch):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    order = []
    real = holding._recheck

    async def recheck(engine, job, plan):
        order.append("second look")
        return await real(engine, job, plan)

    monkeypatch.setattr(holding, "_recheck", recheck)
    real_send = wait.provider.send

    async def send(request):
        order.append("provider")
        return await real_send(request)

    wait.provider.send = send
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert order == ["second look", "provider"]


async def test_a_reply_that_lands_after_the_second_look_cannot_stop_this_message(make_tenant):
    """The residual window, written down: the second look has passed, the provider call is under way. The lead gets one
    neutral line, nothing breaks, and the task is stamped."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    real_send = wait.provider.send

    async def send(request):
        if request.body == holding.HOLDING_TEXT_PLACEHOLDER:
            await staff_reply(tenant, lead, wait.clock())  # lands while the message is on its way
        return await real_send(request)

    wait.provider.send = send
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1
    assert (await tasks_of(tenant))[0].holding_sent_at is not None
    assert (await timer(tenant, "holding")).status == "done"


async def test_the_task_row_is_read_not_cached(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    async with tenant_session(tenant) as session:
        assert (await session.scalar(select(Task.status))) == "open"
    await set_task(tenant, status="handled", handled_at=wait.clock())
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
