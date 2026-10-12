"""Migration helpers for schemas, grants and tenant row-level security.

Every migration that creates a tenant-scoped table must call
``enable_tenant_rls(op, "schema.table")``. ``check_rls_coverage`` (run in tests)
fails if a table with tenant_id was added without it.
"""

APP_ROLES = ("clinic_app", "clinic_system")

# The app sets this per transaction: SELECT set_config('app.tenant_id', '<uuid>', true)
_TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def create_schema_with_grants(op, schema: str) -> None:
    roles = ", ".join(APP_ROLES)
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {roles}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {roles}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {roles}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {roles}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {roles}")


def enable_tenant_rls(op, table: str, column: str = "tenant_id") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({column} = {_TENANT_EXPR}) WITH CHECK ({column} = {_TENANT_EXPR})"
    )


def disable_tenant_rls(op, table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


RLS_COVERAGE_SQL = """
SELECT n.nspname || '.' || c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
  AND NOT c.relrowsecurity
ORDER BY 1
"""
