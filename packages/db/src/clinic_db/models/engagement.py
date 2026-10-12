"""``engagement`` schema: the shared outreach engine.

Reactivation, lead follow-up and review requests are all "enrol people in a
multi-step SMS/email sequence and stop when they book or reply". They share these
tables instead of each feature building its own messaging.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "engagement"}


class Enrollment(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = SCHEMA

    sequence_key: Mapped[str] = mapped_column(String(100), comment="e.g. reactivation.default")
    owner_feature: Mapped[str] = mapped_column(String(64))
    owner_ref: Mapped[uuid.UUID | None] = mapped_column(comment="feature's own row, e.g. a campaign target")
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.leads.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", comment="active, completed, stopped")
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Message(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = SCHEMA

    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("engagement.enrollments.id", ondelete="SET NULL"), index=True
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.patients.id", ondelete="SET NULL"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.leads.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(16), comment="sms, email")
    direction: Mapped[str] = mapped_column(String(16), default="outbound")
    to_address: Mapped[str] = mapped_column(String(320))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", comment="queued, sent, failed, blocked")
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
