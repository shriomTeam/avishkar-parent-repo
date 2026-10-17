"""add reviews tables

Revision ID: e4a91c0b7d22
Revises: c960f111b68d
Create Date: 2026-10-17 22:20:00.000000

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from clinic_db.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "e4a91c0b7d22"
down_revision: str | None = "c960f111b68d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, comment="draft, active, paused"),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment="ordered: sms, email"),
        sa.Column("fallback_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "included_service_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "excluded_service_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("frequency_days", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_campaigns_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
        schema="reviews",
    )
    op.create_index(op.f("ix_reviews_campaigns_tenant_id"), "campaigns", ["tenant_id"], unique=False, schema="reviews")
    enable_tenant_rls(op, "reviews.campaigns")

    op.create_table(
        "integrations",
        sa.Column("listing_name", sa.String(length=200), nullable=True),
        sa.Column("google_review_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment="not_connected, connected, disconnected",
        ),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_integrations_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_integrations_tenant_id")),
        schema="reviews",
    )
    op.create_index(
        op.f("ix_reviews_integrations_tenant_id"), "integrations", ["tenant_id"], unique=False, schema="reviews"
    )
    enable_tenant_rls(op, "reviews.integrations")

    op.create_table(
        "requests",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=True, comment="sms, email"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment="scheduled, processing, submitted, skipped, cancelled, failed_permanent, completed",
        ),
        sa.Column("skip_reason", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "public_token",
            sa.String(length=64),
            server_default=sa.text("encode(gen_random_bytes(24), 'hex')"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["core.appointments.id"],
            name=op.f("fk_requests_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["reviews.campaigns.id"], name=op.f("fk_requests_campaign_id_campaigns"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["core.patients.id"], name=op.f("fk_requests_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_requests_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
        sa.UniqueConstraint("public_token", name=op.f("uq_requests_public_token")),
        sa.UniqueConstraint(
            "tenant_id",
            "appointment_id",
            "campaign_id",
            name=op.f("uq_requests_tenant_id_appointment_id_campaign_id"),
        ),
        schema="reviews",
    )
    op.create_index(op.f("ix_reviews_requests_tenant_id"), "requests", ["tenant_id"], unique=False, schema="reviews")
    op.create_index(op.f("ix_reviews_requests_campaign_id"), "requests", ["campaign_id"], unique=False, schema="reviews")
    op.create_index(
        op.f("ix_reviews_requests_appointment_id"), "requests", ["appointment_id"], unique=False, schema="reviews"
    )
    op.create_index(op.f("ix_reviews_requests_patient_id"), "requests", ["patient_id"], unique=False, schema="reviews")
    op.create_index(op.f("ix_reviews_requests_scheduled_at"), "requests", ["scheduled_at"], unique=False, schema="reviews")
    op.create_index(
        "ix_reviews_requests_due",
        "requests",
        ["tenant_id", "status", "scheduled_at"],
        unique=False,
        schema="reviews",
    )
    enable_tenant_rls(op, "reviews.requests")

    op.create_table(
        "feedback",
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("google_review_offered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("google_review_clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["core.patients.id"], name=op.f("fk_feedback_patient_id_patients"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["reviews.requests.id"], name=op.f("fk_feedback_request_id_requests"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_feedback_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("request_id", name=op.f("uq_feedback_request_id")),
        schema="reviews",
    )
    op.create_index(op.f("ix_reviews_feedback_tenant_id"), "feedback", ["tenant_id"], unique=False, schema="reviews")
    op.create_index(op.f("ix_reviews_feedback_request_id"), "feedback", ["request_id"], unique=False, schema="reviews")
    op.create_index(op.f("ix_reviews_feedback_patient_id"), "feedback", ["patient_id"], unique=False, schema="reviews")
    enable_tenant_rls(op, "reviews.feedback")

    op.create_table(
        "follow_up_tasks",
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, comment="pending, resolved"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["reviews.feedback.id"],
            name=op.f("fk_follow_up_tasks_feedback_id_feedback"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_follow_up_tasks_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_follow_up_tasks")),
        schema="reviews",
    )
    op.create_index(
        op.f("ix_reviews_follow_up_tasks_tenant_id"), "follow_up_tasks", ["tenant_id"], unique=False, schema="reviews"
    )
    op.create_index(
        op.f("ix_reviews_follow_up_tasks_feedback_id"),
        "follow_up_tasks",
        ["feedback_id"],
        unique=False,
        schema="reviews",
    )
    enable_tenant_rls(op, "reviews.follow_up_tasks")


def downgrade() -> None:
    disable_tenant_rls(op, "reviews.follow_up_tasks")
    op.drop_index(op.f("ix_reviews_follow_up_tasks_feedback_id"), table_name="follow_up_tasks", schema="reviews")
    op.drop_index(op.f("ix_reviews_follow_up_tasks_tenant_id"), table_name="follow_up_tasks", schema="reviews")
    op.drop_table("follow_up_tasks", schema="reviews")
    disable_tenant_rls(op, "reviews.feedback")
    op.drop_index(op.f("ix_reviews_feedback_patient_id"), table_name="feedback", schema="reviews")
    op.drop_index(op.f("ix_reviews_feedback_request_id"), table_name="feedback", schema="reviews")
    op.drop_index(op.f("ix_reviews_feedback_tenant_id"), table_name="feedback", schema="reviews")
    op.drop_table("feedback", schema="reviews")
    disable_tenant_rls(op, "reviews.requests")
    op.drop_index("ix_reviews_requests_due", table_name="requests", schema="reviews")
    op.drop_index(op.f("ix_reviews_requests_scheduled_at"), table_name="requests", schema="reviews")
    op.drop_index(op.f("ix_reviews_requests_patient_id"), table_name="requests", schema="reviews")
    op.drop_index(op.f("ix_reviews_requests_appointment_id"), table_name="requests", schema="reviews")
    op.drop_index(op.f("ix_reviews_requests_campaign_id"), table_name="requests", schema="reviews")
    op.drop_index(op.f("ix_reviews_requests_tenant_id"), table_name="requests", schema="reviews")
    op.drop_table("requests", schema="reviews")
    disable_tenant_rls(op, "reviews.integrations")
    op.drop_index(op.f("ix_reviews_integrations_tenant_id"), table_name="integrations", schema="reviews")
    op.drop_table("integrations", schema="reviews")
    disable_tenant_rls(op, "reviews.campaigns")
    op.drop_index(op.f("ix_reviews_campaigns_tenant_id"), table_name="campaigns", schema="reviews")
    op.drop_table("campaigns", schema="reviews")
