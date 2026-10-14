"""``reactivation`` schema, owned by the Dormant Revenue Finder team."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "reactivation"}


class Campaign(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = SCHEMA

    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="draft", comment="draft, running, finished")
    criteria: Mapped[dict] = mapped_column(JSONB, comment="e.g. {'lapsed_days': 180}")
    sequence_key: Mapped[str] = mapped_column(String(100), default="reactivation.default")
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignTarget(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "campaign_targets"
    __table_args__ = (UniqueConstraint("campaign_id", "patient_id"), SCHEMA)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reactivation.campaigns.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    days_lapsed: Mapped[int] = mapped_column(Integer)
    lifetime_value_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending, contacted, booked, opted_out")
    booked_appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.appointments.id", ondelete="SET NULL")
    )
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Settings(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("tenant_id"), SCHEMA)

    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSONB, comment="ReactivationSettings, validated in Python")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_by: Mapped[str | None] = mapped_column(String(100))


class Run(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("uq_runs_one_running", "tenant_id", unique=True, postgresql_where=text("status = 'running'")),
        Index("uq_runs_one_queued", "tenant_id", unique=True, postgresql_where=text("status = 'queued'")),
        Index(
            "uq_runs_idem",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        SCHEMA,
    )

    trigger: Mapped[str] = mapped_column(String(16), comment="scheduled, manual")
    status: Mapped[str] = mapped_column(
        String(16), default="queued", comment="queued, running, completed, failed, cancelled"
    )
    requested_by: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    settings_version: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSONB, comment="copy of the config this run used")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    quality: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reactivation.runs.id", ondelete="SET NULL"))
