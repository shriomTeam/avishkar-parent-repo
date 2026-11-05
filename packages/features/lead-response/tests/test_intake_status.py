"""The delivery-receipt route: what Twilio tells us about a text we sent."""

import logging
import uuid

import pytest
from lr_gateway import FakeProvider, accepted, audit_rows, consents, event_pairs, events, gateway, make_lead, request
from lr_intake import (
    LEAD_NUMBER,
    OUR_NUMBER,
    PATH,
    PUBLIC,
    TOKEN,
    Counter,
    Intake,
    count,
    receipt_pairs,
    sid,
)

from clinic_db.models.lead_response import ConsentRecord, MessageEvent
from clinic_lead_response.gateway.service import Gateway
from clinic_lead_response.gateway.status import current_status
from clinic_lead_response.intake.parse import MAX_BODY_BYTES

EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
PROVIDER_SID = sid(7)

# set_config, the message found by Twilio's sid, its events, the new event, its events again to report the status.
RECEIPT_STATEMENTS = 5
# A receipt for a message we do not have stops after looking.
UNKNOWN_STATEMENTS = 2
# An opt-out error adds: the contact of the message, the consent lookup, the revocation and its audit row.
OPT_OUT_STATEMENTS = 9


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def sent(tenant, provider_sid: str = PROVIDER_SID, *, lead=None):
    """A text we sent and Twilio accepted: events sending and sent, the sent one carrying Twilio's sid."""
    lead = lead or await make_lead(tenant)
    result = await gateway(FakeProvider(accepted(provider_sid))).send(tenant, request(lead))
    return lead, result.message_id


async def statuses(tenant, message_id) -> list[str]:
    return [status for _, status in await event_pairs(tenant, message_id)]


async def current(tenant, message_id):
    return current_status(await event_pairs(tenant, message_id))


async def test_a_delivered_receipt_is_recorded_and_answered_with_200(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    assert response.status_code == 200 and response.text == EMPTY
    assert response.headers["content-type"].startswith("text/xml")
    assert await statuses(tenant, message) == ["sending", "sent", "delivered"]
    delivered = [e for e in await events(tenant, message) if e.status == "delivered"][0]
    assert delivered.attempt == 1 and delivered.provider_message_id == PROVIDER_SID and delivered.trace_id is not None


@pytest.mark.parametrize(
    ("word", "added"),
    [
        ("queued", "queued"),
        ("delivered", "delivered"),
        ("read", "delivered"),
        ("undelivered", "failed"),
        ("failed", "failed"),
        ("sending", None),  # we already have a sending event
        ("sent", None),  # and a sent one
    ],
)
async def test_each_twilio_status_word_becomes_our_status(intake, make_tenant, word, added):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    assert (await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, word))).status_code == 200
    expected = ["sending", "sent"] + ([added] if added else [])
    assert sorted(await statuses(tenant, message)) == sorted(expected)


@pytest.mark.parametrize("word", ["receiving", "canceled", "accepted_by_carrier", "whatever"])
async def test_a_status_word_we_do_not_know_is_ignored_with_200(intake, make_tenant, word):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, word))
    assert response.status_code == 200
    assert await statuses(tenant, message) == ["sending", "sent"]


async def test_the_same_receipt_twice_is_one_event(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    for _ in range(3):
        assert (await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))).status_code == 200
    assert (await statuses(tenant, message)).count("delivered") == 1


async def test_receipts_in_the_wrong_order_still_end_delivered(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "sent"))
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "queued"))
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "failed", ErrorCode="30003"))
    assert str(await current(tenant, message)) == "delivered"


