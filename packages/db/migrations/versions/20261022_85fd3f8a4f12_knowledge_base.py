"""knowledge base

Revision ID: 85fd3f8a4f12
Revises: 51847416ab0c
Create Date: 2026-10-22 23:41:13.762690

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from clinic_db.rls import create_schema_with_grants, disable_tenant_rls, enable_tenant_rls

TENANT_TABLES = ["knowledge.documents", "knowledge.chunks"]

revision: str = "85fd3f8a4f12"
down_revision: str | None = "51847416ab0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    create_schema_with_grants(op, "knowledge")
    op.create_table(
        "documents",
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, comment="SHA-256 of the uploaded file"),
        sa.Column("text_hash", sa.String(length=64), nullable=True, comment="SHA-256 of the cleaned-up extracted text"),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="uploaded",
            nullable=False,
            comment="uploaded, processing, ready, failed, duplicate",
        ),
        sa.Column("error", sa.String(length=300), nullable=True, comment="A plain-words reason when status is failed"),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "object_name",
            sa.String(length=400),
            nullable=False,
            comment="Object in the files bucket, under knowledge-base/",
        ),
        sa.Column("replaces_id", sa.UUID(), nullable=True, comment="The older version this one will replace"),
        sa.Column("duplicate_of_id", sa.UUID(), nullable=True, comment="The document with the same text"),
        sa.Column("created_by_staff_id", sa.UUID(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_staff_id"],
            ["core.staff.id"],
            name=op.f("fk_documents_created_by_staff_id_staff"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["knowledge.documents.id"],
            name=op.f("fk_documents_duplicate_of_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaces_id"],
            ["knowledge.documents.id"],
            name=op.f("fk_documents_replaces_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_documents_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("tenant_id", "content_hash", name=op.f("uq_documents_tenant_id_content_hash")),
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_knowledge_documents_tenant_id"), "documents", ["tenant_id"], unique=False, schema="knowledge"
    )
    op.create_index(
        "ix_knowledge_documents_tenant_text_hash",
        "documents",
        ["tenant_id", "text_hash"],
        unique=False,
        schema="knowledge",
    )
    op.create_table(
        "chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=300), nullable=True, comment="The section this passage sits under"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False, comment="SHA-256 of the cleaned-up passage text"),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.halfvec.HALFVEC(dim=768), nullable=False),
        sa.Column(
            "tsv", postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', text)", persisted=True), nullable=True
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge.documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_chunks_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("document_id", "ordinal", name=op.f("uq_chunks_document_id_ordinal")),
        schema="knowledge",
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_id"), "chunks", ["document_id"], unique=False, schema="knowledge"
    )
    op.create_index(op.f("ix_knowledge_chunks_tenant_id"), "chunks", ["tenant_id"], unique=False, schema="knowledge")
    op.create_index(
        "ix_knowledge_chunks_tenant_text_hash", "chunks", ["tenant_id", "text_hash"], unique=False, schema="knowledge"
    )
    op.create_index(
        "ix_knowledge_chunks_tsv", "chunks", ["tsv"], unique=False, schema="knowledge", postgresql_using="gin"
    )
    for table in TENANT_TABLES:
        enable_tenant_rls(op, table)


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        disable_tenant_rls(op, table)
    op.drop_index("ix_knowledge_chunks_tsv", table_name="chunks", schema="knowledge", postgresql_using="gin")
    op.drop_index("ix_knowledge_chunks_tenant_text_hash", table_name="chunks", schema="knowledge")
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="chunks", schema="knowledge")
    op.drop_index(op.f("ix_knowledge_chunks_document_id"), table_name="chunks", schema="knowledge")
    op.drop_table("chunks", schema="knowledge")
    op.drop_index("ix_knowledge_documents_tenant_text_hash", table_name="documents", schema="knowledge")
    op.drop_index(op.f("ix_knowledge_documents_tenant_id"), table_name="documents", schema="knowledge")
    op.drop_table("documents", schema="knowledge")
    op.execute("DROP SCHEMA IF EXISTS knowledge")
