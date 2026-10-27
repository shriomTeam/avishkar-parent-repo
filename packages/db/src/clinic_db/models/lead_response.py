"""``lead_response`` schema, owned by the 60-Second Response System team.

``messages``, ``message_events`` and ``consent_records`` are append-only: the migration adds triggers and revokes
UPDATE and DELETE, so a delivery status is a new ``message_events`` row, never an edit of a message.
``jobs`` is the queue of record for release 1 (due time, kind, idempotency key, attempts, status).
Message bodies are personal data: never log them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "lead_response"}

# Python only on purpose: placeholder wording that chunk 2 validates in the API, so the database has no default.
DEFAULT_ACK_TEXT = "Thanks for your message. We have received it and a member of our team will reply soon."
DEFAULT_CAPABILITIES = (
    '{"answer_questions": false, "quote_pricing": false, "show_open_slots": false, '
    '"book_appointments": false, "patient_aware_replies": false}'
)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = SCHEMA

    display_name: Mapped[str | None] = mapped_column(String(200))


class ContactIdentity(IdMixin, TenantMixin, Base):
    """A way to reach or recognise a contact. One phone number belongs to one contact per tenant."""

    __tablename__ = "contact_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "value"),
        CheckConstraint(r"kind <> 'phone' OR value ~ '^\+[1-9][0-9]{7,14}$'", name="phone_is_e164"),
        CheckConstraint("kind <> 'email' OR value = lower(value)", name="email_is_lowercase"),
        SCHEMA,
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lead_response.contacts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), comment="phone, email, instagram, facebook")
    value: Mapped[str] = mapped_column(String(320), comment="phone as E.164, email lowercased")
    created_at: Mapped[datetime] = _created_at()


class Conversation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contact_id", "channel", "channel_address"),
        Index("ix_conversations_tenant_last_inbound", "tenant_id", "last_inbound_at"),
        SCHEMA,
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), comment="sms")
    channel_address: Mapped[str] = mapped_column(String(32), comment="the clinic's own number on this channel")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", comment="open, closed")
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    ai_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, TenantMixin, Base):
    """Append-only. Personal data in ``body``; stored as plain text until an encryption scheme is chosen."""

    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "uq_messages_provider",
            "tenant_id",
            "channel",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        Index(
            "uq_messages_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        SCHEMA,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.conversations.id"))
    direction: Mapped[str] = mapped_column(String(16), comment="inbound, outbound")
    channel: Mapped[str] = mapped_column(String(16))
    sender_kind: Mapped[str] = mapped_column(String(16), comment="contact, ack, holding, staff, ai")
    body: Mapped[str] = mapped_column(Text, comment="personal data; never log")
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.staff.id", ondelete="SET NULL"))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class MessageEvent(IdMixin, TenantMixin, Base):
    """Append-only. Send attempts and delivery receipts for one message."""

    __tablename__ = "message_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", "attempt", "status"),
        Index("ix_message_events_provider_message", "tenant_id", "provider_message_id"),
        SCHEMA,
    )

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.messages.id"), index=True)
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), comment="queued, sent, delivered, failed, blocked")
    reason_code: Mapped[str | None] = mapped_column(String(64))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class ConsentRecord(IdMixin, TenantMixin, Base):
    """Append-only. The newest row for a contact and channel is the current consent."""

    __tablename__ = "consent_records"
    __table_args__ = (
        Index("ix_consent_records_contact_channel_created", "tenant_id", "contact_id", "channel", "created_at"),
        SCHEMA,
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.contacts.id"))
    channel: Mapped[str] = mapped_column(String(16))
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(32), comment="first_inbound, stop, start, staff, import")
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_response.messages.id"))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", comment="names only")
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class Task(IdMixin, TenantMixin, TimestampMixin, Base):
    """The priority staff task for one wait. Time waiting is computed from ``received_at``."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "uq_tasks_one_open_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_tasks_dashboard", "tenant_id", "status", text("priority DESC"), "received_at"),
        SCHEMA,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.conversations.id"))
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_response.contacts.id"))
    status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", comment="open, handled, cancelled"
    )
    priority: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    escalation_state: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", comment="none, escalated"
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    holding_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_staff_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.staff.id", ondelete="SET NULL"))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Job(IdMixin, TenantMixin, Base):
    """The queue of record for release 1. Scanned across tenants by the scheduler, run inside a tenant session."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key"),
        Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'pending'")),
        Index("ix_jobs_conversation_status", "tenant_id", "conversation_id", "status"),
        SCHEMA,
    )

    kind: Mapped[str] = mapped_column(String(32), comment="ack, holding_message, sla_escalation, follow_up")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", comment="pending, running, done, failed, cancelled"
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, default=3, server_default="3")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_response.conversations.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_response.tasks.id"))
    payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", comment="ids only, no personal data"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    cancel_reason: Mapped[str | None] = mapped_column(String(32), comment="booked, stop, staff_reply, handled")
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PracticeSettings(IdMixin, TenantMixin, Base):
    """One immutable row per version; the current settings are the row with the highest version.
    No row means version 0: the defaults below. Capability toggles are stored but not wired in release 1."""

    __tablename__ = "practice_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version"),
        CheckConstraint("holding_minutes BETWEEN 5 AND 60", name="holding_range"),
        CheckConstraint("sla_minutes BETWEEN 10 AND 240", name="sla_range"),
        CheckConstraint("sla_minutes > holding_minutes", name="sla_after_holding"),
        CheckConstraint("ai_active_mode <> 'overflow' OR overflow_minutes IS NOT NULL", name="overflow_needs_minutes"),
        SCHEMA,
    )

    version: Mapped[int] = mapped_column(Integer)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    capabilities: Mapped[dict] = mapped_column(JSONB, server_default=DEFAULT_CAPABILITIES, comment="all off")
    context_fields: Mapped[list] = mapped_column(JSONB, server_default="[]")
    send_mode: Mapped[str] = mapped_column(String(8), default="draft", server_default="draft", comment="draft, auto")
    ai_active_mode: Mapped[str] = mapped_column(
        String(16), default="always", server_default="always", comment="always, after_hours, overflow"
    )
    overflow_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    holding_minutes: Mapped[int] = mapped_column(SmallInteger, default=15, server_default="15")
    sla_minutes: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    ack_text: Mapped[str] = mapped_column(Text, default=DEFAULT_ACK_TEXT)
    business_hours: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    quiet_hours: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    escalation_role: Mapped[str] = mapped_column(String(32), default="office_manager", server_default="office_manager")
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created_at()
