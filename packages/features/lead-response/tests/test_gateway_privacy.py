"""Nothing personal reaches the logs, on any path the gateway takes."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from lr_gateway import (
    BODY,
    NIGHT_UTC,
    PHONE,
    Clock,
    FakeProvider,
    RaisingProvider,
    accepted,
    failure,
    gateway,
    make_lead,
    request,
    set_settings,
)

from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.service import Gateway
from clinic_lead_response.gateway.types import Lane, Purpose

SECRETS = [BODY, "Zebra", PHONE, PHONE[1:], PHONE[-10:], "4155550142", "tokentokentoken"]


def assert_clean(text):
    for secret in SECRETS:
        assert secret not in text, secret


async def test_no_path_logs_the_body_or_a_full_phone_number(make_tenant, caplog):
    t = await make_tenant()
    consenting = await make_lead(t, consent=(True, "start"))
    opted_out = await make_lead(t, phone="+14155550143", consent=(False, "stop"))
    trace = uuid.uuid4()
    with caplog.at_level(logging.DEBUG):
        ok = gateway(FakeProvider(accepted("SMp1")))
        await ok.send(t, request(consenting, trace=trace))  # sent
        await ok.send(t, request(opted_out))  # blocked
        await set_settings(t, quiet_hours={"start": "21:00", "end": "08:00"})
        await gateway(clock=Clock(NIGHT_UTC)).send(
            t, request(consenting, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP)
        )  # deferred
        retry = await gateway(FakeProvider(failure(ErrorKind.RETRYABLE, "20429", 429))).send(t, request(consenting))
        await gateway(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None))).send(
            t, request(consenting)
        )  # uncertain
        await gateway(FakeProvider(failure(ErrorKind.OPT_OUT, "21610"))).send(t, request(consenting))  # opt-out
        await Gateway(RaisingProvider(), ok._numbers, clock=Clock()).send(t, request(consenting))  # adapter bug
        await ok.attempt_again(t, retry.message_id, lane=Lane.LIVE, trace_id=trace)
        await ok.record_receipt(t, provider_message_id="SMp1", provider_status="delivered", trace_id=trace)
        await ok.handle_inbound_keyword(
            t, contact_id=consenting.contact, text="STOP", inbound_message_id=None, trace_id=trace
        )
    assert caplog.records, "the gateway should log what it does"
    assert_clean(caplog.text)


async def test_the_log_lines_carry_tenant_trace_and_outcome_and_a_masked_number(make_tenant, caplog):
    t = await make_tenant()
    lead = await make_lead(t)
    trace = uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="lead_response.gateway"):
        await gateway().send(t, request(lead, trace=trace))
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("send ")]
    for expected in (
        f"tenant_id={t}",
        f"trace_id={trace}",
        "outcome=sent",
        "lane=live",
        "purpose=ack",
        "to_masked=***42",
    ):
        assert expected in line, expected


async def test_a_blocked_send_logs_the_reason_but_not_who(make_tenant, caplog):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    with caplog.at_level(logging.INFO, logger="lead_response.gateway"):
        await gateway().send(t, request(lead))
    text = caplog.text
    assert "outcome=blocked" in text and "reason=opted_out" in text
    assert_clean(text)


async def test_a_stuck_message_expiry_is_logged_without_personal_data(make_tenant, caplog):
    t = await make_tenant()
    lead = await make_lead(t)
    clock = Clock()
    g = gateway(FakeProvider(failure(ErrorKind.AMBIGUOUS, "timeout", None)), clock=clock)
    stuck = await g.send(t, request(lead))
    clock.now = datetime.now(UTC) + timedelta(days=1)
    with caplog.at_level(logging.DEBUG):
        await g.expire_stuck(t, stuck.message_id, lane=Lane.LIVE, trace_id=uuid.uuid4())
    assert "stuck_expired" in caplog.text
    assert_clean(caplog.text)
