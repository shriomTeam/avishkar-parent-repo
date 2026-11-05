"""The inbound route: what each kind of request gets back, and what is written."""

import uuid

import pytest
from lr_intake import (
    BODY,
    LEAD_NUMBER,
    OUR_NUMBER,
    PATH,
    PUBLIC,
    SID,
    TOKEN,
    Counter,
    Intake,
    count,
    form_bytes,
    reference_signature,
    rows,
    sid,
    twilio_pairs,
)

from clinic_db.models.lead_response import ConsentRecord, Contact, Conversation, Job, Message
from clinic_lead_response.intake.parse import MAX_BODY_BYTES, parse_form

EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def nothing_stored(tenant) -> bool:
    return all([await count(tenant, m) == 0 for m in (Message, Contact, Conversation, Job, ConsentRecord)])


async def test_a_signed_text_is_stored_and_answered_with_an_empty_twiml(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    assert response.text == EMPTY
    (message,) = await rows(tenant, Message)
    assert (message.direction, message.channel, message.sender_kind, message.provider) == (
        "inbound",
        "sms",
        "contact",
        "twilio",
    )
    assert message.body == BODY
    assert message.provider_message_id == SID
    assert message.idempotency_key == f"in:{SID}"
    assert message.trace_id is not None and message.staff_id is None


@pytest.mark.parametrize("missing", ["base", "token", "number"])
async def test_an_unconfigured_server_answers_503_and_reads_nothing(monkeypatch, make_tenant, missing):
    tenant = await make_tenant()
    kwargs = {"base": "" if missing == "base" else PUBLIC, "token": "" if missing == "token" else TOKEN}
    intake = Intake(monkeypatch, number="" if missing == "number" else OUR_NUMBER, **kwargs)
    with Counter() as statements:
        response = await intake.post(tenant)
    assert response.status_code == 503 and response.content == b""
    assert statements == []
    assert await nothing_stored(tenant)


async def test_a_bad_base_address_switches_intake_off(monkeypatch, make_tenant):
    tenant = await make_tenant()
    response = await Intake(monkeypatch, base="https://api.example.test/features").post(tenant)
    assert response.status_code == 503


@pytest.mark.parametrize(
    "case",
    ["no-header", "wrong-token", "other-path", "empty-header", "tampered"],
)
async def test_a_bad_signature_is_403_with_no_database_access(intake, make_tenant, case):
    tenant = await make_tenant()
    other = f"{PATH}/in/sms/{uuid.uuid4()}"
    kwargs = {
        "no-header": {"sign": False},
        "wrong-token": {"token": TOKEN + "x"},
        "other-path": {"signed_path": other},
        "empty-header": {"sign": False, "headers": {"x-twilio-signature": ""}},
        "tampered": {"sign": False, "headers": {"x-twilio-signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAA="}},
    }[case]
    with Counter() as statements:
        response = await intake.post(tenant, **kwargs)
    assert response.status_code == 403 and response.content == b""
    assert statements == []
    assert await nothing_stored(tenant)


async def test_a_request_signed_for_one_tenant_is_refused_at_another(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    response = await intake.post(b, signed_path=f"{PATH}/in/sms/{a}")
    assert response.status_code == 403
    assert await nothing_stored(a) and await nothing_stored(b)


async def test_a_query_string_is_part_of_what_is_signed(intake, make_tenant):
    tenant = await make_tenant()
    assert (await intake.post(tenant, query="x=1")).status_code == 200
    path = f"{PATH}/in/sms/{tenant}"
    body = form_bytes(twilio_pairs(MessageSid=sid(2)))
    without_query = reference_signature(TOKEN, PUBLIC + path, parse_form(body))
    response = await intake.post(
        tenant, raw=body, query="x=1", sign=False, headers={"x-twilio-signature": without_query}
    )
    assert response.status_code == 403
    assert await count(tenant, Message) == 1


@pytest.mark.parametrize("channel", ["mms", "whatsapp", "email", "SMS"])
async def test_another_channel_is_404(intake, make_tenant, channel):
    tenant = await make_tenant()
    response = await intake.post(tenant, channel=channel)
    assert response.status_code == 404
    assert await nothing_stored(tenant)


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", ""])
async def test_only_a_form_post_is_read(intake, make_tenant, content_type):
    tenant = await make_tenant()
    response = await intake.post(tenant, content_type=content_type)
    assert response.status_code == 400
    assert await nothing_stored(tenant)


async def test_a_form_content_type_may_carry_a_charset(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant, content_type="application/x-www-form-urlencoded; charset=UTF-8")
    assert response.status_code == 200 and await count(tenant, Message) == 1


async def test_a_declared_size_over_the_limit_is_413_before_anything_is_read(intake, make_tenant):
    tenant = await make_tenant()
    big = b"Body=" + b"x" * MAX_BODY_BYTES
    with Counter() as statements:
        response = await intake.post(tenant, raw=big)
    assert response.status_code == 413 and statements == []


async def test_a_streamed_body_over_the_limit_is_413(intake, make_tenant):
    tenant = await make_tenant()

    async def chunks():
        for _ in range(40):
            yield b"a=" + b"x" * 1000 + b"&"

    async with intake.client() as client:
        response = await client.post(
            f"{PATH}/in/sms/{tenant}",
            content=chunks(),
            headers={"content-type": "application/x-www-form-urlencoded", "x-twilio-signature": "x"},
        )
    assert response.status_code == 413
    assert await nothing_stored(tenant)


async def test_a_body_just_under_the_limit_is_read(intake, make_tenant):
    tenant = await make_tenant()
    raw = form_bytes(twilio_pairs() + [("Pad", "x" * (MAX_BODY_BYTES - 1500))])
    assert len(raw) < MAX_BODY_BYTES
    response = await intake.post(tenant, raw=raw)
    assert response.status_code == 200 and await count(tenant, Message) == 1


async def test_a_tenant_that_is_not_a_uuid_gets_200_and_nothing_is_stored(intake, make_tenant):
    tenant = await make_tenant()
    with Counter() as statements:
        response = await intake.post("not-a-uuid")
    assert response.status_code == 200 and response.text == EMPTY
    assert statements == []
    assert await nothing_stored(tenant)


async def test_an_unknown_tenant_gets_200_and_nothing_is_stored(intake):
    response = await intake.post(uuid.uuid4())
    assert response.status_code == 200 and response.text == EMPTY


async def test_a_tenant_written_in_capitals_is_not_trusted(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(str(tenant).upper())
    assert response.status_code == 200
    assert await nothing_stored(tenant)


async def test_a_clinic_without_the_feature_gets_200_and_nothing_is_stored(intake, make_tenant):
    tenant = await make_tenant(())
    response = await intake.post(tenant)
    assert response.status_code == 200 and response.text == EMPTY
    assert await nothing_stored(tenant)


async def test_a_text_to_another_number_is_not_stored(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs(To="+14155550199"))
    assert response.status_code == 200 and response.text == EMPTY
    assert await nothing_stored(tenant)


@pytest.mark.parametrize("sender", ["12345", "AcmeBank", "whatsapp:+14155550142", ""])
async def test_a_sender_that_is_not_a_phone_number_is_dropped_with_200(intake, make_tenant, sender):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs(From=sender))
    assert response.status_code == 200
    assert await nothing_stored(tenant)


@pytest.mark.parametrize("bad", ["", "SM123", "XX" + "0" * 32])
async def test_a_signed_post_without_a_proper_sid_is_400(intake, make_tenant, bad):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs(MessageSid=bad))
    assert response.status_code == 400 and response.content == b""
    assert await nothing_stored(tenant)


async def test_a_get_is_not_allowed(intake, make_tenant):
    tenant = await make_tenant()
    async with intake.client() as client:
        response = await client.get(f"{PATH}/in/sms/{tenant}")
    assert response.status_code == 405


async def test_the_answer_never_carries_the_text_or_the_numbers(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant)
    shown = response.text + str(dict(response.headers))
    assert BODY not in shown and LEAD_NUMBER not in shown and OUR_NUMBER not in shown
