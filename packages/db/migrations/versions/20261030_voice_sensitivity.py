"""Make voice speech-start sensitivity explicit per agent; preserve the pre-tuning HIGH default."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_voice_sensitivity"
down_revision = "0282a1e9855e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agents",
        sa.Column("speech_start_sensitivity", sa.String(16), nullable=False, server_default="high"),
        schema="voice",
    )
    op.create_check_constraint(
        op.f("ck_agents_speech_start_sensitivity"),
        "agents",
        "speech_start_sensitivity IN ('high', 'low')",
        schema="voice",
    )


def downgrade():
    op.drop_constraint(op.f("ck_agents_speech_start_sensitivity"), "agents", schema="voice", type_="check")
    op.drop_column("agents", "speech_start_sensitivity", schema="voice")
