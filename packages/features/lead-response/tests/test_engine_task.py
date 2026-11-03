"""The priority task: made first, one per wait, and there whatever becomes of the acknowledgement."""

import asyncio
import uuid
from datetime import timedelta

from lr_engine import (
    add_outbound,
    all_jobs,
    around,
    get_job,
    jobs_of_kind,
    make_engine,
    messages_of,
    seed_text,
    tasks_of,
)
from lr_gateway import FakeProvider, accepted, failure, make_lead, set_settings
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job, Task
from clinic_lead_response.gateway.retry import ErrorKind


async def test_the_task_and_its_timers_exist_before_the_provider_is_called(make_tenant):
    """The order, asserted from inside the provider call: nothing is sent until the task has been committed."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    message = await seed_text(tenant, lead)
    seen = {}

    async def at_the_moment_of_sending(request):
        seen["tasks"] = await tasks_of(tenant)
        seen["timers"] = sorted(j.kind for j in await all_jobs(tenant) if j.kind != "ack")
        seen["calls"] = 1

    engine, provider, _ = make_engine(FakeProvider(accepted("SM" + "1" * 32), hook=at_the_moment_of_sending))
    assert await engine.run_due(tenant) == 1
    assert seen["calls"] == 1 and len(provider.requests) == 1
    (task,) = seen["tasks"]
    assert (task.status, task.first_ack_at, task.conversation_id, task.contact_id) == (
        "open",
        None,
        lead.conversation,
        lead.contact,
    )
    assert seen["timers"] == ["escalate", "holding"]
    assert message  # the text the wait began with


async def test_the_task_is_made_with_the_right_facts(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    trace = uuid.uuid4()
    message = await seed_text(tenant, lead, trace_id=trace)
    engine, _, _ = make_engine()
    await engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    (text,) = [m for m in await messages_of(tenant) if m.id == message]
    assert (task.status, task.priority, task.escalation_state) == ("open", 0, "none")
    assert task.received_at == text.created_at and task.trace_id == trace
    assert (task.holding_sent_at, task.first_staff_reply_at, task.handled_at, task.escalated_at) == (None,) * 4


async def test_the_holding_and_escalation_jobs_are_written_with_the_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    trace = uuid.uuid4()
    await seed_text(tenant, lead, trace_id=trace)
    engine, _, _ = make_engine()
    await engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    (holding,) = await jobs_of_kind(tenant, "holding")
    (escalate,) = await jobs_of_kind(tenant, "escalate")
    assert holding.idempotency_key == f"holding:{task.id}" and escalate.idempotency_key == f"escalate:{task.id}"
    for job in (holding, escalate):
        assert (job.status, job.attempts, job.task_id, job.conversation_id) == (
            "pending",
            0,
            task.id,
            lead.conversation,
        )
        assert job.payload == {"task_id": str(task.id)} and job.trace_id == trace
    assert holding.run_at == task.received_at + timedelta(minutes=15)  # the default holding timer
    assert escalate.run_at == task.received_at + timedelta(minutes=30)  # the default staff target


async def test_the_timers_use_the_clinics_settings_when_the_task_is_made(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, holding_minutes=20, sla_minutes=45)
    await seed_text(tenant, lead)
    engine, _, _ = make_engine()
    await engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    assert (await jobs_of_kind(tenant, "holding"))[0].run_at == task.received_at + timedelta(minutes=20)
    assert (await jobs_of_kind(tenant, "escalate"))[0].run_at == task.received_at + timedelta(minutes=45)


async def test_a_second_text_in_the_same_wait_joins_the_open_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    await seed_text(tenant, lead, n=2)
    engine, _, _ = make_engine()
    assert await engine.run_due(tenant) == 2
    assert len(await tasks_of(tenant)) == 1
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1


async def test_the_wait_is_dated_from_the_first_text_not_the_second(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    first_at = clock() - timedelta(minutes=10)
    await seed_text(tenant, lead, n=1, created_at=first_at, run_at=first_at)
    await seed_text(tenant, lead, n=2, created_at=clock() - timedelta(minutes=5), run_at=clock() - timedelta(minutes=5))
    await engine.run_due(tenant)  # oldest job first
    (task,) = await tasks_of(tenant)
    assert task.received_at == first_at


async def test_running_the_same_job_twice_makes_one_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, _, clock = make_engine()
    await engine.run_due(tenant)
    (job,) = await jobs_of_kind(tenant, "ack")
    async with tenant_session(tenant) as session:  # as if a crash had left the job to be run again
        await session.execute(
            update(Job).where(Job.id == job.id).values(status="pending", run_at=clock(), finished_at=None)
        )
    await engine.run_due(tenant)
    assert len(await tasks_of(tenant)) == 1 and len(await all_jobs(tenant)) == 3


async def test_two_workers_on_two_texts_of_one_wait_make_one_task_and_one_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    await seed_text(tenant, lead, n=2)
    first, provider, clock = make_engine()
    second, _, _ = make_engine(provider, clock=clock)
    counts = await asyncio.gather(first.run_due(tenant, limit=1), second.run_due(tenant, limit=1))
    assert sorted(counts) == [1, 1]
    assert len(await tasks_of(tenant)) == 1
    assert len(provider.requests) == 1
    assert len(await jobs_of_kind(tenant, "holding")) == 1


async def test_a_new_task_is_made_once_the_old_wait_is_over(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead, n=1)
    engine, provider, clock = make_engine()
    await engine.run_due(tenant)
    async with tenant_session(tenant) as session:  # staff handled it
        await session.execute(update(Task).values(status="handled", handled_at=clock()))
    clock.advance(hours=3)
    await seed_text(tenant, lead, n=2, created_at=clock(), run_at=clock())
    await engine.run_due(tenant)
    tasks = await tasks_of(tenant)
    assert [t.status for t in tasks] == ["handled", "open"]
    assert len(await jobs_of_kind(tenant, "holding")) == 2 and len(await jobs_of_kind(tenant, "escalate")) == 2


async def test_a_different_conversation_gets_its_own_task(make_tenant):
    tenant = await make_tenant()
    one = await make_lead(tenant, phone="+14155550142")
    two = await make_lead(tenant, phone="+14155550177")
    await seed_text(tenant, one, n=1)
    await seed_text(tenant, two, n=2)
    engine, _, _ = make_engine()
    await engine.run_due(tenant)
    assert {t.conversation_id for t in await tasks_of(tenant)} == {one.conversation, two.conversation}


# --- the task is there whatever becomes of the acknowledgement ------------------------------------------------------


async def test_a_contact_who_opted_out_still_gets_a_task_and_timers(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    assert provider.requests == []  # the gateway blocked the ack
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.first_ack_at is None
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1
    (ack,) = await jobs_of_kind(tenant, "ack")
    assert (ack.status, ack.last_error_code) == ("done", "blocked_opted_out")


async def test_a_failed_ack_still_leaves_a_task_and_timers(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine(FakeProvider(failure(ErrorKind.PERMANENT, "21211")))
    await engine.run_due(tenant)
    assert len(provider.requests) == 1
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.first_ack_at is None
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1


async def test_a_provider_that_raises_still_leaves_a_task(make_tenant):
    class Raising:
        name = "raising"

        async def send(self, request):
            raise RuntimeError("an adapter bug")

    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, _, _ = make_engine(Raising())
    await engine.run_due(tenant)
    assert len(await tasks_of(tenant)) == 1


async def test_a_clinic_with_no_sending_number_still_gets_a_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, _ = make_engine(number=None)
    await engine.run_due(tenant)
    assert provider.requests == [] and len(await tasks_of(tenant)) == 1


async def test_a_task_is_made_even_when_no_ack_is_due(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    await seed_text(tenant, lead, created_at=clock() - timedelta(minutes=1), run_at=clock() - timedelta(minutes=1))
    await add_outbound(tenant, lead, sender_kind="staff", created_at=clock())  # staff already answered
    await engine.run_due(tenant)
    assert provider.requests == [] and len(await tasks_of(tenant)) == 1
    assert (await jobs_of_kind(tenant, "ack"))[0].last_error_code == "staff_replied"


async def test_a_task_is_made_even_during_quiet_hours(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, timezone="UTC")
    engine, provider, clock = make_engine()
    await set_settings(tenant, quiet_hours=around(clock))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)  # the text was stamped a moment after the clock was made: let its job fall due
    await engine.run_due(tenant)
    assert (
        len(await tasks_of(tenant)) == 1 and len(provider.requests) == 1
    )  # and the ack goes out: acks ignore quiet hours


# --- jobs that cannot be run -----------------------------------------------------------------------------------------


async def test_a_job_whose_message_is_gone_is_cancelled_and_makes_no_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    async with tenant_session(tenant) as session:
        await session.execute(update(Job).values(payload={"message_id": str(uuid.uuid4())}))
    engine, provider, _ = make_engine()
    await engine.run_due(tenant)
    (job,) = await jobs_of_kind(tenant, "ack")
    assert (job.status, job.cancel_reason) == ("cancelled", "message_missing")
    assert await tasks_of(tenant) == [] and provider.requests == []


async def test_a_job_with_a_broken_payload_is_cancelled(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    async with tenant_session(tenant) as session:
        await session.execute(update(Job).values(payload={"message_id": "not-an-id"}))
    engine, _, _ = make_engine()
    await engine.run_due(tenant)
    assert (await jobs_of_kind(tenant, "ack"))[0].cancel_reason == "bad_payload"


async def test_a_message_that_is_not_inbound_makes_no_task(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    outbound = await add_outbound(tenant, lead, sender_kind="staff", created_at=clock())
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                tenant_id=tenant,
                kind="ack",
                run_at=clock(),
                idempotency_key=f"ack:{outbound}",
                payload={"message_id": str(outbound)},
            )
        )
    await engine.run_due(tenant)
    assert await tasks_of(tenant) == [] and provider.requests == []
    assert (await get_job(tenant, (await jobs_of_kind(tenant, "ack"))[0].id)).cancel_reason == "message_missing"
