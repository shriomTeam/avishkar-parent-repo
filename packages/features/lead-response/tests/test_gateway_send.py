"""Gateway.send, attempt_again and expire_stuck against the real database (the provider is always a fake)."""

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from lr_gateway import (
    BODY,
    DAYTIME,
    FROM,
    NIGHT_UTC,
    PHONE,
    Clock,
    FakeProvider,
    RaisingProvider,
    accepted,
    event_pairs,
    events,
    failure,
    gateway,
    make_lead,
    messages,
    request,
    set_settings,
)
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Conversation
from clinic_lead_response.gateway import store
from clinic_lead_response.gateway.provider import NotConfiguredProvider
from clinic_lead_response.gateway.retry import STUCK_AFTER_SECONDS, ErrorKind
from clinic_lead_response.gateway.service import ContactNotFound, ConversationNotFound, Gateway, MessageNotFound
from clinic_lead_response.gateway.types import FailReason, Lane, Outcome, Purpose
from clinic_lead_response.gateway.types import MessageStatus as S

# --- the happy path ------------------------------------------------------------------------------------------------


async def test_an_ack_is_sent_once_and_recorded(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(accepted("SM42"))
    req = request(lead, key="ack:inbound-1")
    result = await gateway(provider).send(t, req)

    assert (result.outcome, result.status, result.attempt) == (Outcome.SENT, S.SENT, 1)
    (call,) = provider.requests
    assert (call.to, call.from_number, call.body, call.attempt) == (PHONE, FROM, BODY, 1)
    assert call.message_id == result.message_id and call.trace_id == req.trace_id

    (message,) = await messages(t)
    assert (message.direction, message.channel, message.sender_kind, message.provider) == (
        "outbound",
        "sms",
        "ack",
        "fake",
    )
    assert (message.body, message.idempotency_key, message.trace_id) == (BODY, "ack:inbound-1", req.trace_id)
    evs = await events(t, message.id)
    assert [(e.attempt, e.status) for e in evs] == [(1, "sending"), (1, "sent")]
    assert evs[1].provider_message_id == "SM42"


async def test_the_conversation_remembers_when_we_last_wrote(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    await gateway(clock=Clock(DAYTIME)).send(t, request(lead))
    async with tenant_session(t) as s:
        assert (
            await s.scalar(select(Conversation.last_outbound_at).where(Conversation.id == lead.conversation)) == DAYTIME
        )


@pytest.mark.parametrize(
    ("purpose", "kind"),
    [(Purpose.ACK, "ack"), (Purpose.HOLDING, "holding"), (Purpose.HELP, "help"), (Purpose.STAFF_REPLY, "staff")],
)
async def test_each_reply_purpose_is_stored_with_its_own_sender_kind(make_tenant, purpose, kind):
    t = await make_tenant()
    lead = await make_lead(t)
    await gateway().send(t, request(lead, purpose=purpose))
    assert (await messages(t))[0].sender_kind == kind


async def test_a_follow_up_with_an_explicit_grant_goes_out_in_daytime(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"))
    result = await gateway().send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    assert result.outcome is Outcome.SENT and (await messages(t))[0].sender_kind == "followup"


async def test_the_status_callback_is_built_from_tenant_and_message(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider()
    g = gateway(
        provider, status_callback=lambda tenant, message: f"https://example.test/in/sms/{tenant}/status?m={message}"
    )
    result = await g.send(t, request(lead))
    assert provider.requests[0].status_callback_url == f"https://example.test/in/sms/{t}/status?m={result.message_id}"


async def test_every_row_carries_the_trace_id(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    req = request(lead)
    result = await gateway().send(t, req)
    assert (await messages(t))[0].trace_id == req.trace_id
    assert {e.trace_id for e in await events(t, result.message_id)} == {req.trace_id}


# --- idempotency ---------------------------------------------------------------------------------------------------


async def test_the_same_key_twice_sends_once_and_returns_the_earlier_result(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider()
    g = gateway(provider)
    req = request(lead, key="ack:same")
    first = await g.send(t, req)
    second = await g.send(t, req)
    assert (second.outcome, second.message_id, second.status) == (Outcome.DUPLICATE, first.message_id, S.SENT)
    assert len(provider.requests) == 1 and len(await messages(t)) == 1


async def test_a_repeat_of_a_message_still_in_flight_says_so(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    g = gateway(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None)))
    req = request(lead, key="ack:flight")
    assert (await g.send(t, req)).outcome is Outcome.UNCERTAIN
    again = await g.send(t, req)
    assert (again.outcome, again.status) == (Outcome.DUPLICATE, S.SENDING)


async def test_the_same_key_in_another_tenant_is_a_different_message(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    la, lb = await make_lead(a), await make_lead(b)
    provider = FakeProvider()
    g = gateway(provider)
    assert (await g.send(a, request(la, key="ack:x"))).outcome is Outcome.SENT
    assert (await g.send(b, request(lb, key="ack:x"))).outcome is Outcome.SENT
    assert len(provider.requests) == 2


async def test_two_sends_at_the_same_moment_text_the_lead_once(make_tenant, monkeypatch):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider()
    g = gateway(provider)
    # Hold both requests after their "already sent?" check and before either inserts, so both see nothing and the
    # loser can only be stopped by the unique (tenant_id, idempotency_key).
    barrier = asyncio.Barrier(2)
    read = store.find_message_by_key
    lookups = 0

    async def synchronised(session, key):
        nonlocal lookups
        found = await read(session, key)
        lookups += 1
        if lookups <= 2:  # only the two first lookups wait; the loser looks again later and must not wait for anyone
            await barrier.wait()
        return found

    monkeypatch.setattr(store, "find_message_by_key", synchronised)
    req = request(lead, key="ack:race")
    first, second = await asyncio.gather(g.send(t, req), g.send(t, req))
    assert sorted(r.outcome for r in (first, second)) == [Outcome.DUPLICATE, Outcome.SENT]
    assert len(provider.requests) == 1 and len(await messages(t)) == 1


# --- policy outcomes -----------------------------------------------------------------------------------------------


async def test_an_opted_out_contact_is_blocked_and_the_block_is_recorded(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    provider = FakeProvider()
    result = await gateway(provider).send(t, request(lead))
    assert (result.outcome, result.status, result.reason) == (Outcome.BLOCKED, S.BLOCKED, "opted_out")
    assert provider.requests == []
    assert await event_pairs(t, result.message_id) == [(1, "blocked")]
    assert (await events(t, result.message_id))[0].reason_code == "opted_out"


async def test_a_follow_up_without_an_explicit_grant_is_blocked(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "first_inbound"))
    result = await gateway().send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    assert (result.outcome, result.reason) == (Outcome.BLOCKED, "no_consent")


async def test_a_lead_with_no_phone_number_is_blocked(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, phone=None)
    result = await gateway().send(t, request(lead))
    assert (result.outcome, result.reason) == (Outcome.BLOCKED, "no_phone")


async def test_an_ack_in_the_middle_of_the_night_still_goes_out(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    await set_settings(t, quiet_hours={"start": "21:00", "end": "08:00"})
    result = await gateway(clock=Clock(NIGHT_UTC)).send(t, request(lead))
    assert result.outcome is Outcome.SENT


async def test_a_follow_up_in_quiet_hours_is_deferred_and_nothing_is_written(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"))
    await set_settings(t, quiet_hours={"start": "21:00", "end": "08:00"})
    provider = FakeProvider()
    result = await gateway(provider, clock=Clock(NIGHT_UTC)).send(
        t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP)
    )
    assert result.outcome is Outcome.DEFERRED and result.until == datetime(
        2026, 5, 2, 12, 0, tzinfo=UTC
    )  # 08:00 New York
    assert provider.requests == [] and await messages(t) == []


async def test_the_clinics_own_time_zone_decides_whether_it_is_quiet(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"), timezone="America/Los_Angeles")
    await set_settings(t, quiet_hours={"start": "21:00", "end": "08:00"})
    # 03:04 UTC is 23:04 in New York but 20:04 in Los Angeles, which is not quiet there.
    result = await gateway(clock=Clock(NIGHT_UTC)).send(
        t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP)
    )
    assert result.outcome is Outcome.SENT


async def test_an_unrecognised_time_zone_blocks_follow_ups_but_not_replies(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"), timezone="Mars/Olympus")
    g = gateway()
    follow_up = await g.send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    ack = await g.send(t, request(lead))
    assert (follow_up.outcome, follow_up.reason) == (Outcome.BLOCKED, "bad_timezone")
    assert ack.outcome is Outcome.SENT


async def test_no_number_to_send_from_is_a_recorded_failure(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider()
    result = await gateway(provider, number=None).send(t, request(lead))
    assert (result.outcome, result.reason) == (Outcome.FAILED, FailReason.NO_FROM_NUMBER)
    assert provider.requests == [] and await event_pairs(t, result.message_id) == [(1, "failed")]


# --- provider outcomes ---------------------------------------------------------------------------------------------


async def test_a_retryable_error_says_when_to_try_again(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429))).send(t, request(lead))
    assert (result.outcome, result.retry_after_seconds, result.attempt) == (Outcome.RETRY, 3.0, 1)
    assert await event_pairs(t, result.message_id) == [(1, "sending"), (1, "failed")]
    assert (await events(t, result.message_id))[1].reason_code == "20429"


async def test_the_provider_retry_after_wins_when_it_is_longer(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429, retry_after=30))).send(
        t, request(lead)
    )
    assert result.retry_after_seconds == 30.0


async def test_the_follow_up_lane_waits_longer_before_a_retry(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"))
    result = await gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429))).send(
        t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP)
    )
    assert result.retry_after_seconds == 60.0


@pytest.mark.parametrize(
    ("kind", "code", "reason"),
    [
        (ErrorKind.INVALID_NUMBER, "21211", "invalid_number"),
        (ErrorKind.PERMANENT, "21408", "permanent"),
        (ErrorKind.CONFIG, "20003", "config"),
    ],
)
async def test_permanent_errors_fail_without_a_retry(make_tenant, kind, code, reason):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await gateway(FakeProvider(failure(kind, code))).send(t, request(lead))
    assert (result.outcome, result.reason, result.provider_error_code) == (Outcome.FAILED, reason, code)
    assert result.retry_after_seconds is None


async def test_an_opt_out_error_revokes_consent_and_audits_it_without_values(make_tenant):
    from lr_gateway import audit_rows, consents

    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "first_inbound"))
    result = await gateway(FakeProvider(failure(ErrorKind.OPT_OUT, "21610"))).send(t, request(lead))
    assert (result.outcome, result.reason) == (Outcome.FAILED, "opt_out")
    newest = (await consents(t, lead.contact))[-1]
    assert (newest.granted, newest.source, newest.evidence) == (False, "stop", {"provider_error_code": "21610"})
    (audit,) = await audit_rows(t, "lead_response.consent.changed")
    assert audit.details == {"channel": "sms", "granted": False, "source": "stop"} and audit.actor_type == "system"
    # and the next message is stopped by policy, before any provider call
    provider = FakeProvider()
    assert (await gateway(provider).send(t, request(lead))).reason == "opted_out" and provider.requests == []


