"""``ops`` schema: platform plumbing (event outbox, audit log)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, TenantMixin

SCHEMA = {"schema": "ops"}


class OutboxEvent(TenantMixin, Base):
    """Domain events, written in the same transaction as the change that caused them.

    The worker relays unpublished rows to the queue, where every enabled feature's
    handlers receive them. This is how features react to each other without imports.
    """

    __tablename__ = "outbox_events"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AuditLog(TenantMixin, Base):
    """Append-only record of who touched PHI. The app role may insert, never update/delete."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tenant_time_id", "tenant_id", "occurred_at", "id"), SCHEMA)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(32), comment="staff, system, api_key")
    actor_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
