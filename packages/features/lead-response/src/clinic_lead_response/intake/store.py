"""Intake's reads and writes. Every function takes a tenant session, so row-level security applies, and nothing here
accepts an id from the request: contacts and conversations are found from the phone number inside the tenant.

``messages`` is append-only, so an inbound message is only ever inserted. A foreign key ignores row-level security,
which is why no id from outside is ever written as a reference."""

import uuid
from datetime import datetime

from sqlalchemy import and_, exists, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.lead_response import ConsentRecord, Contact, ContactIdentity, Conversation, Job, Message

CHANNEL = "sms"
FIRST_INBOUND = "first_inbound"
FLOOD_WINDOW = "60 seconds"


async def contact_for_phone(session: AsyncSession, phone: str) -> uuid.UUID | None:
    return await session.scalar(
        select(ContactIdentity.contact_id).where(ContactIdentity.kind == "phone", ContactIdentity.value == phone)
    )


async def resolve_contact(session: AsyncSession, phone: str) -> tuple[uuid.UUID, bool]:
    """The contact that owns this phone number in this clinic, made if it is new. True when it was made.

    Two first texts from one number can arrive together. The identity has a unique key, so one of them loses; its
    half-made contact is rolled back with the savepoint and it uses the winner's."""
    found = await contact_for_phone(session, phone)
    if found is not None:
        return found, False
    tenant_id = current_tenant(session)
    try:
        async with session.begin_nested():
            contact = Contact(tenant_id=tenant_id)
            session.add(contact)
            await session.flush()
            session.add(ContactIdentity(tenant_id=tenant_id, contact_id=contact.id, kind="phone", value=phone))
            await session.flush()
        return contact.id, True
    except IntegrityError:
        found = await contact_for_phone(session, phone)
        if found is None:  # the other request rolled back too: not a race we can explain
            raise
        return found, False


async def open_conversation(
    session: AsyncSession, contact_id: uuid.UUID, clinic_number: str, now: datetime
) -> uuid.UUID:
    """The conversation for this contact and the clinic's number, made if new, reopened if closed. The time of the
    last inbound text only moves forward."""
    statement = (
        insert(Conversation)
        .values(
            tenant_id=current_tenant(session),
            contact_id=contact_id,
            channel=CHANNEL,
            channel_address=clinic_number,
            last_inbound_at=now,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "contact_id", "channel", "channel_address"],
            set_={
                "status": "open",
                "last_inbound_at": func.greatest(func.coalesce(Conversation.last_inbound_at, now), now),
            },
        )
        .returning(Conversation.id)
    )
    return await session.scalar(statement)


async def insert_inbound(
    session: AsyncSession, *, conversation_id: uuid.UUID, sid: str, body: str, trace_id: uuid.UUID
) -> uuid.UUID | None:
    """None when this provider message was already stored (a Twilio retry). With no conflict target the insert
    answers any unique key: the provider message id and the idempotency key ``in:{sid}``. A retry that arrives while
    the first request is still open waits on the unique index, then finds the row and does nothing."""
    statement = (
        insert(Message)
        .values(
            tenant_id=current_tenant(session),
            conversation_id=conversation_id,
            direction="inbound",
            channel=CHANNEL,
            sender_kind="contact",
            body=body,
            provider="twilio",
            provider_message_id=sid,
            idempotency_key=f"in:{sid}",
            trace_id=trace_id,
        )
        .on_conflict_do_nothing()
        .returning(Message.id)
    )
    return await session.scalar(statement)


async def record_first_inbound_consent(
    session: AsyncSession, *, contact_id: uuid.UUID, message_id: uuid.UUID, trace_id: uuid.UUID
) -> None:
    """The lead's own first text is the grant that lets us reply. Written only when the contact has no consent record
    at all, so a contact who opted out is never granted again by texting."""
    tenant_id = current_tenant(session)
    none_yet = ~exists().where(
        and_(
            ConsentRecord.contact_id == contact_id,
            ConsentRecord.channel == CHANNEL,
        )
    )
    await session.execute(
        insert(ConsentRecord).from_select(
            ["tenant_id", "contact_id", "channel", "granted", "source", "message_id", "trace_id"],
            select(
                literal(tenant_id),
                literal(contact_id),
                literal(CHANNEL),
                literal(True),
                literal(FIRST_INBOUND),
                literal(message_id),
                literal(trace_id),
            ).where(none_yet),
        )
    )


async def recent_inbound_count(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    """Inbound texts in this conversation in the last minute, counting the one just stored (uses the conversation
    index; a clinic-wide count would scan the table)."""
    return await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "inbound",
            Message.created_at > func.now() - text(f"interval '{FLOOD_WINDOW}'"),
        )
    )


async def queue_ack(
    session: AsyncSession, *, conversation_id: uuid.UUID, message_id: uuid.UUID, trace_id: uuid.UUID, now: datetime
) -> bool:
    """The durable ack job, written in the same transaction as the message. Ids only, no personal data."""
    statement = (
        insert(Job)
        .values(
            tenant_id=current_tenant(session),
            kind="ack",
            run_at=now,
            idempotency_key=f"ack:{message_id}",
            conversation_id=conversation_id,
            payload={"message_id": str(message_id)},
            trace_id=trace_id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        .returning(Job.id)
    )
    return await session.scalar(statement) is not None
