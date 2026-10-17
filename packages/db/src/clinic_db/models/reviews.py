"""``reviews`` schema, owned by The 5-Star Machine team."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "reviews"}


class Campaign(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = SCHEMA

    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="draft", comment="draft, active, paused")
    trigger_type: Mapped[str] = mapped_column(String(64), default="appointment_completed")
    delay_minutes: Mapped[int] = mapped_column(Integer, default=120)
    channels: Mapped[list] = mapped_column(JSONB, comment="ordered: sms, email")
    fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    included_service_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    excluded_service_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    frequency_days: Mapped[int] = mapped_column(Integer, default=30)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Integration(IdMixin, TenantMixin, TimestampMixin, Base):
    """The practice's Google Business Profile review link."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id"), SCHEMA)

    listing_name: Mapped[str | None] = mapped_column(String(200))
    google_review_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(32), default="not_connected", comment="not_connected, connected, disconnected"
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewRequest(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "appointment_id", "campaign_id"),
        UniqueConstraint("public_token"),
        Index("ix_reviews_requests_due", "tenant_id", "status", "scheduled_at"),
        SCHEMA,
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.campaigns.id", ondelete="CASCADE"), index=True
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.appointments.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str | None] = mapped_column(String(16), comment="sms, email")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(32),
        default="scheduled",
        comment="scheduled, processing, submitted, skipped, cancelled, failed_permanent, completed",
    )
    skip_reason: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    public_token: Mapped[str] = mapped_column(String(64), default=text("encode(gen_random_bytes(24), 'hex')"))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("request_id"), SCHEMA)

    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.requests.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    google_review_offered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    google_review_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FollowUpTask(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "follow_up_tasks"
    __table_args__ = SCHEMA

    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.feedback.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(String(64), default="low_patient_rating")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending, resolved")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
