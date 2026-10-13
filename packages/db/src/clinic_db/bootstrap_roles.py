"""Create the runtime database roles (clinic_app, clinic_system) before migrations run.

Locally ``infra/postgres/init.sql`` does this. On Cloud SQL the migration job runs this first,
as the owner role. Safe to re-run: roles that already exist are left untouched (passwords are never changed).
"""

import os
import sys

import psycopg
from psycopg import sql

# (role, password env var, bypasses row-level security)
ROLES = [
    ("clinic_app", "CLINIC_APP_PASSWORD", False),
    ("clinic_system", "CLINIC_SYSTEM_PASSWORD", True),
]


def main() -> int:
    owner_url = os.environ["DATABASE_OWNER_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(owner_url, autocommit=True) as conn:
        for role, password_var, bypass_rls in ROLES:
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if not exists:
                attrs = sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(os.environ[password_var]))
                if bypass_rls:
                    attrs = sql.SQL("{} BYPASSRLS").format(attrs)
                conn.execute(sql.SQL("CREATE ROLE {} {}").format(sql.Identifier(role), attrs))
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(conn.info.dbname), sql.Identifier(role)
                )
            )
            print(f"role {role}: {'already exists' if exists else 'created'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
