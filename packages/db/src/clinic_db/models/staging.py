"""``staging`` schema: where client data lands before it becomes canonical.

Every import (CSV, Excel, client database, EMR API) first writes the raw rows
here untouched, then a per-tenant mapping turns them into ``core`` rows. Nothing
about a client's source format ever requires a schema migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "staging"}


class SourceMapping(IdMixin, TenantMixin, TimestampMixin, Base):
    """How one client's source columns map to one canonical entity.

    ``config`` example::

        {"fields": {"external_id": "PatientID",
                    "email": {"column": "Email Address", "transform": "lower"},
                    "phone": {"column": "Mobile", "transform": "phone_e164"}},
         "unmapped": "attributes"}
    """

    __tablename__ = "source_mappings"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "entity_type"), SCHEMA)

    source_system: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSONB)


class ImportBatch(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = SCHEMA

    source_system: Mapped[str] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(32), comment="csv, excel, sql, emr_api")
    entity_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="received", comment="received, loaded, failed")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawRecord(IdMixin, TenantMixin, Base):
    __tablename__ = "raw_records"
    __table_args__ = SCHEMA

    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staging.import_batches.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="pending, loaded, skipped, error")
    error: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(comment="canonical row this became")
