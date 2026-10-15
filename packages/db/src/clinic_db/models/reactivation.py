"""``reactivation`` schema, owned by the Dormant Revenue Finder team."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reactivation.runs.id", ondelete="SET NULL"), index=True
    )
    type_key: Mapped[str | None] = mapped_column(String(32), comment="informational: patient type it came from")
    category: Mapped[str | None] = mapped_column(String(100))
    audience: Mapped[dict | None] = mapped_column(JSONB, comment="free-form, validated in Python")
    schedule: Mapped[dict | None] = mapped_column(JSONB, comment="free-form, validated in Python")
    content: Mapped[dict | None] = mapped_column(JSONB, comment="free-form, validated in Python")


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


class RunPatient(TenantMixin, Base):
    __tablename__ = "run_patients"
    __table_args__ = (Index("ix_run_patients_type_score", "run_id", "primary_type", "likelihood_score"), SCHEMA)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reactivation.runs.id", ondelete="CASCADE"), primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), comment="dormant, at_risk")
    primary_type: Mapped[str | None] = mapped_column(String(32))
    matched_types: Mapped[list] = mapped_column(JSONB, default=list)
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days_since_last_visit: Mapped[int | None] = mapped_column(Integer)
    overdue_ratio: Mapped[float | None] = mapped_column(Numeric(6, 2))
    visit_count: Mapped[int] = mapped_column(Integer)
    total_spend_cents: Mapped[int] = mapped_column(BigInteger)
    usual_service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.id", ondelete="SET NULL"))
    usual_provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.providers.id", ondelete="SET NULL"))
    revenue_basis_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    revenue_kind: Mapped[str] = mapped_column(String(16), default="new", comment="new, retention")
    likelihood_score: Mapped[int | None] = mapped_column(SmallInteger)
    points: Mapped[dict] = mapped_column(JSONB, default=dict, comment="enabled analysis points only")
    change: Mapped[str | None] = mapped_column(String(24), comment="new, unchanged, returned_since_last")
    reasons: Mapped[list] = mapped_column(JSONB, default=list, comment="plain-words rule hits")


class RunType(TenantMixin, Base):
    __tablename__ = "run_types"
    __table_args__ = SCHEMA

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reactivation.runs.id", ondelete="CASCADE"), primary_key=True)
    type_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_count: Mapped[int] = mapped_column(Integer)
    basis_total_cents: Mapped[int] = mapped_column(BigInteger)
    rate_low: Mapped[float] = mapped_column(Numeric(5, 4))
    rate_high: Mapped[float] = mapped_column(Numeric(5, 4))
    rate_source: Mapped[str] = mapped_column(String(16), comment="assumed, measured")
    revenue_low_cents: Mapped[int] = mapped_column(BigInteger)
    revenue_high_cents: Mapped[int] = mapped_column(BigInteger)
    revenue_kind: Mapped[str] = mapped_column(String(16))
    top_service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.id", ondelete="SET NULL"))
