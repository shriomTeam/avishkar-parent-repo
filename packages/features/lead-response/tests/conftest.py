"""Fixtures for the lead response tests. Run against a migrated test database (never the dev one).

Append-only tables cannot be cleaned by the app roles, so tenants made through ``make_tenant`` are removed at the end of
the test by the owner role, which skips the triggers only for the delete of our own rows.
"""

import os
import uuid
from pathlib import Path

import pytest
from lr_seed import TABLES
from sqlalchemy import create_engine, text

from clinic_core.settings import REPO_ROOT
from clinic_core.testing import create_test_tenant


def owner_url() -> str:
    url = os.environ.get("DATABASE_OWNER_URL")
    if url:
        return url
    env = Path(REPO_ROOT / ".env")
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("DATABASE_OWNER_URL="):
            return line.partition("=")[2].strip()
    raise RuntimeError("DATABASE_OWNER_URL is not set")


@pytest.fixture(scope="session")
def owner_engine():
    engine = create_engine(owner_url())
    yield engine
    engine.dispose()


@pytest.fixture
async def make_tenant(owner_engine):
    made: list[uuid.UUID] = []

    async def make(features: tuple[str, ...] = ("lead_response",)) -> uuid.UUID:
        tenant = await create_test_tenant(features)
        made.append(tenant)
        return tenant

    yield make

    ids = [str(t) for t in made]
    with owner_engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        for table in TABLES:
            conn.execute(
                text(f"DELETE FROM lead_response.{table} WHERE tenant_id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}
            )
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM core.tenants WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids})
