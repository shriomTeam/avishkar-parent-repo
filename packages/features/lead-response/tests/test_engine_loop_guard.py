"""Two machines must not be able to keep each other talking, and one contact must not cost us unlimited texts."""

from datetime import timedelta

import pytest
from lr_engine import add_outbound, jobs_of_kind, make_engine, messages_of, seed_text, tasks_of
from lr_gateway import make_lead
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Task
from clinic_lead_response.engine.ack import AUTO_REPLY_SECONDS, DAILY_ACK_CAP


async def ack_job(tenant, index=-1):
    return (await jobs_of_kind(tenant, "ack"))[index]


def test_the_limits_are_the_agreed_ones():
    assert (DAILY_ACK_CAP, AUTO_REPLY_SECONDS) == (3, 5)


# --- a text that arrives right after our own message ----------------


@pytest.mark.parametrize("seconds", [0, 1, 3, 5])
async def test_a_text_within_five_seconds_of_our_message_is_treated_as_a_machine(make_tenant, seconds):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    ours = clock() - timedelta(hours=1)
    await add_outbound(tenant, lead, sender_kind="holding", created_at=ours)
    await seed_text(tenant, lead, created_at=ours + timedelta(seconds=seconds), run_at=ours)
    await engine.run_due(tenant)
    assert provider.requests == []
    assert (await ack_job(tenant)).last_error_code == "auto_reply"
    assert len(await tasks_of(tenant)) == 1  # the lead is still on staff's list


