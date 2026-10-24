"""Track durable Cloud Tasks dispatch reservations and recovery generations."""

import sqlalchemy as sa
from alembic import op

revision = "20261024_email_tasks"
down_revision = "20261023_audit_history"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "email_deliveries", sa.Column("task_dispatch_at", sa.DateTime(timezone=True), nullable=True), schema="ops"
    )
    op.add_column(
        "email_deliveries", sa.Column("task_generation", sa.Integer(), nullable=False, server_default="0"), schema="ops"
    )


def downgrade():
    op.drop_column("email_deliveries", "task_generation", schema="ops")
    op.drop_column("email_deliveries", "task_dispatch_at", schema="ops")
