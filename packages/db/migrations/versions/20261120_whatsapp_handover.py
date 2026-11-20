"""Let staff take over a WhatsApp chat: pause the agent, and record which messages a person wrote.

Revision ID: 20261120_wa_handover
Revises: 20261119_wa_knowledge
"""

import sqlalchemy as sa
from alembic import op

revision = "20261120_wa_handover"
down_revision = "20261119_wa_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "whatsapp_conversations",
        sa.Column(
            "agent_paused",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Staff took over this chat: the agent stores new messages but does not answer them",
        ),
        schema="voice",
    )
    op.add_column(
        "whatsapp_conversations", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True), schema="voice"
    )
    op.add_column("whatsapp_conversations", sa.Column("paused_by_staff_id", sa.Uuid(), nullable=True), schema="voice")
    op.create_foreign_key(
        op.f("fk_whatsapp_conversations_paused_by_staff_id_staff"),
        "whatsapp_conversations",
        "staff",
        ["paused_by_staff_id"],
        ["id"],
        source_schema="voice",
        referent_schema="core",
        ondelete="SET NULL",
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column(
            "sent_by_staff_id",
            sa.Uuid(),
            nullable=True,
            comment="Set when a staff member wrote this outbound message; empty means the agent wrote it",
        ),
        schema="voice",
    )
    op.create_foreign_key(
        op.f("fk_whatsapp_messages_sent_by_staff_id_staff"),
        "whatsapp_messages",
        "staff",
        ["sent_by_staff_id"],
        ["id"],
        source_schema="voice",
        referent_schema="core",
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        op.f("fk_whatsapp_messages_sent_by_staff_id_staff"), "whatsapp_messages", schema="voice", type_="foreignkey"
    )
    op.drop_column("whatsapp_messages", "sent_by_staff_id", schema="voice")
    op.drop_constraint(
        op.f("fk_whatsapp_conversations_paused_by_staff_id_staff"),
        "whatsapp_conversations",
        schema="voice",
        type_="foreignkey",
    )
    op.drop_column("whatsapp_conversations", "paused_by_staff_id", schema="voice")
    op.drop_column("whatsapp_conversations", "paused_at", schema="voice")
    op.drop_column("whatsapp_conversations", "agent_paused", schema="voice")
