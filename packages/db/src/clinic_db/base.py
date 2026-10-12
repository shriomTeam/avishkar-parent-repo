"""Declarative base, shared column mixins and the list of Postgres schemas.

Every feature gets its own Postgres schema (namespace). Shared entities live in
``core``. Tables are still defined only here, in one package, so the same table
can never be defined twice and there is a single migration stream.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Order matters only for readability; the initial migration creates them all.
PLATFORM_SCHEMAS = ["core", "staging", "ops", "engagement"]
FEATURE_SCHEMAS = [
    "reactivation",
    "blueprints",
    "lead_response",
    "reviews",
    "voice",
    "scribe",
    "command_center",
    "photos",
]
ALL_SCHEMAS = PLATFORM_SCHEMAS + FEATURE_SCHEMAS

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Marks a table as tenant-scoped. Migrations enable row-level security on it
    (see ``clinic_db.rls``), so a session only ever sees its own tenant's rows."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"), index=True
    )


def tenant_scoped_tables() -> list[str]:
    """Fully qualified names of every table that carries tenant_id."""
    return sorted(f"{t.schema}.{t.name}" for t in Base.metadata.sorted_tables if "tenant_id" in t.columns)
