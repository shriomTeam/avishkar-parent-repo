"""The stuck-message sweep: a message left `sending` is settled with the gateway's own expiry and never resent."""

import uuid
from datetime import timedelta

from lr_engine import make_engine, messages_of, seed_text, tasks_of
from lr_gateway import FakeProvider, accepted, event_pairs, failure, make_lead, set_settings
from lr_intake import Counter
from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_db.models.lead_response import Message, MessageEvent
from clinic_lead_response.engine import sweep
from clinic_lead_response.gateway.retry import STUCK_AFTER_SECONDS, ErrorKind
from clinic_lead_response.gateway.status import current_status
from clinic_lead_response.gateway.types import Lane, MessageStatus

DEADLINE = STUCK_AFTER_SECONDS[Lane.LIVE]  # 120 seconds on the live lane


async def message_with(tenant, lead, events, *, clock, sender_kind="ack") -> uuid.UUID:
    """An outbound message with the given events: [(attempt, status, seconds_ago), ...]."""
    message_id = uuid.uuid4()
    async with tenant_session(tenant) as session:
        session.add(
            Message(
                id=message_id,
                tenant_id=tenant,
                conversation_id=lead.conversation,
                direction="outbound",
                channel="sms",
                sender_kind=sender_kind,
                body="x",
                provider="fake",
                idempotency_key=f"seed:{message_id}",
                created_at=clock() - timedelta(seconds=max(s for _, _, s in events)),
            )
        )
        await session.flush()
        for attempt, status, ago in events:
            session.add(
                MessageEvent(
                    tenant_id=tenant,
                    message_id=message_id,
                    attempt=attempt,
                    status=status,
                    created_at=clock() - timedelta(seconds=ago),
                )
            )
    return message_id


async def status_of(tenant, message_id):
    return current_status(await event_pairs(tenant, message_id))


# --- the real way a message gets stuck ----------------


async def test_an_ack_the_provider_never_answered_is_settled_and_not_resent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    (message,) = [m for m in await messages_of(tenant) if m.sender_kind == "ack"]
    assert await status_of(tenant, message.id) is MessageStatus.SENDING
    clock.advance(seconds=DEADLINE + 1)
    assert await sweep.expire_stuck(engine, tenant) == 1
    assert await status_of(tenant, message.id) is MessageStatus.FAILED
    failed = [e for e in await event_pairs(tenant, message.id)]
    assert (1, "failed") in failed
    assert len(provider.requests) == 1  # nothing was sent again
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.first_ack_at is None  # the lead is still on staff's list


