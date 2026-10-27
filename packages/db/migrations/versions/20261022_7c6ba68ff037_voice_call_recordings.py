"""voice call recordings

Revision ID: 7c6ba68ff037
Revises: 043059e5b093
Create Date: 2026-10-22 06:22:38.501349

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from clinic_db.rls import create_schema_with_grants, enable_tenant_rls  # noqa: F401

revision: str = "7c6ba68ff037"
down_revision: str | None = "043059e5b093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "save_recording",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Keep the call audio; off unless chosen",
        ),
        schema="voice",
    )
    op.add_column(
        "calls",
        sa.Column(
            "recording_object",
            sa.String(length=300),
            nullable=True,
            comment="Object name in the files bucket, voice-recordings/<tenant_id>/<call_id>.wav",
        ),
        schema="voice",
    )
    op.add_column(
        "calls",
        sa.Column(
            "recording_status",
            sa.String(length=16),
            nullable=True,
            comment="saved or failed; null when the agent did not record this call",
        ),
        schema="voice",
    )


def downgrade() -> None:
    op.drop_column("calls", "recording_status", schema="voice")
    op.drop_column("calls", "recording_object", schema="voice")
    op.drop_column("agents", "save_recording", schema="voice")
