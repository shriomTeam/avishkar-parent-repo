"""Workspace invitations, session workspace selection and encrypted delivery queue."""

import sqlalchemy as sa
from alembic import op

from clinic_db.rls import enable_tenant_rls

revision = "20261023_membership"
down_revision = "51847416ab0c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auth_sessions", sa.Column("active_workspace_id", sa.UUID(), nullable=True), schema="auth")
    op.create_foreign_key(
        "fk_session_active_workspace",
        "auth_sessions",
        "tenants",
        ["active_workspace_id"],
        ["id"],
        source_schema="auth",
        referent_schema="core",
        ondelete="SET NULL",
    )
    op.add_column("auth_sessions", sa.Column("authenticated_email", sa.String(320), nullable=True), schema="auth")
    op.add_column(
        "auth_sessions",
        sa.Column("mailbox_authoritative", sa.Boolean(), server_default="false", nullable=False),
        schema="auth",
    )
    op.add_column(
        "oauth_transactions", sa.Column("invitation_context_hash", sa.String(64), nullable=True), schema="auth"
    )
    op.execute(
        "\nCREATE TABLE core.workspace_invitations (\n\temail VARCHAR(320) NOT NULL, \n\trole VARCHAR(32) NOT NULL, \n\tinvited_by UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tgeneration INTEGER NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_sent_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\taccepted_by UUID, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_workspace_invitations PRIMARY KEY (id), \n\tCONSTRAINT fk_workspace_invitations_invited_by_staff FOREIGN KEY(invited_by) REFERENCES core.staff (id), \n\tCONSTRAINT uq_workspace_invitations_token_hash UNIQUE (token_hash), \n\tCONSTRAINT fk_workspace_invitations_accepted_by_users FOREIGN KEY(accepted_by) REFERENCES auth.users (id), \n\tCONSTRAINT fk_workspace_invitations_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE auth.invitation_contexts (\n\ttoken_hash VARCHAR(64) NOT NULL, \n\tinvitation_id UUID NOT NULL, \n\tgeneration INTEGER NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tverification_hash VARCHAR(64), \n\tverification_expires_at TIMESTAMP WITH TIME ZONE, \n\tverification_user_id UUID, \n\tverification_sent_at TIMESTAMP WITH TIME ZONE, \n\tconsumed BOOLEAN NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_invitation_contexts PRIMARY KEY (id), \n\tCONSTRAINT uq_invitation_contexts_token_hash UNIQUE (token_hash), \n\tCONSTRAINT fk_invitation_contexts_invitation_id_workspace_invitations FOREIGN KEY(invitation_id) REFERENCES core.workspace_invitations (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_invitation_contexts_verification_user_id_users FOREIGN KEY(verification_user_id) REFERENCES auth.users (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE ops.email_deliveries (\n\tdeduplication_key VARCHAR(150) NOT NULL, \n\tpayload TEXT, \n\tinvitation_id UUID, \n\tgeneration INTEGER, \n\tstatus VARCHAR(24) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tprovider_message_id VARCHAR(200), \n\terror VARCHAR(80), \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_email_deliveries PRIMARY KEY (id), \n\tCONSTRAINT uq_email_deliveries_tenant_id_deduplication_key UNIQUE (tenant_id, deduplication_key), \n\tCONSTRAINT fk_email_deliveries_invitation_id_workspace_invitations FOREIGN KEY(invitation_id) REFERENCES core.workspace_invitations (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_email_deliveries_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES core.tenants (id) ON DELETE CASCADE\n)\n\n"
    )
    for table in ("core.workspace_invitations", "ops.email_deliveries"):
        enable_tenant_rls(op, table)
    op.execute(
        "ALTER TABLE core.workspace_invitations ADD CONSTRAINT ck_invitation_role CHECK (role IN ('office_manager','front_desk','provider','consultant'))"
    )
    op.execute(
        "ALTER TABLE core.workspace_invitations ADD CONSTRAINT ck_invitation_status CHECK (status IN ('pending','accepted','revoked','expired'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pending_invitation ON core.workspace_invitations(tenant_id,email) WHERE status='pending'"
    )
    op.create_index("ix_core_workspace_invitations_tenant_id", "workspace_invitations", ["tenant_id"], schema="core")
    op.create_index("ix_ops_email_deliveries_tenant_id", "email_deliveries", ["tenant_id"], schema="ops")
    op.execute("CREATE INDEX ix_email_due ON ops.email_deliveries(status,next_attempt_at)")
    op.add_column("calls", sa.Column("auth_session_id", sa.UUID(), nullable=True), schema="voice")
    op.create_foreign_key(
        "fk_call_auth_session",
        "calls",
        "auth_sessions",
        ["auth_session_id"],
        ["id"],
        source_schema="voice",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.execute(
        "GRANT SELECT(id,user_id,revoked_at,expires_at,active_workspace_id), UPDATE(active_workspace_id) ON auth.auth_sessions TO clinic_system"
    )
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON auth.invitation_contexts TO clinic_auth,clinic_system")
    op.execute(
        "GRANT SELECT,INSERT,UPDATE,DELETE ON core.workspace_invitations,ops.email_deliveries TO clinic_app,clinic_system"
    )


def downgrade():
    op.drop_column("calls", "auth_session_id", schema="voice")
    op.execute(
        "REVOKE SELECT(id,user_id,revoked_at,expires_at,active_workspace_id), UPDATE(active_workspace_id) ON auth.auth_sessions FROM clinic_system"
    )
    op.drop_table("email_deliveries", schema="ops")
    op.drop_table("invitation_contexts", schema="auth")
    op.drop_table("workspace_invitations", schema="core")
    op.drop_column("oauth_transactions", "invitation_context_hash", schema="auth")
    for column in ("mailbox_authoritative", "authenticated_email", "active_workspace_id"):
        op.drop_column("auth_sessions", column, schema="auth")
