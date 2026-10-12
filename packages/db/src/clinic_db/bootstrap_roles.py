"""Create the runtime database roles (clinic_app, clinic_system) before migrations run.

Locally ``infra/postgres/init.sql`` does this. On Cloud SQL the migration job runs this first,
as the owner role. Safe to re-run: existing roles only get their password refreshed.
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
            password = sql.Literal(os.environ[password_var])
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            attrs = sql.SQL("LOGIN PASSWORD {}").format(password)
            if not exists and bypass_rls:
                attrs = sql.SQL("{} BYPASSRLS").format(attrs)
            conn.execute(sql.SQL("{} ROLE {} {}").format(sql.SQL(verb), sql.Identifier(role), attrs))
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(conn.info.dbname), sql.Identifier(role)
                )
            )
            print(f"role {role}: {'updated' if exists else 'created'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
