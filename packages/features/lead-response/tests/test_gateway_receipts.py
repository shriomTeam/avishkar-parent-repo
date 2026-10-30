"""Delivery receipts: recorded as events, status derived, replays harmless, nothing ever updated."""

import uuid
from datetime import UTC, datetime, timedelta

from lr_gateway import (
    Clock,
    FakeProvider,
    accepted,
    audit_rows,
    consents,
    event_pairs,
    events,
    failure,
    gateway,
    make_lead,
    request,
)

from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.types import Lane, Outcome
from clinic_lead_response.gateway.types import MessageStatus as S


async def sent_message(t, sid="SMrx1", **lead_kw):
    lead = await make_lead(t, **lead_kw)
    g = gateway(FakeProvider(accepted(sid)))
    result = await g.send(t, request(lead))
    return g, lead, result.message_id


async def test_a_delivered_receipt_is_recorded_and_the_message_is_delivered(make_tenant):
    t = await make_tenant()
    g, _, message_id = await sent_message(t)
    trace = uuid.uuid4()
    receipt = await g.record_receipt(t, provider_message_id="SMrx1", provider_status="delivered", trace_id=trace)
    assert (receipt.recorded, receipt.status, receipt.message_id) == (True, S.DELIVERED, message_id)
    last = (await events(t, message_id))[-1]
    assert (last.status, last.attempt, last.provider_message_id, last.trace_id) == ("delivered", 1, "SMrx1", trace)


async def test_a_replayed_receipt_changes_nothing(make_tenant):
    t = await make_tenant()
    g, _, message_id = await sent_message(t)
    first = await g.record_receipt(t, provider_message_id="SMrx1", provider_status="delivered", trace_id=uuid.uuid4())
    again = await g.record_receipt(t, provider_message_id="SMrx1", provider_status="delivered", trace_id=uuid.uuid4())
    assert (first.recorded, again.recorded, again.status) == (True, False, S.DELIVERED)
    assert await event_pairs(t, message_id) == [(1, "sending"), (1, "sent"), (1, "delivered")]


async def test_receipts_in_any_order_end_delivered(make_tenant):
    t = await make_tenant()
    g, _, message_id = await sent_message(t)
    for status in ["delivered", "sent", "sending", "queued"]:  # the worst order: the late ones arrive after delivery
        receipt = await g.record_receipt(t, provider_message_id="SMrx1", provider_status=status, trace_id=uuid.uuid4())
        assert receipt.status is S.DELIVERED
    assert (
        await g.record_receipt(t, provider_message_id="SMrx1", provider_status="delivered", trace_id=uuid.uuid4())
    ).status is S.DELIVERED


async def test_an_undelivered_receipt_records_the_error_code_and_fails_the_message(make_tenant):
    t = await make_tenant()
    g, lead, message_id = await sent_message(t)
    receipt = await g.record_receipt(
        t, provider_message_id="SMrx1", provider_status="undelivered", error_code=30006, trace_id=uuid.uuid4()
    )
    assert (receipt.recorded, receipt.status) == (True, S.FAILED)
    assert (await events(t, message_id))[-1].reason_code == "30006"
    assert await consents(t, lead.contact) == []  # a landline is not an opt-out


async def test_an_opt_out_error_in_a_receipt_revokes_consent_once(make_tenant):
    t = await make_tenant()
    g, lead, _ = await sent_message(t, consent=(True, "first_inbound"))
    for _ in range(2):
        await g.record_receipt(
            t, provider_message_id="SMrx1", provider_status="failed", error_code=21610, trace_id=uuid.uuid4()
        )
    revocations = [c for c in await consents(t, lead.contact) if not c.granted]
    assert [(c.source, c.evidence) for c in revocations] == [("stop", {"provider_error_code": "21610"})]
    assert len(await audit_rows(t, "lead_response.consent.changed")) == 1


async def test_a_failed_receipt_with_a_retryable_code_allows_a_retry(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(accepted("SMrx1"), accepted("SMrx2"))
    g = gateway(provider)
    first = await g.send(t, request(lead))
    await g.record_receipt(
        t, provider_message_id="SMrx1", provider_status="undelivered", error_code=30003, trace_id=uuid.uuid4()
    )
    again = await g.attempt_again(t, first.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert (again.outcome, again.attempt) == (Outcome.SENT, 2) and len(provider.requests) == 2


async def test_a_failed_receipt_with_a_permanent_code_blocks_any_retry(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(accepted("SMrx1"))
    g = gateway(provider)
    first = await g.send(t, request(lead))
    await g.record_receipt(
        t, provider_message_id="SMrx1", provider_status="undelivered", error_code=30007, trace_id=uuid.uuid4()
    )
    again = await g.attempt_again(t, first.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert again.outcome is Outcome.FAILED and len(provider.requests) == 1


async def test_an_unknown_message_or_status_is_ignored(make_tenant):
    t = await make_tenant()
    g, _, message_id = await sent_message(t)
    unknown = await g.record_receipt(
        t, provider_message_id="SMnope", provider_status="delivered", trace_id=uuid.uuid4()
    )
    odd_status = await g.record_receipt(
        t, provider_message_id="SMrx1", provider_status="receiving", trace_id=uuid.uuid4()
    )
    nothing = await g.record_receipt(t, provider_status="delivered", trace_id=uuid.uuid4())
    assert [r.recorded for r in (unknown, odd_status, nothing)] == [False, False, False]
    assert await event_pairs(t, message_id) == [(1, "sending"), (1, "sent")]


async def test_a_receipt_can_find_a_message_whose_send_never_got_an_answer(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    g = gateway(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None)))
    stuck = await g.send(t, request(lead))
    assert stuck.status is S.SENDING
    # The status callback carries our message id, so the receipt resolves it even though we never stored the SID.
    receipt = await g.record_receipt(
        t, message_id=stuck.message_id, provider_message_id="SMlate", provider_status="delivered", trace_id=uuid.uuid4()
    )
    assert (receipt.recorded, receipt.status) == (True, S.DELIVERED)
    assert (await events(t, stuck.message_id))[-1].provider_message_id == "SMlate"


async def test_a_delivery_receipt_outranks_an_earlier_no_receipt_failure(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    clock = Clock()
    g = gateway(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None)), clock=clock)
    stuck = await g.send(t, request(lead))
    clock.now = datetime.now(UTC) + timedelta(days=1)
    assert await g.expire_stuck(t, stuck.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    receipt = await g.record_receipt(t, message_id=stuck.message_id, provider_status="delivered", trace_id=uuid.uuid4())
    assert receipt.status is S.DELIVERED


async def test_a_receipt_of_another_tenant_cannot_touch_this_one(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    ga, _, message_id = await sent_message(a)
    gb = gateway()
    receipt = await gb.record_receipt(
        b, provider_message_id="SMrx1", provider_status="delivered", trace_id=uuid.uuid4()
    )
    by_id = await gb.record_receipt(b, message_id=message_id, provider_status="delivered", trace_id=uuid.uuid4())
    assert (receipt.recorded, by_id.recorded) == (False, False)
    assert await event_pairs(a, message_id) == [(1, "sending"), (1, "sent")]


async def test_a_late_failure_for_an_old_attempt_does_not_hide_the_new_one(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    g = gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429), accepted("SMrx2")))
    first = await g.send(t, request(lead))
    await g.attempt_again(t, first.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    receipt = await g.record_receipt(t, message_id=first.message_id, provider_status="sent", trace_id=uuid.uuid4())
    assert receipt.status is S.SENT  # attempt 2 is the current one and it is sent
