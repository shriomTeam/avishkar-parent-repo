"""One clinic's text must never touch another clinic's rows."""

import uuid

import pytest
from lr_gateway import make_lead
from lr_intake import LEAD_NUMBER, PATH, SID, Intake, count, rows, twilio_pairs

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import ConsentRecord, Contact, ContactIdentity, Conversation, Job, Message
from clinic_lead_response.intake import service, store
from clinic_lead_response.intake.parse import InboundText


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def test_the_same_number_is_a_separate_contact_in_each_clinic(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await intake.post(a)
    await intake.post(b)
    (contact_a,) = await rows(a, Contact)
    (contact_b,) = await rows(b, Contact)
    assert contact_a.id != contact_b.id
    assert (await rows(a, ContactIdentity))[0].value == (await rows(b, ContactIdentity))[0].value == LEAD_NUMBER


async def test_a_text_to_one_clinic_leaves_the_other_empty(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await intake.post(a)
    for model in (Message, Contact, Conversation, Job, ConsentRecord):
        assert await count(b, model) == 0


async def test_a_request_signed_for_clinic_a_cannot_write_to_clinic_b(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    response = await intake.post(b, signed_path=f"{PATH}/in/sms/{a}")
    assert response.status_code == 403
    assert await count(a, Message) == 0 and await count(b, Message) == 0


async def test_a_clinic_with_the_feature_is_not_reached_through_one_without(intake, make_tenant):
    on, off = await make_tenant(), await make_tenant(())
    response = await intake.post(off)
    assert response.status_code == 200
    assert await count(off, Message) == 0 and await count(on, Message) == 0


async def test_looking_up_a_number_in_one_clinic_never_finds_the_other_clinics_contact(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_b = await make_lead(b, phone=LEAD_NUMBER)
    async with tenant_session(a) as session:
        assert await store.contact_for_phone(session, LEAD_NUMBER) is None
        contact_id, created = await store.resolve_contact(session, LEAD_NUMBER)
    assert created and contact_id != lead_b.contact
    assert await count(b, Contact) == 1


async def test_a_conversation_is_never_reused_across_clinics(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_b = await make_lead(b, phone=LEAD_NUMBER)
    text = InboundText(SID, LEAD_NUMBER, "+14155550100", "hi")
    result = await service.accept(a, text, trace_id=uuid.uuid4())
    assert result.conversation_id != lead_b.conversation
    assert await count(b, Message) == 0


async def test_the_service_refuses_a_session_for_another_clinic_with_no_feature(make_tenant):
    on, off = await make_tenant(), await make_tenant(())
    result = await service.accept(off, InboundText(SID, LEAD_NUMBER, "+14155550100", "x"), trace_id=uuid.uuid4())
    assert result.outcome is service.Outcome.NOT_ENABLED
    assert await count(on, Message) == 0


async def test_the_pairs_helper_posts_the_same_text_to_both_clinics_without_mixing_them(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await intake.post(a, twilio_pairs(Body="for clinic a"))
    await intake.post(b, twilio_pairs(Body="for clinic b"))
    assert [m.body for m in await rows(a, Message)] == ["for clinic a"]
    assert [m.body for m in await rows(b, Message)] == ["for clinic b"]
