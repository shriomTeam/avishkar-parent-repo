"""Shared invitation and transactional-email state; no feature dependencies."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Invitation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        Index("uq_pending_invitation", "tenant_id", "email", unique=True, postgresql_where=text("status='pending'")),
        {"schema": "core"},
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32))
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.staff.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth.users.id"))


class InvitationContext(IdMixin, TimestampMixin, Base):
    __tablename__ = "invitation_contexts"
    __table_args__ = {"schema": "auth"}
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.workspace_invitations.id", ondelete="CASCADE"))
    generation: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verification_hash: Mapped[str | None] = mapped_column(String(64))
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth.users.id"))
    verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailDelivery(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "deduplication_key"),
        Index("ix_email_due", "status", "next_attempt_at"),
        {"schema": "ops"},
    )
    deduplication_key: Mapped[str] = mapped_column(String(150))
    payload: Mapped[str | None] = mapped_column(Text)
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.workspace_invitations.id", ondelete="CASCADE")
    )
    generation: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(80))
    task_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
