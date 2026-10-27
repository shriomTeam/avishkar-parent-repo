import uuid
from datetime import UTC, datetime

import pytest
from lr_seed import PHONE, seed
from sqlalchemy.exc import IntegrityError

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import (
    Contact,
    ContactIdentity,
    Conversation,
    Job,
    Message,
    Task,
)


async def _add(tenant, *rows):
    async with tenant_session(tenant) as s:
        s.add_all(rows)


async def _contact(tenant) -> uuid.UUID:
    contact = Contact(tenant_id=tenant)
    await _add(tenant, contact)
    return contact.id


async def test_second_contact_with_the_same_phone_fails(make_tenant):
    t = await make_tenant()
    await seed(t)
    other = await _contact(t)
    with pytest.raises(IntegrityError, match="uq_contact_identities"):
        await _add(t, ContactIdentity(tenant_id=t, contact_id=other, kind="phone", value=PHONE))


async def test_same_phone_is_allowed_for_another_tenant(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await seed(a)
    await seed(b)


@pytest.mark.parametrize("bad", ["4155550123", "+0123456789", "+1415", "+1415555012345678", "+1 415 555 0123"])
async def test_phone_identity_must_be_e164(make_tenant, bad):
    t = await make_tenant()
    contact = await _contact(t)
    with pytest.raises(IntegrityError, match="phone_is_e164"):
        await _add(t, ContactIdentity(tenant_id=t, contact_id=contact, kind="phone", value=bad))


async def test_email_identity_must_be_lowercase(make_tenant):
    t = await make_tenant()
    contact = await _contact(t)
    with pytest.raises(IntegrityError, match="email_is_lowercase"):
        await _add(t, ContactIdentity(tenant_id=t, contact_id=contact, kind="email", value="Ann@Example.com"))


async def _message(t, conversation, **kw):
    return Message(
        tenant_id=t,
        conversation_id=conversation,
        direction="inbound",
        channel="sms",
        sender_kind="contact",
        body="x",
        **kw,
    )


async def test_inbound_duplicate_provider_message_id_fails(make_tenant):
    t = await make_tenant()
    ids = await seed(t)
    dup = await _message(t, ids["conversation"], provider_message_id=f"SM{ids['message']}")
    with pytest.raises(IntegrityError, match="uq_messages_provider"):
        await _add(t, dup)


async def test_same_provider_message_id_is_allowed_for_another_tenant_and_for_none(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    ia, ib = await seed(a), await seed(b)
    await _add(b, await _message(b, ib["conversation"], provider_message_id=f"SM{ia['message']}"))
    await _add(a, await _message(a, ia["conversation"]), await _message(a, ia["conversation"]))


async def test_outbound_idempotency_key_rejects_a_duplicate_for_the_same_tenant_only(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    ia, ib = await seed(a), await seed(b)
    await _add(a, await _message(a, ia["conversation"], idempotency_key="ack:1"))
    with pytest.raises(IntegrityError, match="uq_messages_idempotency"):
        await _add(a, await _message(a, ia["conversation"], idempotency_key="ack:1"))
    await _add(b, await _message(b, ib["conversation"], idempotency_key="ack:1"))


def _job(t, key, **kw):
    return Job(tenant_id=t, kind="holding_message", run_at=datetime.now(UTC), idempotency_key=key, **kw)


async def test_job_idempotency_key_rejects_a_duplicate_for_the_same_tenant_only(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await _add(a, _job(a, "holding:1"))
    with pytest.raises(IntegrityError, match="uq_jobs_tenant_id_idempotency_key"):
        await _add(a, _job(a, "holding:1"))
    await _add(b, _job(b, "holding:1"))


async def test_a_conversation_has_one_open_task_but_any_number_of_closed_ones(make_tenant):
    t = await make_tenant()
    ids = await seed(t)

    def task(status):
        return Task(
            tenant_id=t,
            conversation_id=ids["conversation"],
            contact_id=ids["contact"],
            status=status,
            received_at=datetime.now(UTC),
        )

    with pytest.raises(IntegrityError, match="uq_tasks_one_open_per_conversation"):
        await _add(t, task("open"))
    await _add(t, task("handled"), task("handled"), task("cancelled"))


async def test_one_conversation_per_contact_channel_and_clinic_line(make_tenant):
    t = await make_tenant()
    ids = await seed(t)
    with pytest.raises(IntegrityError, match="uq_conversations"):
        await _add(
            t, Conversation(tenant_id=t, contact_id=ids["contact"], channel="sms", channel_address="+14155550100")
        )
