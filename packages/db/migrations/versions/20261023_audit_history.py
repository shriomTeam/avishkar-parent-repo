"""Index workspace audit history for paginated date-range queries."""

from alembic import op

revision = "20261023_audit_history"
down_revision = "20261023_membership"
branch_labels = None
depends_on = None


def upgrade():
    # Avoid blocking audit inserts while an existing production history is indexed.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_audit_log_tenant_time_id",
            "audit_log",
            ["tenant_id", "occurred_at", "id"],
            schema="ops",
            postgresql_concurrently=True,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("ix_audit_log_tenant_time_id", table_name="audit_log", schema="ops", postgresql_concurrently=True)
