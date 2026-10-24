"""voice variables

Revision ID: 51847416ab0c
Revises: 7c6ba68ff037
Create Date: 2026-10-22 22:01:15.429876

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from clinic_db.rls import disable_tenant_rls, enable_tenant_rls

revision: str = "51847416ab0c"
down_revision: str | None = "7c6ba68ff037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "variables",
        sa.Column(
            "name",
            sa.String(length=64),
            nullable=False,
            comment="snake_case, used as {{name}}; never changes after creation",
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_variables_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variables")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_variables_tenant_id_name")),
        schema="voice",
    )
    op.create_index(op.f("ix_voice_variables_tenant_id"), "variables", ["tenant_id"], unique=False, schema="voice")
    enable_tenant_rls(op, "voice.variables")


def downgrade() -> None:
    disable_tenant_rls(op, "voice.variables")
    op.drop_index(op.f("ix_voice_variables_tenant_id"), table_name="variables", schema="voice")
    op.drop_table("variables", schema="voice")