async def test_the_reason_recorded_is_no_receipt(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    clock.advance(seconds=DEADLINE + 1)
    await sweep.expire_stuck(engine, tenant)
    async with tenant_session(tenant) as session:
        reasons = list(await session.scalars(select(MessageEvent.reason_code).where(MessageEvent.status == "failed")))
    assert reasons == ["no_receipt"]


async def test_a_delivery_receipt_that_turns_up_later_outranks_the_expiry(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout")))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    (message,) = [m for m in await messages_of(tenant) if m.sender_kind == "ack"]
    clock.advance(seconds=DEADLINE + 1)
    await sweep.expire_stuck(engine, tenant)
    await engine.gateway.record_receipt(
        tenant, provider_status="delivered", trace_id=uuid.uuid4(), message_id=message.id
    )
    assert await status_of(tenant, message.id) is MessageStatus.DELIVERED


async def test_a_message_that_is_retried_and_then_left_uncertain_is_settled_on_its_last_attempt(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(failure(ErrorKind.RETRYABLE, "30003"), failure(ErrorKind.AMBIGUOUS, "timeout"))
    engine, provider, clock = make_engine(provider)
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    clock.advance(seconds=3)
    await engine.run_due(tenant)  # the retry: attempt 2, ends uncertain
    (message,) = [m for m in await messages_of(tenant) if m.sender_kind == "ack"]
    clock.advance(seconds=DEADLINE + 1)
    assert await sweep.expire_stuck(engine, tenant) == 1
    assert [e for e in await event_pairs(tenant, message.id) if e[0] == 2][-1] == (2, "failed")


# --- which messages are stuck ----------------


async def test_a_message_is_not_stuck_until_the_deadline_has_passed(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", DEADLINE - 5)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 0
    clock.advance(seconds=6)
    assert await sweep.expire_stuck(engine, tenant) == 1


async def test_the_sweep_is_idempotent(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 1
    assert await sweep.expire_stuck(engine, tenant) == 0


async def test_messages_that_already_moved_on_are_left_alone(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    old = DEADLINE + 60
    kept = [
        await message_with(tenant, lead, [(1, "sending", old), (1, "sent", old - 1)], clock=clock),
        await message_with(tenant, lead, [(1, "sending", old), (1, "delivered", old - 1)], clock=clock),
        await message_with(tenant, lead, [(1, "sending", old), (1, "failed", old - 1)], clock=clock),
        await message_with(tenant, lead, [(1, "blocked", old)], clock=clock),
    ]
    assert await sweep.expire_stuck(engine, tenant) == 0
    for message_id in kept:
        assert len(await event_pairs(tenant, message_id)) <= 2


async def test_a_message_delivered_on_an_earlier_attempt_is_not_stuck(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    old = DEADLINE + 60
    await message_with(tenant, lead, [(1, "delivered", old), (2, "sending", old - 1)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 0


async def test_only_the_latest_attempt_decides(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    old = DEADLINE + 60
    stale = await message_with(tenant, lead, [(1, "sending", old), (2, "sent", old - 10)], clock=clock)
    stuck = await message_with(tenant, lead, [(1, "failed", old), (2, "sending", old - 10)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 1
    assert (2, "failed") in await event_pairs(tenant, stuck)
    assert (1, "failed") not in await event_pairs(tenant, stale)


async def test_a_stuck_staff_reply_is_settled_too(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock, sender_kind="staff")
    assert await sweep.expire_stuck(engine, tenant) == 1


async def test_messages_older_than_a_day_are_left_alone(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", 60 * 60 * 25)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 0


async def test_several_stuck_messages_are_all_settled(make_tenant):
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    for number in range(3):
        lead = await make_lead(tenant, phone=f"+1415555{number:04d}")
        await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 3


async def test_the_limit_caps_one_sweep(make_tenant):
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    for number in range(4):
        lead = await make_lead(tenant, phone=f"+1415555{number:04d}")
        await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant, limit=3) == 3
    assert await sweep.expire_stuck(engine, tenant, limit=3) == 1


async def test_the_oldest_stuck_message_always_goes_first(make_tenant):
    """Eight stuck messages, inserted in a scrambled order, expired one at a time: each sweep takes the oldest left."""
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    ages = [DEADLINE + extra for extra in (40, 900, 10, 500, 70, 300, 20, 700)]  # seconds stuck, in scrambled order
    ids = {}
    for number, age in enumerate(ages):
        lead = await make_lead(tenant, phone=f"+1415555{number:04d}")
        ids[age] = await message_with(tenant, lead, [(1, "sending", age)], clock=clock)
    for age in sorted(ages, reverse=True):  # the longest-stuck first
        assert await sweep.expire_stuck(engine, tenant, limit=1) == 1
        assert (1, "failed") in await event_pairs(tenant, ids[age]), f"the message stuck for {age}s should have gone"


async def test_the_count_is_of_messages_the_gateway_actually_expired(make_tenant, monkeypatch):
    """One of two candidates was settled by someone else between the read and the call: only one was expired."""
    tenant = await make_tenant()
    engine, _, clock = make_engine()
    for number in range(2):
        lead = await make_lead(tenant, phone=f"+1415555{number:04d}")
        await message_with(tenant, lead, [(1, "sending", DEADLINE + 30 + number)], clock=clock)
    real = engine.gateway.expire_stuck
    calls = []

    async def first_one_already_settled(*args, **kwargs):
        calls.append(1)
        return False if len(calls) == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(engine.gateway, "expire_stuck", first_one_already_settled)
    assert await sweep.expire_stuck(engine, tenant) == 1
    assert len(calls) == 2


async def test_the_sweep_sends_nothing(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    await sweep.expire_stuck(engine, tenant)
    assert provider.requests == []


# --- the gates and other clinics ----------------


async def test_with_the_switch_off_the_sweep_does_nothing_and_touches_nothing(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine(enabled=False)
    message = await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    with Counter() as statements:
        assert await sweep.expire_stuck(engine, tenant) == 0
    assert statements == [] and await status_of(tenant, message) is MessageStatus.SENDING


async def test_a_clinic_without_the_feature_is_not_swept(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, _, clock = make_engine()
    message = await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    assert await sweep.expire_stuck(engine, tenant) == 0
    assert await status_of(tenant, message) is MessageStatus.SENDING


async def test_sweeping_one_clinic_leaves_the_others_stuck_messages_alone(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a, lead_b = await make_lead(a), await make_lead(b)
    engine, _, clock = make_engine()
    in_a = await message_with(a, lead_a, [(1, "sending", DEADLINE + 30)], clock=clock)
    in_b = await message_with(b, lead_b, [(1, "sending", DEADLINE + 30)], clock=clock)
    assert await sweep.expire_stuck(engine, a) == 1
    assert await status_of(a, in_a) is MessageStatus.FAILED and await status_of(b, in_b) is MessageStatus.SENDING


async def test_a_sweep_with_nothing_stuck_costs_the_gates_and_one_read(make_tenant):
    tenant = await make_tenant()
    await make_lead(tenant)
    engine, _, _ = make_engine()
    with Counter() as statements:
        assert await sweep.expire_stuck(engine, tenant) == 0
    print(f"\nsweep, nothing stuck: {len(statements)} statements")
    assert len(statements) <= 2 + 2  # the two gates, then set_config and the one read


async def test_settings_and_clinic_names_have_no_effect_on_what_is_stuck(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, holding_minutes=60, sla_minutes=90)
    engine, _, clock = make_engine()
    await message_with(tenant, lead, [(1, "sending", DEADLINE + 30)], clock=clock)
    assert await sweep.expire_stuck(engine, tenant) == 1


async def test_an_ack_that_was_accepted_is_never_swept(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    engine, provider, clock = make_engine(FakeProvider(accepted("SM" + "1" * 32)))
    await seed_text(tenant, lead)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    clock.advance(hours=1)
    assert await sweep.expire_stuck(engine, tenant) == 0
