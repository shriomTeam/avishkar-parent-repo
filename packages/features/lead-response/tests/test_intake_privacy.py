"""No message text, phone number or request value reaches a log line, an audit row or a job."""

import logging
import uuid

import pytest
from lr_intake import BODY, LEAD_NUMBER, OUR_NUMBER, PATH, Intake, count, rows, sid, twilio_pairs
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job, Message
from clinic_db.models.ops import AuditLog
from clinic_lead_response.intake import service
from clinic_lead_response.intake.parse import InboundText

EVIL_TENANT = "zebraquartz-evil-tenant-sentinel"


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


@pytest.fixture
def lines(caplog):
    """Every record from this feature, at every level, as one list of the text that would reach a log."""
    caplog.set_level(logging.DEBUG, logger="lead_response")
    caplog.set_level(logging.DEBUG, logger="clinic_core")

    def read() -> list[str]:
        return [record.getMessage() for record in caplog.records]

    return read


def personal() -> list[str]:
    return [BODY, "Zebra-Quartz", LEAD_NUMBER, LEAD_NUMBER[1:], OUR_NUMBER, OUR_NUMBER[1:]]


def assert_clean(lines: list[str]) -> None:
    for line in lines:
        for secret in personal():
            assert secret not in line, "a personal value reached a log line"


async def test_a_stored_text_logs_ids_and_no_personal_value(intake, make_tenant, lines):
    tenant = await make_tenant()
    await intake.post(tenant)
    written = lines()
    assert written, "the route should log what it did"
    assert_clean(written)
    stored = [line for line in written if "outcome=stored" in line]
    assert len(stored) == 1
    assert f"tenant_id={tenant}" in stored[0] and "trace_id=" in stored[0] and "message_id=" in stored[0]


async def test_every_kind_of_refusal_and_drop_logs_no_personal_value(intake, make_tenant, lines):
    tenant = await make_tenant()
    await intake.post(tenant)
    await intake.post(tenant)  # a repeat
    await intake.post(tenant, sign=False)
    await intake.post(tenant, twilio_pairs(MessageSid="bad"))
    await intake.post(tenant, twilio_pairs(From="12345"))
    await intake.post(tenant, twilio_pairs(To="+14155550199"))
    await intake.post(uuid.uuid4())
    await intake.post("not-a-uuid")
    await intake.post(tenant, content_type="text/plain")
    assert_clean(lines())


async def test_the_reasons_are_fixed_words(intake, make_tenant, lines):
    tenant = await make_tenant()
    await intake.post(tenant, sign=False)
    await intake.post(tenant, twilio_pairs(From="12345"))
    text = " ".join(lines())
    assert "reason=bad_signature" in text and "reason=sender_not_e164" in text


async def test_an_unverified_tenant_from_the_url_is_never_logged(intake, lines):
    response = await intake.post(EVIL_TENANT, sign=False)
    assert response.status_code == 403
    signed = await intake.post(EVIL_TENANT)
    assert signed.status_code == 200
    assert EVIL_TENANT not in " ".join(lines())


async def test_the_trace_id_is_ours_and_not_read_from_the_request(intake, make_tenant):
    tenant = await make_tenant()
    theirs = uuid.uuid4()
    await intake.post(tenant, headers={"x-trace-id": str(theirs), "x-request-id": str(theirs)})
    (message,) = await rows(tenant, Message)
    assert message.trace_id is not None and message.trace_id != theirs


async def test_the_job_holds_ids_and_nothing_else(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    (job,) = await rows(tenant, Job)
    (message,) = await rows(tenant, Message)
    assert job.payload == {"message_id": str(message.id)}
    assert job.last_error_code is None and job.cancel_reason is None


async def test_intake_writes_no_audit_row(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(AuditLog.id).limit(1)) is None


async def test_what_the_service_returns_shows_no_personal_value(make_tenant):
    tenant = await make_tenant()
    result = await service.accept(tenant, InboundText(sid(1), LEAD_NUMBER, OUR_NUMBER, BODY), trace_id=uuid.uuid4())
    assert BODY not in repr(result) and LEAD_NUMBER not in repr(result)


async def test_the_only_place_the_text_is_kept_is_the_message(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    assert await count(tenant, Message) == 1
    (job,) = await rows(tenant, Job)
    assert BODY not in str(job.payload) and LEAD_NUMBER not in str(job.payload)
    assert PATH  # the helper is in use
