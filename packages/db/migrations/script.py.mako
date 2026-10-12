"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Checklist for tenant-scoped tables (anything with tenant_id):
  enable_tenant_rls(op, "<schema>.<table>") after op.create_table(...)
New feature schema:
  create_schema_with_grants(op, "<schema>") before creating its tables
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
from clinic_db.rls import create_schema_with_grants, enable_tenant_rls  # noqa: F401

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
