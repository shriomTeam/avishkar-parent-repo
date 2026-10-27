import importlib.util
import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from clinic_core.database import system_session
from clinic_core.settings import REPO_ROOT

VERSIONS = REPO_ROOT / "packages/db/migrations/versions"
SCHEMA = "lead_response"


def _migration() -> Path:
    (path,) = VERSIONS.glob("*_lead_response_tables.py")
    return path


class _RecordingOp:
    """Stands in for alembic's ``op`` and records every schema and every SQL statement the migration issues."""

    def __init__(self):
        self.schemas: list[str] = []
        self.sql: list[str] = []

    def f(self, name):
        return name

    def execute(self, statement):
        self.sql.append(str(statement))

    def __getattr__(self, name):
        def record(*args, **kwargs):
            if "schema" in kwargs:
                self.schemas.append(kwargs["schema"])

        return record


def _run(direction: str) -> _RecordingOp:
    spec = importlib.util.spec_from_file_location("lead_response_migration", _migration())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder = _RecordingOp()
    module.op = recorder
    getattr(module, direction)()
    return recorder


def test_the_migration_touches_only_the_lead_response_schema():
    for direction in ("upgrade", "downgrade"):
        recorded = _run(direction)
        assert recorded.schemas, "no schema-qualified operation recorded"
        assert set(recorded.schemas) == {SCHEMA}
        for statement in recorded.sql:
            # Every table or function the SQL names must be ours (setting names like app.tenant_id are not objects).
            named = {m.group(1) for m in re.finditer(r"\b(?:ON|TABLE|FUNCTION|FROM|INTO)\s+([a-z_]+)\.", statement)}
            assert named <= {SCHEMA}, statement


def test_the_migration_has_a_downgrade_that_drops_what_upgrade_creates():
    up, down = _run("upgrade"), _run("downgrade")
    assert any("CREATE FUNCTION" in s for s in up.sql)
    assert any("DROP FUNCTION" in s for s in down.sql)


def test_there_is_a_single_migration_head():
    heads = ScriptDirectory.from_config(Config(str(REPO_ROOT / "packages/db/alembic.ini"))).get_heads()
    assert len(heads) == 1


async def test_the_migrated_database_has_all_tables_triggers_and_policies():
    async with system_session() as s:
        tables = set(
            (
                await s.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"), {"s": SCHEMA}
                )
            ).scalars()
        )
        policies = (
            await s.execute(text("SELECT count(*) FROM pg_policies WHERE schemaname = :s"), {"s": SCHEMA})
        ).scalar()
        triggers = (
            await s.execute(
                text(
                    "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :s AND NOT t.tgisinternal"
                ),
                {"s": SCHEMA},
            )
        ).scalar()
    assert tables == {
        "contacts",
        "contact_identities",
        "conversations",
        "messages",
        "message_events",
        "consent_records",
        "tasks",
        "jobs",
        "practice_settings",
    }
    assert policies == 9
    assert triggers == 6