async def test_an_ambiguous_error_leaves_the_message_sending_and_never_retries_itself(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None))
    g = gateway(provider)
    result = await g.send(t, request(lead))
    assert (result.outcome, result.status) == (Outcome.UNCERTAIN, S.SENDING)
    assert await event_pairs(t, result.message_id) == [(1, "sending")]
    again = await g.attempt_again(t, result.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert again.outcome is Outcome.UNCERTAIN and len(provider.requests) == 1  # no second call


async def test_an_adapter_that_raises_is_treated_as_uncertain_not_propagated(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await Gateway(RaisingProvider(), gateway().__dict__["_numbers"], clock=Clock()).send(t, request(lead))
    assert result.outcome is Outcome.UNCERTAIN


async def test_without_twilio_set_up_every_send_fails_loudly_and_is_recorded(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await Gateway(NotConfiguredProvider(), gateway().__dict__["_numbers"], clock=Clock()).send(
        t, request(lead)
    )
    assert (result.outcome, result.reason, result.provider_error_code) == (
        Outcome.FAILED,
        "config",
        "provider_not_configured",
    )
    assert (await events(t, result.message_id))[-1].reason_code == "provider_not_configured"


@pytest.mark.parametrize("kind", list(ErrorKind))
async def test_send_returns_a_result_for_every_kind_of_provider_error_and_never_raises(make_tenant, kind):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await gateway(FakeProvider(failure(kind, "x"))).send(t, request(lead))
    assert isinstance(result.outcome, Outcome) and result.outcome is not Outcome.SENT


# --- retrying ------------------------------------------------------------------------------------------------------


async def test_a_retry_after_a_retryable_error_goes_through_as_attempt_two(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429), accepted("SM2"))
    g = gateway(provider)
    first = await g.send(t, request(lead))
    second = await g.attempt_again(t, first.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert (second.outcome, second.attempt) == (Outcome.SENT, 2)
    assert await event_pairs(t, first.message_id) == [(1, "sending"), (1, "failed"), (2, "sending"), (2, "sent")]
    assert [r.attempt for r in provider.requests] == [1, 2]


async def test_after_three_retries_the_gateway_gives_up(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    g = gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429)))
    result = await g.send(t, request(lead))
    delays = [result.retry_after_seconds]
    for _ in range(3):
        result = await g.attempt_again(t, result.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
        delays.append(result.retry_after_seconds)
    assert delays == [3.0, 15.0, 45.0, None]
    assert (result.outcome, result.reason, result.attempt) == (Outcome.FAILED, FailReason.RETRIES_EXHAUSTED, 4)


async def test_a_retry_never_resends_a_message_that_was_sent_or_delivered(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider()
    g = gateway(provider)
    sent = await g.send(t, request(lead))
    again = await g.attempt_again(t, sent.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert (again.outcome, again.status) == (Outcome.DUPLICATE, S.SENT) and len(provider.requests) == 1


async def test_a_retry_checks_consent_again_so_a_stop_in_between_wins(make_tenant):
    from lr_gateway import consents  # noqa: F401  (kept next to the other helpers)

    t = await make_tenant()
    lead = await make_lead(t)
    provider = FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429), accepted())
    g = gateway(provider)
    first = await g.send(t, request(lead))
    async with tenant_session(t) as s:
        await store.add_consent(s, contact_id=lead.contact, channel="sms", granted=False, source="stop", trace_id=None)
    second = await g.attempt_again(t, first.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert (second.outcome, second.reason) == (Outcome.BLOCKED, "opted_out") and len(provider.requests) == 1


async def test_a_retry_of_an_unknown_message_is_a_caller_bug(make_tenant):
    t = await make_tenant()
    with pytest.raises(MessageNotFound):
        await gateway().attempt_again(t, uuid.uuid4(), lane=Lane.LIVE, trace_id=uuid.uuid4())


# --- stuck messages and no_receipt ---------------------------------------------------------------------------------


async def stuck_message(t, lane=Lane.LIVE):
    lead = await make_lead(t, consent=(True, "start"))  # the bulk lane needs an explicit grant
    provider = FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None))
    clock = Clock()
    g = gateway(provider, clock=clock)
    result = await g.send(t, request(lead, lane=lane))
    return g, provider, clock, result


async def test_a_message_that_is_still_sending_after_its_deadline_is_surfaced_not_resent(make_tenant):
    t = await make_tenant()
    g, provider, clock, result = await stuck_message(t)
    trace = uuid.uuid4()
    assert not await g.expire_stuck(t, result.message_id, lane=Lane.LIVE, trace_id=trace)  # too soon
    clock.now = datetime.now(UTC) + timedelta(seconds=STUCK_AFTER_SECONDS[Lane.LIVE] + 5)
    assert await g.expire_stuck(t, result.message_id, lane=Lane.LIVE, trace_id=trace)
    assert not await g.expire_stuck(t, result.message_id, lane=Lane.LIVE, trace_id=trace)  # only once
    evs = await events(t, result.message_id)
    assert [(e.attempt, e.status, e.reason_code) for e in evs] == [(1, "sending", None), (1, "failed", "no_receipt")]
    assert len(provider.requests) == 1


@pytest.mark.parametrize("lane", list(Lane))
async def test_a_no_receipt_message_is_never_resent_in_any_lane(make_tenant, lane):
    t = await make_tenant()
    g, provider, clock, result = await stuck_message(t, lane)
    clock.now = datetime.now(UTC) + timedelta(days=1)
    assert await g.expire_stuck(t, result.message_id, lane=lane, trace_id=uuid.uuid4())
    again = await g.attempt_again(t, result.message_id, lane=lane, trace_id=uuid.uuid4())
    assert (again.outcome, again.reason) == (Outcome.FAILED, FailReason.NO_RECEIPT)
    assert len(provider.requests) == 1 and await event_pairs(t, result.message_id) == [(1, "sending"), (1, "failed")]


async def test_a_sent_message_is_never_expired(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    clock = Clock()
    g = gateway(clock=clock)
    result = await g.send(t, request(lead))
    clock.now = datetime.now(UTC) + timedelta(days=1)
    assert not await g.expire_stuck(t, result.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())


# --- who may send --------------------------------------------------------------------------------------------------


async def test_a_conversation_of_another_tenant_cannot_be_used(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a = await make_lead(a)
    provider = FakeProvider()
    with pytest.raises(ConversationNotFound):
        await gateway(provider).send(b, request(lead_a))
    assert provider.requests == [] and await messages(b) == [] and await messages(a) == []


async def test_a_conversation_that_does_not_exist_is_a_caller_bug(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    bad = request(lead)
    bad = type(bad)(uuid.uuid4(), bad.purpose, bad.body, bad.lane, bad.idempotency_key, bad.trace_id)
    with pytest.raises(ConversationNotFound):
        await gateway().send(t, bad)


@pytest.mark.parametrize("body", ["", "   ", "\n"])
async def test_an_empty_body_is_a_programmer_error(make_tenant, body):
    t = await make_tenant()
    lead = await make_lead(t)
    with pytest.raises(ValueError, match="body"):
        await gateway().send(t, request(lead, body=body))


@pytest.mark.parametrize("key", ["", "k" * 101])
async def test_a_bad_idempotency_key_is_a_programmer_error(make_tenant, key):
    t = await make_tenant()
    lead = await make_lead(t)
    with pytest.raises(ValueError, match="idempotency key"):
        await gateway().send(t, replace(request(lead), idempotency_key=key))


def test_contact_not_found_exists_for_the_keyword_handler():
    assert issubclass(ContactNotFound, LookupError)
