"""Let custom voice tools send a payload built from captured details, model arguments and call facts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261027_tool_template"
down_revision = "305f028abc4d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tools",
        sa.Column(
            "payload_template",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Request body with {{field.x}}, {{arg.x}}, {{call.x}} placeholders; null sends the arguments",
        ),
        schema="voice",
    )


def downgrade():
    op.drop_column("tools", "payload_template", schema="voice")
