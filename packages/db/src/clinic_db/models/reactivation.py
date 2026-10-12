"""``reactivation`` schema, owned by the Dormant Revenue Finder team."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
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
