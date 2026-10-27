"""Pause automatic onboarding trials while billing is not implemented.

Only clear enabled entitlements matching their trial workspace's exact end date.
Explicitly disabled products, independent entitlement expiries and suspended
workspaces are preserved. Historical end dates cannot be reconstructed afterward.
"""

from alembic import op

revision = "20261026_pause_trials"
down_revision = "20261024_email_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE core.tenant_features AS feature
        SET expires_at = NULL
        FROM core.tenants AS tenant
        WHERE feature.tenant_id = tenant.id
          AND tenant.status = 'trial'
          AND tenant.trial_ends_at IS NOT NULL
          AND feature.enabled = true
          AND feature.expires_at = tenant.trial_ends_at
    """)
    op.execute("""
        UPDATE core.tenants
        SET status = 'active', trial_ends_at = NULL
        WHERE status = 'trial' AND trial_ends_at IS NOT NULL
    """)


def downgrade():
    # Data-only policy change: do not invent expiry dates or revoke existing access
    # on rollback. Reintroducing billing requires a separate, explicit migration.
    pass
