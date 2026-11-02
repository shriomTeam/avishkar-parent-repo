"""The gateway's reads and writes. Every function takes a tenant session, so row-level security applies; messages,
message_events and consent_records are append-only (the app role can only insert and select), so nothing is updated
except the conversation's last_outbound_at."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.core import Tenant
from clinic_db.models.lead_response import (
    ConsentRecord,
    Contact,
    ContactIdentity,
    Conversation,
    Message,
    MessageEvent,
)
from clinic_lead_response.gateway.policy import ConsentSnapshot


@dataclass(frozen=True)
class SendContext:
    contact_id: uuid.UUID
    channel: str
    phone: str | None


@dataclass(frozen=True)
class StoredMessage:
    id: uuid.UUID
    conversation_id: uuid.UUID
    channel: str
    sender_kind: str
    body: str
    trace_id: uuid.UUID | None


@dataclass(frozen=True)
class StoredEvent:
    attempt: int
    status: str
    reason_code: str | None
    provider_message_id: str | None
    created_at: datetime


async def find_message_by_key(session: AsyncSession, key: str) -> StoredMessage | None:
    row = (
        await session.execute(
            select(
                Message.id,
                Message.conversation_id,
                Message.channel,
                Message.sender_kind,
                Message.body,
                Message.trace_id,
            ).where(Message.idempotency_key == key)
        )
    ).first()
    return StoredMessage(*row) if row else None


async def get_message(session: AsyncSession, message_id: uuid.UUID) -> StoredMessage | None:
    row = (
        await session.execute(
            select(
                Message.id,
                Message.conversation_id,
                Message.channel,
                Message.sender_kind,
                Message.body,
                Message.trace_id,
            ).where(Message.id == message_id)
        )
    ).first()
    return StoredMessage(*row) if row else None


async def events_of(session: AsyncSession, message_id: uuid.UUID) -> list[StoredEvent]:
    rows = await session.execute(
        select(
            MessageEvent.attempt,
            MessageEvent.status,
            MessageEvent.reason_code,
            MessageEvent.provider_message_id,
            MessageEvent.created_at,
        )
        .where(MessageEvent.message_id == message_id)
        .order_by(MessageEvent.created_at, MessageEvent.attempt)
    )
    return [StoredEvent(*row) for row in rows]


async def load_send_context(session: AsyncSession, conversation_id: uuid.UUID) -> SendContext | None:
    row = (
        await session.execute(
            select(Conversation.contact_id, Conversation.channel, ContactIdentity.value)
            .select_from(Conversation)
            .outerjoin(
                ContactIdentity,
                and_(ContactIdentity.contact_id == Conversation.contact_id, ContactIdentity.kind == "phone"),
            )
            .where(Conversation.id == conversation_id)
            .order_by(ContactIdentity.created_at)
            .limit(1)
        )
    ).first()
    return SendContext(*row) if row else None


async def contact_exists(session: AsyncSession, contact_id: uuid.UUID) -> bool:
    return await session.scalar(select(Contact.id).where(Contact.id == contact_id)) is not None


async def contact_of_message(session: AsyncSession, message_id: uuid.UUID) -> tuple[uuid.UUID, str] | None:
    row = (
        await session.execute(
            select(Conversation.contact_id, Conversation.channel)
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def tenant_info(session: AsyncSession) -> tuple[str, str]:
    """The clinic's time zone and name, from core.tenants (a tenant session can read its own row)."""
    row = (
        await session.execute(select(Tenant.timezone, Tenant.name).where(Tenant.id == current_tenant(session)))
    ).one()
    return row[0], row[1]


async def consent_snapshots(session: AsyncSession, contact_id: uuid.UUID, channel: str) -> list[ConsentSnapshot]:
    """The newest consent record(s) for the contact and channel: every row that shares the latest timestamp, so a tie
    between a grant and a revocation is visible to the policy."""
    newest = (
        select(ConsentRecord.created_at)
        .where(ConsentRecord.contact_id == contact_id, ConsentRecord.channel == channel)
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(ConsentRecord.granted, ConsentRecord.source, ConsentRecord.created_at).where(
            ConsentRecord.contact_id == contact_id, ConsentRecord.channel == channel, ConsentRecord.created_at == newest
        )
    )
    return [ConsentSnapshot(*row) for row in rows]


async def insert_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    channel: str,
    sender_kind: str,
    body: str,
    provider: str,
    idempotency_key: str,
    trace_id: uuid.UUID,
    staff_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """None when the idempotency key was already used (another request got there first)."""
    statement = (
        insert(Message)
        .values(
            tenant_id=current_tenant(session),
            conversation_id=conversation_id,
            direction="outbound",
            channel=channel,
            sender_kind=sender_kind,
            body=body,
            provider=provider,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            staff_id=staff_id,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "idempotency_key"], index_where=text("idempotency_key IS NOT NULL")
        )
        .returning(Message.id)
    )
    return await session.scalar(statement)


async def append_event(
    session: AsyncSession,
    *,
    message_id: uuid.UUID,
    attempt: int,
    status: str,
    trace_id: uuid.UUID | None,
    reason_code: str | None = None,
    provider_message_id: str | None = None,
) -> bool:
    """False when this (message, attempt, status) is already recorded: a replayed receipt is a no-op."""
    statement = (
        insert(MessageEvent)
        .values(
            tenant_id=current_tenant(session),
            message_id=message_id,
            attempt=attempt,
            status=status,
            reason_code=reason_code,
            provider_message_id=provider_message_id,
            trace_id=trace_id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "message_id", "attempt", "status"])
        .returning(MessageEvent.id)
    )
    return await session.scalar(statement) is not None


async def event_for_provider_message(session: AsyncSession, provider_message_id: str) -> tuple[uuid.UUID, int] | None:
    row = (
        await session.execute(
            select(MessageEvent.message_id, MessageEvent.attempt)
            .where(MessageEvent.provider_message_id == provider_message_id)
            .order_by(MessageEvent.created_at)
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def add_consent(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    channel: str,
    granted: bool,
    source: str,
    trace_id: uuid.UUID | None,
    message_id: uuid.UUID | None = None,
    evidence: dict | None = None,
) -> uuid.UUID:
    record = ConsentRecord(
        tenant_id=current_tenant(session),
        contact_id=contact_id,
        channel=channel,
        granted=granted,
        source=source,
        message_id=message_id,
        evidence=evidence or {},
        trace_id=trace_id,
    )
    session.add(record)
    await session.flush()
    return record.id


async def touch_last_outbound(session: AsyncSession, conversation_id: uuid.UUID, when: datetime) -> None:
    await session.execute(update(Conversation).where(Conversation.id == conversation_id).values(last_outbound_at=when))
