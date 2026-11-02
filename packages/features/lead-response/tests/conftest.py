"""Fixtures for the lead response tests. Run against a migrated test database (never the dev one).

Append-only tables cannot be cleaned by the app roles, so tenants made through ``make_tenant`` are removed at the end of
the test by the owner role, which skips the triggers only for the delete of our own rows.
"""

import os
import uuid
from pathlib import Path

import httpx
import pytest
from lr_seed import TABLES
from sqlalchemy import create_engine, text

from clinic_core.settings import REPO_ROOT
from clinic_core.testing import create_test_tenant


def owner_url() -> str | None:
    url = os.environ.get("DATABASE_OWNER_URL")
    if url:
        return url
    env = Path(REPO_ROOT / ".env")
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("DATABASE_OWNER_URL="):
            return line.partition("=")[2].strip()
    return None


@pytest.fixture(scope="session")
def cleanup_engine():
    """The owner connection, or None. CI's "without voice" step copies the repo without .env and sets no owner URL,
    so there is no owner role there: cleanup is skipped (a disposable database, and each test uses its own tenants)."""
    url = owner_url()
    engine = create_engine(url) if url else None
    yield engine
    if engine is not None:
        engine.dispose()


@pytest.fixture(scope="session")
def owner_engine(cleanup_engine):
    if cleanup_engine is None:
        pytest.skip("DATABASE_OWNER_URL is not set; this test needs the owner role")
    return cleanup_engine


@pytest.fixture
async def make_tenant(cleanup_engine):
    made: list[uuid.UUID] = []

    async def make(features: tuple[str, ...] = ("lead_response",)) -> uuid.UUID:
        tenant = await create_test_tenant(features)
        made.append(tenant)
        return tenant

    yield make

    if cleanup_engine is None:
        return
    ids = [str(t) for t in made]
    with cleanup_engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        for table in TABLES:
            conn.execute(
                text(f"DELETE FROM lead_response.{table} WHERE tenant_id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}
            )
    with cleanup_engine.begin() as conn:
        conn.execute(text("DELETE FROM core.tenants WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids})


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """No test may reach the real network, so none can send a real SMS: the two real httpx transports refuse.
    ``httpx.MockTransport`` and ``httpx.ASGITransport`` are other classes and keep working."""

    async def refuse_async(self, request):
        raise AssertionError(f"a test tried to use the real network ({request.method} {request.url.host})")

    def refuse(self, request):
        raise AssertionError(f"a test tried to use the real network ({request.method} {request.url.host})")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
