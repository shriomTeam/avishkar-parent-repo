"""Who a text is from, which conversation it belongs to, what consent and job it leaves behind."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from lr_gateway import make_lead
from lr_intake import LEAD_NUMBER, OUR_NUMBER, Intake, count, rows, sid, twilio_pairs
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import ConsentRecord, Contact, ContactIdentity, Conversation, Job, Message
from clinic_lead_response.intake import service
from clinic_lead_response.intake.parse import InboundText

FLOOD_LIMIT = 20  # the design: more than 20 texts in a conversation in a minute are kept but get no ack


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


def test_the_flood_limit_is_the_designed_one():
    assert service.MAX_PER_MINUTE == FLOOD_LIMIT


def text(n: int = 1, *, sender: str = LEAD_NUMBER) -> InboundText:
    return InboundText(sid(n), sender, OUR_NUMBER, f"hello {n}")


async def test_a_new_number_makes_a_contact_an_identity_and_a_conversation(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    (contact,) = await rows(tenant, Contact)
    (identity,) = await rows(tenant, ContactIdentity)
    (conversation,) = await rows(tenant, Conversation)
    assert (identity.kind, identity.value, identity.contact_id) == ("phone", LEAD_NUMBER, contact.id)
    assert conversation.contact_id == contact.id
    assert (conversation.channel, conversation.channel_address, conversation.status) == ("sms", OUR_NUMBER, "open")
    assert conversation.last_inbound_at is not None and conversation.ai_paused is False
    (message,) = await rows(tenant, Message)
    assert message.conversation_id == conversation.id


async def test_the_next_text_from_the_same_number_joins_the_same_conversation(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    await intake.post(tenant, twilio_pairs(MessageSid=sid(2)))
    assert await count(tenant, Contact) == 1 and await count(tenant, Conversation) == 1
    assert await count(tenant, Message) == 2


async def test_an_existing_contact_is_found_by_its_number(intake, make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=LEAD_NUMBER)
    await intake.post(tenant)
    (message,) = await rows(tenant, Message)
    assert message.conversation_id == lead.conversation
    assert await count(tenant, Contact) == 1


async def test_two_numbers_are_two_contacts(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    await intake.post(tenant, twilio_pairs(MessageSid=sid(2), From="+14155550177"))
    assert await count(tenant, Contact) == 2 and await count(tenant, Conversation) == 2


async def test_a_closed_conversation_is_reopened_by_a_new_text(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    async with tenant_session(tenant) as s:
        await s.execute(update(Conversation).values(status="closed"))
    await intake.post(tenant, twilio_pairs(MessageSid=sid(2)))
    (conversation,) = await rows(tenant, Conversation)
    assert conversation.status == "open"


async def test_the_time_of_the_last_text_only_moves_forward(make_tenant):
    tenant = await make_tenant()
    now = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)
    await service.accept(tenant, text(1), trace_id=uuid.uuid4(), now=now)
    await service.accept(tenant, text(2), trace_id=uuid.uuid4(), now=now - timedelta(hours=1))
    (conversation,) = await rows(tenant, Conversation)
    assert conversation.last_inbound_at == now
    await service.accept(tenant, text(3), trace_id=uuid.uuid4(), now=now + timedelta(minutes=5))
    (conversation,) = await rows(tenant, Conversation)
    assert conversation.last_inbound_at == now + timedelta(minutes=5)


async def test_the_first_text_records_a_first_inbound_grant_once(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    await intake.post(tenant, twilio_pairs(MessageSid=sid(2)))
    (consent,) = await rows(tenant, ConsentRecord)
    first = (await rows(tenant, Message, Message.created_at))[0]
    assert (consent.granted, consent.source, consent.channel) == (True, "first_inbound", "sms")
    assert consent.message_id == first.id and consent.trace_id == first.trace_id


async def test_a_contact_who_opted_out_is_not_granted_again_by_texting(intake, make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=LEAD_NUMBER, consent=(False, "stop"))
    await intake.post(tenant)
    (consent,) = await rows(tenant, ConsentRecord)
    assert (consent.granted, consent.source, consent.contact_id) == (False, "stop", lead.contact)


async def test_an_explicit_grant_is_left_as_it_is(intake, make_tenant):
    tenant = await make_tenant()
    await make_lead(tenant, phone=LEAD_NUMBER, consent=(True, "start"))
    await intake.post(tenant)
    (consent,) = await rows(tenant, ConsentRecord)
    assert (consent.granted, consent.source) == (True, "start")


async def test_the_text_leaves_one_ack_job_with_ids_only(intake, make_tenant):
    tenant = await make_tenant()
    before = datetime.now(UTC)
    await intake.post(tenant)
    (job,) = await rows(tenant, Job)
    (message,) = await rows(tenant, Message)
    (conversation,) = await rows(tenant, Conversation)
    assert (job.kind, job.status, job.attempts) == ("ack", "pending", 0)
    assert job.idempotency_key == f"ack:{message.id}"
    assert job.conversation_id == conversation.id and job.task_id is None
    assert job.payload == {"message_id": str(message.id)}
    assert job.trace_id == message.trace_id
    assert before - timedelta(seconds=5) <= job.run_at <= datetime.now(UTC) + timedelta(seconds=5)


async def test_a_flood_is_kept_but_stops_getting_acks(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, FLOOD_LIMIT + 4):
        response = await intake.post(tenant, twilio_pairs(MessageSid=sid(n)))
        assert response.status_code == 200
    assert await count(tenant, Message) == FLOOD_LIMIT + 3
    assert await count(tenant, Job) == FLOOD_LIMIT


async def test_the_flood_guard_counts_each_conversation_alone(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, FLOOD_LIMIT + 2):
        await intake.post(tenant, twilio_pairs(MessageSid=sid(n)))
    await intake.post(tenant, twilio_pairs(MessageSid=sid(900), From="+14155550177"))
    assert await count(tenant, Job) == FLOOD_LIMIT + 1


async def test_what_the_service_reports(make_tenant):
    tenant = await make_tenant()
    first = await service.accept(tenant, text(1), trace_id=uuid.uuid4())
    assert first.outcome is service.Outcome.STORED and first.new_contact and first.ack_queued and not first.throttled
    again = await service.accept(tenant, text(1), trace_id=uuid.uuid4())
    assert again.outcome is service.Outcome.DUPLICATE and again.message_id is None and not again.ack_queued
    other = await service.accept(tenant, text(2), trace_id=uuid.uuid4())
    assert other.outcome is service.Outcome.STORED and not other.new_contact
    assert other.contact_id == first.contact_id and other.conversation_id == first.conversation_id


async def test_a_clinic_without_the_feature_gets_nothing_written(make_tenant):
    tenant = await make_tenant(())
    result = await service.accept(tenant, text(1), trace_id=uuid.uuid4())
    assert result.outcome is service.Outcome.NOT_ENABLED
    assert await count(tenant, Contact) == 0