async def test_a_receipt_that_arrives_before_our_own_record_of_the_send_is_matched_by_the_message_id(
    intake, make_tenant
):
    """The callback can outrun the second step of a send. The id in the callback URL (m) is what finds the message."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    answers = []

    async def early_receipt(provider_request):
        # Twilio is already calling back while our send is still waiting for its answer.
        answers.append(
            await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"), m=provider_request.message_id)
        )

    result = await gateway(FakeProvider(accepted(PROVIDER_SID), hook=early_receipt)).send(tenant, request(lead))
    assert answers[0].status_code == 200
    assert sorted(await statuses(tenant, result.message_id)) == ["delivered", "sending", "sent"]
    assert str(await current(tenant, result.message_id)) == "delivered"


async def test_without_the_message_id_an_early_receipt_cannot_be_matched(intake, make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    answers = []

    async def early_receipt(provider_request):
        answers.append(await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered")))

    result = await gateway(FakeProvider(accepted(PROVIDER_SID), hook=early_receipt)).send(tenant, request(lead))
    assert answers[0].status_code == 200  # answered, but there was nothing to attach it to yet
    assert "delivered" not in await statuses(tenant, result.message_id)


async def test_the_twilio_sid_wins_over_the_id_in_the_url(intake, make_tenant):
    tenant = await make_tenant()
    lead, first = await sent(tenant, sid(1))
    _, second = await sent(tenant, sid(2), lead=lead)
    await intake.post_status(tenant, receipt_pairs(sid(1), "delivered"), m=second)
    assert "delivered" in await statuses(tenant, first)
    assert "delivered" not in await statuses(tenant, second)


@pytest.mark.parametrize("bad", ["not-a-uuid", "", str(uuid.uuid4()).upper(), "{" + str(uuid.uuid4()) + "}"])
async def test_an_id_in_the_url_that_is_not_ours_is_ignored(intake, make_tenant, bad):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"), m=bad)
    assert response.status_code == 200
    assert "delivered" in await statuses(tenant, message)


async def test_a_receipt_for_a_message_we_do_not_have_is_answered_and_forgotten(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    response = await intake.post_status(tenant, receipt_pairs(sid(99), "delivered"), m=uuid.uuid4())
    assert response.status_code == 200 and response.text == EMPTY
    assert await statuses(tenant, message) == ["sending", "sent"]


# --- opt-out reported by the carrier ---------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["failed", "undelivered"])
async def test_error_21610_means_the_contact_opted_out_and_is_recorded(intake, make_tenant, word):
    tenant = await make_tenant()
    lead, message = await sent(tenant)
    response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, word, ErrorCode="21610"))
    assert response.status_code == 200
    failed = [e for e in await events(tenant, message) if e.status == "failed"]
    assert [e.reason_code for e in failed] == ["21610"]
    assert [(c.granted, c.source) for c in await consents(tenant, lead.contact)] == [(False, "stop")]
    (row,) = await audit_rows(tenant, "lead_response.consent.changed")
    assert row.details == {"channel": "sms", "granted": False, "source": "stop"}


async def test_a_second_21610_does_not_record_a_second_revocation(intake, make_tenant):
    tenant = await make_tenant()
    lead, _ = await sent(tenant)
    for _ in range(2):
        await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "failed", ErrorCode="21610"))
    assert len(await consents(tenant, lead.contact)) == 1


async def test_another_error_code_fails_the_message_without_opting_anyone_out(intake, make_tenant):
    tenant = await make_tenant()
    lead, message = await sent(tenant)
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "undelivered", ErrorCode="30003"))
    failed = [e for e in await events(tenant, message) if e.status == "failed"]
    assert [e.reason_code for e in failed] == ["30003"]
    assert await consents(tenant, lead.contact) == []


async def test_error_21610_on_a_delivered_receipt_is_not_a_failure(intake, make_tenant):
    tenant = await make_tenant()
    lead, _ = await sent(tenant)
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered", ErrorCode="21610"))
    assert await consents(tenant, lead.contact) == []


async def test_an_error_code_we_cannot_read_still_records_the_failure(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    assert (await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "failed", ErrorCode="abc"))).status_code == 200
    failed = [e for e in await events(tenant, message) if e.status == "failed"]
    assert [e.reason_code for e in failed] == [None]


# --- who may call, and what they may send -------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["no-header", "empty-header", "junk", "wrong-token", "other-path"])
async def test_a_bad_signature_is_403_with_no_database_access(intake, make_tenant, case):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    kwargs = {
        "no-header": {"sign": False},
        "empty-header": {"sign": False, "headers": {"x-twilio-signature": ""}},
        "junk": {"sign": False, "headers": {"x-twilio-signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAA="}},
        "wrong-token": {"token": TOKEN + "x"},
        "other-path": {"signed_path": f"{PATH}/status/sms/{uuid.uuid4()}"},
    }[case]
    with Counter() as statements:
        response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"), **kwargs)
    assert response.status_code == 403 and response.content == b"" and statements == []
    assert await statuses(tenant, message) == ["sending", "sent"]


async def test_the_id_in_the_url_is_part_of_what_is_signed(intake, make_tenant):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    other = uuid.uuid4()
    response = await intake.post_status(
        tenant, receipt_pairs(PROVIDER_SID, "delivered"), m=message, signed_query=f"m={other}"
    )
    assert response.status_code == 403
    unsigned_query = await intake.post_status(
        tenant, receipt_pairs(PROVIDER_SID, "delivered"), m=message, signed_query=""
    )
    assert unsigned_query.status_code == 403
    assert await statuses(tenant, message) == ["sending", "sent"]


@pytest.mark.parametrize("missing", ["base", "token"])
async def test_an_unconfigured_server_answers_503_and_reads_nothing(monkeypatch, make_tenant, missing):
    tenant = await make_tenant()
    intake = Intake(monkeypatch, base="" if missing == "base" else PUBLIC, token="" if missing == "token" else TOKEN)
    with Counter() as statements:
        response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID))
    assert response.status_code == 503 and statements == []


async def test_a_receipt_does_not_need_the_sending_number(monkeypatch, make_tenant):
    """Only inbound texts are matched against our number. A receipt works with no TWILIO_FROM_NUMBER set."""
    tenant = await make_tenant()
    _, message = await sent(tenant)
    intake = Intake(monkeypatch, number="")
    assert (await intake.post_status(tenant, receipt_pairs(PROVIDER_SID))).status_code == 200
    assert "delivered" in await statuses(tenant, message)


@pytest.mark.parametrize("channel", ["mms", "whatsapp", "SMS"])
async def test_another_channel_is_404(intake, make_tenant, channel):
    tenant = await make_tenant()
    assert (await intake.post_status(tenant, receipt_pairs(PROVIDER_SID), channel=channel)).status_code == 404


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", ""])
async def test_only_a_form_post_is_read(intake, make_tenant, content_type):
    tenant = await make_tenant()
    response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID), content_type=content_type)
    assert response.status_code == 400


async def test_a_body_over_the_limit_is_413_before_anything_is_read(intake, make_tenant):
    tenant = await make_tenant()
    with Counter() as statements:
        response = await intake.post_status(tenant, [], raw=b"a=" + b"x" * MAX_BODY_BYTES)
    assert response.status_code == 413 and statements == []


@pytest.mark.parametrize(
    "pairs",
    [
        receipt_pairs("nope"),
        receipt_pairs(PROVIDER_SID, MessageStatus=None),
        receipt_pairs(PROVIDER_SID, MessageSid=None),
        receipt_pairs(PROVIDER_SID, "sent!"),
        receipt_pairs(PROVIDER_SID) + [("MessageStatus", "again")],
        [],
    ],
    ids=["bad-sid", "no-status", "no-sid", "bad-status", "repeated-status", "empty"],
)
async def test_a_signed_receipt_we_cannot_read_is_400(intake, make_tenant, pairs):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    response = await intake.post_status(tenant, pairs)
    assert response.status_code == 400 and response.content == b""
    assert await statuses(tenant, message) == ["sending", "sent"]


@pytest.mark.parametrize("tenant", ["not-a-uuid", "AAAAAAAA-1111-1111-1111-111111111111"])
async def test_a_tenant_that_is_not_written_our_way_gets_200_and_nothing_happens(intake, tenant):
    with Counter() as statements:
        response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID))
    assert response.status_code == 200 and response.text == EMPTY and statements == []


async def test_an_unknown_tenant_gets_200(intake):
    assert (await intake.post_status(uuid.uuid4(), receipt_pairs(PROVIDER_SID))).status_code == 200


async def test_a_get_is_not_allowed(intake, make_tenant):
    tenant = await make_tenant()
    async with intake.client() as client:
        assert (await client.get(f"{PATH}/status/sms/{tenant}")).status_code == 405


# --- failures --------------------------------------------------------------------------------------------------------


async def test_a_failure_while_recording_gives_500_and_the_retry_records_it(intake, make_tenant, monkeypatch):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    real = Gateway.record_receipt
    calls = []

    async def fail_once(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(Gateway, "record_receipt", fail_once)
    failed = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"), raise_app_exceptions=False)
    assert failed.status_code == 500 and failed.content == b""
    assert "delivered" not in await statuses(tenant, message)
    retried = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    assert retried.status_code == 200 and "delivered" in await statuses(tenant, message)


# --- other clinics ---------------------------------------------------------------------------------------------------


async def test_a_receipt_sent_to_one_clinic_never_touches_another_clinics_message(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    _, message_b = await sent(b, sid(5))
    # Correctly signed for clinic A's address, but naming clinic B's Twilio sid.
    response = await intake.post_status(a, receipt_pairs(sid(5), "delivered"))
    assert response.status_code == 200
    assert await statuses(b, message_b) == ["sending", "sent"]
    assert await count(a, MessageEvent) == 0


async def test_clinic_bs_message_id_in_clinic_as_url_finds_nothing(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    _, message_b = await sent(b, sid(5))
    response = await intake.post_status(a, receipt_pairs(sid(6), "delivered"), m=message_b)
    assert response.status_code == 200
    assert await statuses(b, message_b) == ["sending", "sent"]
    assert await count(a, MessageEvent) == 0 and await count(a, ConsentRecord) == 0


async def test_a_21610_for_one_clinic_does_not_opt_out_the_same_number_in_another(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a, _ = await sent(a, sid(1))
    lead_b, _ = await sent(b, sid(2))
    await intake.post_status(a, receipt_pairs(sid(1), "failed", ErrorCode="21610"))
    assert [(c.granted, c.source) for c in await consents(a, lead_a.contact)] == [(False, "stop")]
    assert await consents(b, lead_b.contact) == []


async def test_a_receipt_reaches_the_clinic_in_its_url_and_only_that_one(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    _, message_a = await sent(a, sid(1))
    _, message_b = await sent(b, sid(2))
    await intake.post_status(a, receipt_pairs(sid(1), "delivered"))
    await intake.post_status(b, receipt_pairs(sid(2), "delivered"))
    assert "delivered" in await statuses(a, message_a) and "delivered" in await statuses(b, message_b)


# --- cost and privacy ------------------------------------------------------------------------------------------------


async def test_a_receipt_costs_few_statements(intake, make_tenant):
    tenant = await make_tenant()
    await sent(tenant)
    with Counter() as statements:
        response = await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    print(f"\nreceipt: {len(statements)} statements")
    assert response.status_code == 200 and len(statements) <= RECEIPT_STATEMENTS


async def test_a_receipt_for_a_message_we_do_not_have_costs_two_statements(intake, make_tenant):
    tenant = await make_tenant()
    with Counter() as statements:
        await intake.post_status(tenant, receipt_pairs(sid(99), "delivered"))
    assert len(statements) <= UNKNOWN_STATEMENTS


async def test_an_opt_out_receipt_costs_a_few_more(intake, make_tenant):
    tenant = await make_tenant()
    await sent(tenant)
    with Counter() as statements:
        await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "failed", ErrorCode="21610"))
    print(f"\nopt-out receipt: {len(statements)} statements")
    assert len(statements) <= OPT_OUT_STATEMENTS


async def test_a_repeated_receipt_costs_no_more(intake, make_tenant):
    tenant = await make_tenant()
    await sent(tenant)
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    with Counter() as statements:
        await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    assert len(statements) <= RECEIPT_STATEMENTS


async def test_the_numbers_in_a_receipt_never_reach_a_log_line(intake, make_tenant, caplog):
    tenant = await make_tenant()
    await sent(tenant)
    caplog.set_level(logging.DEBUG, logger="lead_response")
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "failed", ErrorCode="21610"))
    await intake.post_status(tenant, receipt_pairs("bad"))
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID), sign=False)
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "receipt" in text
    for secret in (LEAD_NUMBER, LEAD_NUMBER[1:], OUR_NUMBER, OUR_NUMBER[1:]):
        assert secret not in text


async def test_a_logged_receipt_carries_the_tenant_and_a_trace_id(intake, make_tenant, caplog):
    tenant = await make_tenant()
    _, message = await sent(tenant)
    caplog.set_level(logging.INFO, logger="lead_response")
    await intake.post_status(tenant, receipt_pairs(PROVIDER_SID, "delivered"))
    line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("receipt ")]
    assert len(line) == 1
    assert f"tenant_id={tenant}" in line[0] and "trace_id=" in line[0] and f"message_id={message}" in line[0]
