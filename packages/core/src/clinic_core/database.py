"""Database sessions.

``tenant_session`` is what all feature code uses: it connects as the non-owner
``clinic_app`` role and pins the transaction to one tenant, so Postgres row-level
security hides every other tenant's rows even if a query forgets a WHERE clause.

``system_session`` bypasses RLS and is reserved for platform loops that must scan
across tenants (outbox relay, due-enrollment scans, tenant provisioning). They
should find work there and do it inside a ``tenant_session``.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from clinic_core.settings import get_settings

_engines: list[AsyncEngine] = []


@lru_cache
def _app_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url, pool_pre_ping=True)
    _engines.append(engine)
    return engine


@lru_cache
def _system_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=2)
    _engines.append(engine)
    return engine


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID, *, database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    """One transaction scoped to one tenant. Commits on success, rolls back on error."""
    maker = async_sessionmaker(_app_engine(database_url or get_settings().database_url), expire_on_commit=False)
    async with maker() as session, session.begin():
        await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})
        session.info["tenant_id"] = tenant_id
        yield session


@asynccontextmanager
async def system_session(*, database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(
        _system_engine(database_url or get_settings().database_system_url), expire_on_commit=False
    )
    async with maker() as session, session.begin():
        yield session


def current_tenant(session: AsyncSession) -> uuid.UUID:
    try:
        return session.info["tenant_id"]
    except KeyError:
        raise RuntimeError("This operation needs a tenant_session()") from None


async def dispose_engines() -> None:
    for engine in _engines:
        await engine.dispose()
    _engines.clear()
    _app_engine.cache_clear()
    _system_engine.cache_clear()
