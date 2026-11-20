"""Let a clinic's WhatsApp agent look answers up in the clinic's knowledge base.

Revision ID: 20261119_wa_knowledge
Revises: 20261119_whatsapp
"""

import sqlalchemy as sa
from alembic import op

revision = "20261119_wa_knowledge"
down_revision = "20261119_whatsapp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "whatsapp_accounts",
        sa.Column(
            "use_knowledge",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="The agent may look answers up in the clinic's knowledge base",
        ),
        schema="voice",
    )


def downgrade():
    op.drop_column("whatsapp_accounts", "use_knowledge", schema="voice")
