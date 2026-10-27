"""voice phone numbers

Revision ID: 305f028abc4d
Revises: 20261026_pause_trials
Create Date: 2026-10-24 19:31:49.619909

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from clinic_db.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "305f028abc4d"
down_revision: str | None = "20261026_pause_trials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phone_numbers",
        sa.Column("number", sa.String(length=20), nullable=False, comment="E.164, for example +14155550123"),
        sa.Column("provider", sa.String(length=16), server_default="twilio", nullable=False),
        sa.Column(
            "provider_sid",
            sa.String(length=64),
            nullable=False,
            comment="The provider's id for the number (Twilio PN...)",
        ),
        sa.Column("kind", sa.String(length=16), nullable=False, comment="local or toll_free"),
        sa.Column("agent_id", sa.UUID(), nullable=True, comment="The agent that answers; none = unassigned"),
        sa.Column("purchased_by_staff_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["voice.agents.id"], name=op.f("fk_phone_numbers_agent_id_agents"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["purchased_by_staff_id"],
            ["core.staff.id"],
            name=op.f("fk_phone_numbers_purchased_by_staff_id_staff"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_phone_numbers_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_numbers")),
        sa.UniqueConstraint("number", name=op.f("uq_phone_numbers_number")),
        sa.UniqueConstraint("provider_sid", name=op.f("uq_phone_numbers_provider_sid")),
        schema="voice",
    )
    enable_tenant_rls(op, "voice.phone_numbers")
    op.create_index(
        op.f("ix_voice_phone_numbers_agent_id"), "phone_numbers", ["agent_id"], unique=False, schema="voice"
    )
    op.create_index(
        op.f("ix_voice_phone_numbers_tenant_id"), "phone_numbers", ["tenant_id"], unique=False, schema="voice"
    )


def downgrade() -> None:
    disable_tenant_rls(op, "voice.phone_numbers")
    op.drop_index(op.f("ix_voice_phone_numbers_tenant_id"), table_name="phone_numbers", schema="voice")
    op.drop_index(op.f("ix_voice_phone_numbers_agent_id"), table_name="phone_numbers", schema="voice")
    op.drop_table("phone_numbers", schema="voice")
