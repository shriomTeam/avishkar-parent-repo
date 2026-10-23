"""``knowledge`` schema: a clinic's documents and the passages they are split into.

Deleting a document deletes its passages (``ON DELETE CASCADE``), so nothing searchable outlives the file.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "knowledge"}
EMBEDDING_DIMENSIONS = 768


class Document(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash"),
        Index("ix_knowledge_documents_tenant_text_hash", "tenant_id", "text_hash"),
        SCHEMA,
    )

    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), comment="SHA-256 of the uploaded file")
    text_hash: Mapped[str | None] = mapped_column(String(64), comment="SHA-256 of the cleaned-up extracted text")
    status: Mapped[str] = mapped_column(
        String(16),
        default="uploaded",
        server_default="uploaded",
        comment="uploaded, processing, ready, failed, duplicate",
    )
    error: Mapped[str | None] = mapped_column(String(300), comment="A plain-words reason when status is failed")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    object_name: Mapped[str] = mapped_column(String(400), comment="Object in the files bucket, under knowledge-base/")
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge.documents.id", ondelete="SET NULL"), comment="The older version this one will replace"
    )
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge.documents.id", ondelete="SET NULL"), comment="The document with the same text"
    )
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.staff.id", ondelete="SET NULL"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal"),
        Index("ix_knowledge_chunks_tenant_text_hash", "tenant_id", "text_hash"),
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        SCHEMA,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge.documents.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(300), comment="The section this passage sits under")
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), comment="SHA-256 of the cleaned-up passage text")
    token_estimate: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(EMBEDDING_DIMENSIONS))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True))
