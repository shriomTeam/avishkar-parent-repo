"""``core`` schema: the canonical clinic model every feature reads from.

Client data from any EMR, POS, CSV or database is mapped into these tables by
``clinic_integrations``. Features must not keep their own copy of patients,
appointments, etc.: they reference these rows.

Enumerated values are stored as short strings, validated in Python with the
StrEnums below, so adding a value never needs a migration. Columns a client has
that we don't model yet go into ``attributes`` (JSONB) instead of a new column.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "core"}


class ClinicType(StrEnum):
    MEDSPA = "medspa"
    WELLNESS = "wellness"
    HRT = "hrt"


class TenantStatus(StrEnum):
    TRIAL = "trial"  # lead-magnet prospects (Dormant Revenue Finder, Patient Blueprint)
    ACTIVE = "active"
    SUSPENDED = "suspended"


class StaffRole(StrEnum):
    FRONT_DESK = "front_desk"
    PROVIDER = "provider"
    CONSULTANT = "consultant"
    OWNER = "owner"
    OFFICE_MANAGER = "office_manager"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ConsentKind(StrEnum):
    SMS = "sms"
    EMAIL = "email"
    VOICE = "voice"
    CALL_RECORDING = "call_recording"
    VISIT_RECORDING = "visit_recording"
    PHOTO_PUBLISH = "photo_publish"
    TREATMENT = "treatment"


class Tenant(IdMixin, TimestampMixin, Base):
    """One clinic business (may have several locations)."""

    __tablename__ = "tenants"
    __table_args__ = SCHEMA

    name: Mapped[str] = mapped_column(String(200))
    clinic_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=TenantStatus.TRIAL)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baa_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="No PHI may be imported before the BAA is signed."
    )
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class TenantFeature(Base):
    """Entitlements: which sellable components a tenant has switched on."""

    __tablename__ = "tenant_features"
    __table_args__ = SCHEMA

    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Location(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = SCHEMA

    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(2), comment="US state; drives call/visit recording-consent rules.")
    timezone: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Staff(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (UniqueConstraint("tenant_id", "email"), UniqueConstraint("tenant_id", "user_id"), SCHEMA)

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth.users.id", ondelete="SET NULL"), index=True)

    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Provider(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = SCHEMA

    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.staff.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    credentials: Mapped[str | None] = mapped_column(String(64))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Service(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = SCHEMA

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100), comment="e.g. injectables, laser, hrt, iv")
    default_price_cents: Mapped[int | None] = mapped_column(BigInteger)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Patient(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "patients"
    __table_args__ = SCHEMA

    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True, comment="E.164")
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(32))
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.locations.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Lead(IdMixin, TenantMixin, TimestampMixin, Base):
    """An inquiry that is not (yet) a patient. Carries attribution from first touch."""

    __tablename__ = "leads"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.patients.id", ondelete="SET NULL"))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str | None] = mapped_column(String(64), comment="meta_ads, google_ads, web_form, call...")
    campaign: Mapped[str | None] = mapped_column(String(200))
    utm: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(32), default="new")
    interest: Mapped[str | None] = mapped_column(Text)


class Appointment(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.providers.id", ondelete="SET NULL"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.id", ondelete="SET NULL"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.locations.id", ondelete="SET NULL"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=AppointmentStatus.BOOKED)
    booked_via: Mapped[str | None] = mapped_column(
        String(32), comment="import, staff, voice_agent, sms, web, reactivation..."
    )
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Transaction(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("core.patients.id", ondelete="SET NULL"), index=True
    )
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.appointments.id", ondelete="SET NULL"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.id", ondelete="SET NULL"))
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.providers.id", ondelete="SET NULL"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    kind: Mapped[str] = mapped_column(
        String(32), default="service", comment="service, product, membership, package, refund"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class Membership(IdMixin, TenantMixin, TimestampMixin, Base):
    """Memberships, packages and prepaid balances (wellness) and subscriptions (HRT)."""

    __tablename__ = "memberships"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    plan_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="membership", comment="membership, package, subscription")
    status: Mapped[str] = mapped_column(String(32), default="active")
    started_at: Mapped[date | None] = mapped_column(Date)
    ends_at: Mapped[date | None] = mapped_column(Date)
    recurring_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    prepaid_balance_cents: Mapped[int | None] = mapped_column(BigInteger)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class CarePlan(IdMixin, TenantMixin, TimestampMixin, Base):
    """Protocol-driven care (e.g. HRT): drives labs/refill/follow-up reminders."""

    __tablename__ = "care_plans"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.providers.id", ondelete="SET NULL"))
    protocol: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="active")
    started_at: Mapped[date | None] = mapped_column(Date)
    next_due_at: Mapped[date | None] = mapped_column(Date)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class InventoryLot(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "inventory_lots"
    __table_args__ = SCHEMA

    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.locations.id", ondelete="SET NULL"))
    product_name: Mapped[str] = mapped_column(String(200))
    lot_number: Mapped[str] = mapped_column(String(100))
    expires_on: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class Consent(IdMixin, TenantMixin, TimestampMixin, Base):
    """Consent registry. Messaging, recording and photo publishing check this first."""

    __tablename__ = "consents"
    __table_args__ = SCHEMA

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.patients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str | None] = mapped_column(String(64), comment="import, form, sms_stop_keyword, verbal...")
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalRef(IdMixin, TenantMixin, Base):
    """Maps a row in a client's source system (EMR, POS, CSV) to our canonical row.

    Makes imports idempotent (re-importing the same file updates, never duplicates)
    and lets an ongoing sync find the row it created last time.
    """

    __tablename__ = "external_refs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_system", "entity_type", "external_id"),
        SCHEMA,
    )

    source_system: Mapped[str] = mapped_column(String(64), comment="csv:<name>, boulevard, zenoti, ...")
    entity_type: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(200))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
