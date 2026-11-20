"""WhatsApp agent: a clinic's connection, its conversations and their encrypted messages.

Revision ID: 20261119_whatsapp
Revises: 0282a1e9855e
"""

import sqlalchemy as sa
from alembic import op

from clinic_db.rls import enable_tenant_rls

revision = "20261119_whatsapp"
down_revision = "0282a1e9855e"
branch_labels = None
depends_on = None

TABLES = ["voice.whatsapp_accounts", "voice.whatsapp_conversations", "voice.whatsapp_messages"]


def _tenant():
    return sa.Column("tenant_id", sa.Uuid(), nullable=False)


def upgrade():
    op.create_table(
        "whatsapp_accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _tenant(),
        sa.Column(
            "phone_number_id",
            sa.String(64),
            nullable=False,
            comment="Meta's id for the number; routes incoming webhooks",
        ),
        sa.Column("display_number", sa.String(32), nullable=True, comment="The number as people see it"),
        sa.Column(
            "access_token_enc", sa.Text(), nullable=False, comment="Meta access token, encrypted; never returned"
        ),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False, comment="System instruction sent to the model"),
        sa.Column("greeting", sa.Text(), nullable=True, comment="Sent first when a new person writes in"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_whatsapp_accounts_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_accounts")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_whatsapp_accounts_tenant_id")),
        sa.UniqueConstraint("phone_number_id", name=op.f("uq_whatsapp_accounts_phone_number_id")),
        schema="voice",
    )
    op.create_index(op.f("ix_voice_whatsapp_accounts_tenant_id"), "whatsapp_accounts", ["tenant_id"], schema="voice")

    op.create_table(
        "whatsapp_conversations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _tenant(),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("contact_hash", sa.String(64), nullable=False, comment="Keyed hash of the person's WhatsApp number"),
        sa.Column("contact_number_enc", sa.Text(), nullable=False),
        sa.Column("contact_name_enc", sa.Text(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenants.id"],
            name=op.f("fk_whatsapp_conversations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["voice.whatsapp_accounts.id"],
            name=op.f("fk_whatsapp_conversations_account_id_whatsapp_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_conversations")),
        sa.UniqueConstraint(
            "account_id", "contact_hash", name=op.f("uq_whatsapp_conversations_account_id_contact_hash")
        ),
        schema="voice",
    )
    op.create_index(
        op.f("ix_voice_whatsapp_conversations_tenant_id"), "whatsapp_conversations", ["tenant_id"], schema="voice"
    )
    op.create_index(
        op.f("ix_voice_whatsapp_conversations_account_id"), "whatsapp_conversations", ["account_id"], schema="voice"
    )
    op.create_index(
        "ix_voice_whatsapp_conversations_tenant_last",
        "whatsapp_conversations",
        ["tenant_id", "last_message_at"],
        schema="voice",
    )

    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _tenant(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False, comment="inbound (the person) or outbound (the agent)"),
        sa.Column("provider_message_id", sa.String(128), nullable=True, comment="Meta's message id (wamid)"),
        sa.Column("body_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, comment="received, sent or failed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenants.id"], name=op.f("fk_whatsapp_messages_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["voice.whatsapp_conversations.id"],
            name=op.f("fk_whatsapp_messages_conversation_id_whatsapp_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_messages")),
        sa.UniqueConstraint(
            "tenant_id", "provider_message_id", name=op.f("uq_whatsapp_messages_tenant_id_provider_message_id")
        ),
        schema="voice",
    )
    op.create_index(op.f("ix_voice_whatsapp_messages_tenant_id"), "whatsapp_messages", ["tenant_id"], schema="voice")
    op.create_index(
        op.f("ix_voice_whatsapp_messages_conversation_id"), "whatsapp_messages", ["conversation_id"], schema="voice"
    )
    op.create_index(
        "ix_voice_whatsapp_messages_conversation_created",
        "whatsapp_messages",
        ["conversation_id", "created_at"],
        schema="voice",
    )

    for table in TABLES:
        enable_tenant_rls(op, table)


def downgrade():
    op.drop_table("whatsapp_messages", schema="voice")
    op.drop_table("whatsapp_conversations", schema="voice")
    op.drop_table("whatsapp_accounts", schema="voice")
