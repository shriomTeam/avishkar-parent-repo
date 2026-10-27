"""messages, message_events and consent_records can be inserted, never changed or removed."""

import pytest
from lr_seed import seed
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clinic_core.database import system_session, tenant_session

APPEND_ONLY = ["messages", "message_events", "consent_records"]
CHANGES = ["UPDATE lead_response.{t} SET tenant_id = tenant_id", "DELETE FROM lead_response.{t}"]


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("change", CHANGES)
async def test_app_role_cannot_change_rows(make_tenant, table, change):
    tenant = await make_tenant()
    await seed(tenant)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(tenant) as s:
            await s.execute(text(change.format(t=table)))


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("change", CHANGES + ["TRUNCATE lead_response.{t}"])
async def test_system_role_cannot_change_rows(make_tenant, table, change):
    tenant = await make_tenant()
    await seed(tenant)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with system_session() as s:
            await s.execute(text(change.format(t=table)))


@pytest.mark.parametrize("role", ["app", "system"])
async def test_truncate_messages_cascade_is_refused_by_privilege(make_tenant, role):
    # Postgres checks the TRUNCATE right on messages before it runs any trigger, so the revoke is what stops it here.
    tenant = await make_tenant()
    await seed(tenant)
    with pytest.raises(DBAPIError, match="permission denied for table messages"):
        if role == "app":
            async with tenant_session(tenant) as s:
                await s.execute(text("TRUNCATE lead_response.messages CASCADE"))
        else:
            async with system_session() as s:
                await s.execute(text("TRUNCATE lead_response.messages CASCADE"))
    async with tenant_session(tenant) as s:
        assert await s.scalar(text("SELECT count(*) FROM lead_response.messages")) == 1


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("change", CHANGES + ["TRUNCATE lead_response.{t}"])
async def test_trigger_stops_even_the_owner(make_tenant, owner_engine, table, change):
    tenant = await make_tenant()
    await seed(tenant)
    # Truncating messages is refused by Postgres itself first (consent_records and message_events reference it).
    refused = "append-only|cannot truncate a table referenced" if table == "messages" else "append-only"
    with pytest.raises(DBAPIError, match=refused):
        with owner_engine.begin() as conn:
            conn.execute(text(change.format(t=table)))
    with owner_engine.begin() as conn:
        left = conn.execute(
            text(f"SELECT count(*) FROM lead_response.{table} WHERE tenant_id = CAST(:t AS uuid)"), {"t": str(tenant)}
        ).scalar()
    assert left == 1


async def test_inserting_still_works(make_tenant):
    tenant = await make_tenant()
    await seed(tenant)
    async with tenant_session(tenant) as s:
        for table in APPEND_ONLY:
            assert await s.scalar(text(f"SELECT count(*) FROM lead_response.{table}")) == 1


async def test_a_tenant_with_messages_cannot_be_deleted(make_tenant, owner_engine):
    # Documents what offboarding hits today: the cascade from core.tenants reaches messages and the trigger refuses.
    tenant = await make_tenant()
    await seed(tenant)
    with pytest.raises(DBAPIError, match="append-only"):
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM core.tenants WHERE id = CAST(:t AS uuid)"), {"t": str(tenant)})
    with owner_engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM core.tenants WHERE id = CAST(:t AS uuid)"), {"t": str(tenant)}
            ).scalar()
            == 1
        )
