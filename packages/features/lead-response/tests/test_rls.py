"""Tenant isolation for every lead_response table."""

import pytest
from conftest import TABLES
from lr_seed import seed
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from clinic_core.database import tenant_session
from clinic_core.settings import get_settings

APPEND_ONLY = {"messages", "message_events", "consent_records"}


@pytest.mark.parametrize("table", TABLES)
async def test_tenant_b_cannot_read_tenant_a_rows(make_tenant, table):
    a, b = await make_tenant(), await make_tenant()
    await seed(a)
    async with tenant_session(a) as s:
        assert await s.scalar(text(f"SELECT count(*) FROM lead_response.{table}")) >= 1
    async with tenant_session(b) as s:
        # No WHERE tenant_id on purpose: row-level security must do the filtering.
        assert await s.scalar(text(f"SELECT count(*) FROM lead_response.{table}")) == 0


@pytest.mark.parametrize("table", [t for t in TABLES if t not in APPEND_ONLY])
async def test_tenant_b_cannot_update_or_delete_tenant_a_rows(make_tenant, table):
    a, b = await make_tenant(), await make_tenant()
    await seed(a)
    async with tenant_session(b) as s:
        assert (await s.execute(text(f"UPDATE lead_response.{table} SET tenant_id = tenant_id"))).rowcount == 0
        assert (await s.execute(text(f"DELETE FROM lead_response.{table}"))).rowcount == 0
    async with tenant_session(a) as s:
        assert await s.scalar(text(f"SELECT count(*) FROM lead_response.{table}")) >= 1


@pytest.mark.parametrize("table", sorted(APPEND_ONLY))
async def test_append_only_tables_refuse_tenant_b_update_and_delete(make_tenant, table):
    # The app roles hold no UPDATE or DELETE right on these tables, so the attempt fails before row security applies.
    a, b = await make_tenant(), await make_tenant()
    await seed(a)
    for sql in (f"UPDATE lead_response.{table} SET tenant_id = tenant_id", f"DELETE FROM lead_response.{table}"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with tenant_session(b) as s:
                await s.execute(text(sql))


@pytest.mark.parametrize("table", TABLES)
async def test_no_tenant_set_returns_nothing(make_tenant, table):
    a = await make_tenant()
    await seed(a)
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as s:
            assert await s.scalar(text(f"SELECT count(*) FROM lead_response.{table}")) == 0
    finally:
        await engine.dispose()


async def test_tenant_cannot_write_a_row_for_another_tenant(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as s:
            await s.execute(
                text("INSERT INTO lead_response.contacts (tenant_id) VALUES (CAST(:t AS uuid))"), {"t": str(b)}
            )
