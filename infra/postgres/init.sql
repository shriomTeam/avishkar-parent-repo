-- Runs once when the local Postgres volume is created.
-- clinic_app is the runtime role: it does not own tables, so row-level security
-- policies always apply to it. Grants are added by the Alembic migrations.
CREATE ROLE clinic_app LOGIN PASSWORD 'clinic_app';
GRANT CONNECT ON DATABASE clinic TO clinic_app;

-- clinic_system bypasses row-level security. It is used only by scheduler/relay
-- code that scans across tenants and then does the real work in a tenant session.
CREATE ROLE clinic_system LOGIN PASSWORD 'clinic_system' BYPASSRLS;
GRANT CONNECT ON DATABASE clinic TO clinic_system;