@pytest.mark.parametrize("seconds", [6, 30, 3600])
async def test_a_text_after_the_window_is_answered_normally(make_tenant, seconds):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    ours = clock() - timedelta(hours=2)
    await add_outbound(tenant, lead, sender_kind="holding", created_at=ours)
    await seed_text(tenant, lead, created_at=ours + timedelta(seconds=seconds), run_at=ours)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_a_text_that_came_before_our_message_is_not_a_reply_to_it(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    base = clock() - timedelta(hours=1)
    await add_outbound(tenant, lead, sender_kind="holding", created_at=base + timedelta(seconds=2))
    await seed_text(tenant, lead, created_at=base, run_at=base)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_any_message_of_ours_starts_the_window(make_tenant):
    for kind in ("ack", "holding", "help", "followup"):
        tenant = await make_tenant()
        lead = await make_lead(tenant)
        engine, provider, clock = make_engine()
        ours = clock() - timedelta(hours=1)
        await add_outbound(tenant, lead, sender_kind=kind, created_at=ours)
        await seed_text(tenant, lead, created_at=ours + timedelta(seconds=2), run_at=ours)
        await engine.run_due(tenant)
        assert provider.requests == [], kind


async def test_two_machines_answering_each_other_stop_after_one_message(make_tenant):
    """The lead's phone is an auto-responder. We ack it; it answers two seconds later; we must not answer that."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    await seed_text(tenant, lead, n=1)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1
    (ours,) = [m for m in await messages_of(tenant) if m.sender_kind == "ack"]
    for n in range(2, 8):
        answer_at = ours.created_at + timedelta(seconds=2)
        await seed_text(tenant, lead, n=n, created_at=answer_at, run_at=answer_at)
        clock.advance(seconds=10)
        await engine.run_due(tenant)
    assert len(provider.requests) == 1  # six machine answers, no second message from us
    assert len(await tasks_of(tenant)) == 1


# --- how many acks one contact can cost us in a day ----------------


async def test_three_acks_in_a_day_is_the_most_one_conversation_gets(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    for hours in (2, 3, 4):
        await add_outbound(tenant, lead, sender_kind="ack", created_at=clock() - timedelta(hours=hours))
    await seed_text(tenant, lead, created_at=clock() - timedelta(minutes=1), run_at=clock() - timedelta(minutes=1))
    await engine.run_due(tenant)
    assert provider.requests == [] and (await ack_job(tenant)).last_error_code == "capped"
    assert len(await tasks_of(tenant)) == 1 and (await tasks_of(tenant))[0].first_ack_at is None


async def test_two_acks_leave_room_for_a_third(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    for hours in (2, 3):
        await add_outbound(tenant, lead, sender_kind="ack", created_at=clock() - timedelta(hours=hours))
    await seed_text(tenant, lead, created_at=clock() - timedelta(minutes=1), run_at=clock() - timedelta(minutes=1))
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_acks_older_than_a_day_do_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    for hours in (25, 30, 40, 50):
        await add_outbound(tenant, lead, sender_kind="ack", created_at=clock() - timedelta(hours=hours))
    await seed_text(tenant, lead, created_at=clock() - timedelta(minutes=1), run_at=clock() - timedelta(minutes=1))
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_only_acks_count_towards_the_ack_cap(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    for kind in ("holding", "help", "staff", "followup", "holding"):
        await add_outbound(tenant, lead, sender_kind=kind, created_at=clock() - timedelta(hours=3))
    await seed_text(tenant, lead, created_at=clock() - timedelta(minutes=1), run_at=clock() - timedelta(minutes=1))
    await engine.run_due(tenant)
    assert len(provider.requests) == 1


async def test_the_cap_is_per_conversation(make_tenant):
    tenant = await make_tenant()
    busy = await make_lead(tenant, phone="+14155550142")
    quiet = await make_lead(tenant, phone="+14155550177")
    engine, provider, clock = make_engine()
    for hours in (2, 3, 4):
        await add_outbound(tenant, busy, sender_kind="ack", created_at=clock() - timedelta(hours=hours))
    when = clock() - timedelta(minutes=1)
    await seed_text(tenant, busy, n=1, created_at=when, run_at=when)
    await seed_text(tenant, quiet, n=2, created_at=when, run_at=when)
    await engine.run_due(tenant)
    assert [r.to for r in provider.requests] == ["+14155550177"]


async def test_an_endless_stream_of_waits_costs_at_most_three_acks_a_day(make_tenant):
    """Ten separate waits in a row (each closed by staff, each text ten minutes apart): three acks, then none."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    for n in range(1, 11):
        clock.advance(minutes=10)
        await seed_text(tenant, lead, n=n, created_at=clock(), run_at=clock())
        clock.advance(seconds=1)
        await engine.run_due(tenant)
        async with tenant_session(tenant) as session:
            await session.execute(update(Task).values(status="handled", handled_at=clock()))
    assert len(provider.requests) == DAILY_ACK_CAP
    codes = [j.last_error_code for j in await jobs_of_kind(tenant, "ack")]
    assert codes.count("capped") == 7 and codes.count(None) == 3
    assert len(await tasks_of(tenant)) == 10  # every wait still had its task


async def test_a_blocked_ack_counts_as_a_try(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, consent=(False, "stop"))
    engine, provider, clock = make_engine()
    for n in range(1, 6):
        clock.advance(minutes=10)
        await seed_text(tenant, lead, n=n, created_at=clock(), run_at=clock())
        clock.advance(seconds=1)
        await engine.run_due(tenant)
        async with tenant_session(tenant) as session:
            await session.execute(update(Task).values(status="handled", handled_at=clock()))
    assert provider.requests == []
    codes = [j.last_error_code for j in await jobs_of_kind(tenant, "ack")]
    assert codes.count("blocked_opted_out") == 3 and codes.count("capped") == 2


# --- the other reasons to skip ----------------


async def test_a_staff_reply_since_the_wait_began_means_no_ack(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    began = clock() - timedelta(minutes=10)
    await seed_text(tenant, lead, created_at=began, run_at=began)
    await add_outbound(tenant, lead, sender_kind="staff", created_at=began + timedelta(minutes=2))
    await engine.run_due(tenant)
    assert provider.requests == [] and (await ack_job(tenant)).last_error_code == "staff_replied"
    assert len(await tasks_of(tenant)) == 1


async def test_a_staff_reply_from_before_the_wait_does_not_count(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    began = clock() - timedelta(minutes=10)
    await add_outbound(tenant, lead, sender_kind="staff", created_at=began - timedelta(days=2))
    await seed_text(tenant, lead, created_at=began, run_at=began)
    await engine.run_due(tenant)
    assert len(provider.requests) == 1
