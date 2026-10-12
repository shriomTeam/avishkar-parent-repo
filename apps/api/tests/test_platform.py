import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from clinic_core.database import system_session, tenant_session
from clinic_db.models.core import Patient
from clinic_db.rls import RLS_COVERAGE_SQL
from clinic_integrations import run_import, suggest_mapping
from clinic_integrations.loader import ImportBlocked
from clinic_integrations.sources import CsvSource


async def test_every_tenant_table_has_rls():
    async with system_session() as s:
        uncovered = (await s.execute(text(RLS_COVERAGE_SQL))).scalars().all()
    assert uncovered == [], f"tables with tenant_id but no RLS (add enable_tenant_rls to the migration): {uncovered}"


async def test_tenants_cannot_see_each_other(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    async with tenant_session(a) as s:
        s.add(Patient(tenant_id=a, first_name="Only", last_name="InA", email="a@example.com"))
    async with tenant_session(b) as s:
        # No WHERE tenant_id clause on purpose: RLS must do the filtering.
        assert await s.scalar(select(func.count()).select_from(Patient)) == 0
    async with tenant_session(a) as s:
        assert await s.scalar(select(func.count()).select_from(Patient)) == 1


async def test_tenant_cannot_write_into_another_tenant(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a) as s:
            s.add(Patient(tenant_id=b, first_name="Sneaky"))


async def test_import_is_idempotent(make_tenant, sample):
    tenant = await make_tenant()
    source = CsvSource(sample("patients.csv"))
    mapping = suggest_mapping("patient", source.headers())
    async with tenant_session(tenant) as s:
        first = await run_import(s, source=source, source_system="emr_x", entity_type="patient", mapping=mapping)
    async with tenant_session(tenant) as s:
        second = await run_import(s, source=source, source_system="emr_x", entity_type="patient", mapping=mapping)
        count = await s.scalar(select(func.count()).select_from(Patient))
    assert first.created == 240 and first.error_count == 0
    assert second.created == 0 and second.updated == 240
    assert count == 240


async def test_import_requires_signed_baa(make_tenant, sample):
    tenant = await make_tenant(baa=False)
    source = CsvSource(sample("patients.csv"))
    with pytest.raises(ImportBlocked, match="BAA"):
        async with tenant_session(tenant) as s:
            await run_import(
                s,
                source=source,
                source_system="emr_x",
                entity_type="patient",
                mapping=suggest_mapping("patient", source.headers()),
            )


async def test_feature_routes_are_gated_by_entitlement(make_tenant, client):
    without = await make_tenant(features=("blueprints",))
    with_it = await make_tenant(features=("reactivation",))
    r = await client.get("/features/reactivation/preview", headers={"X-Tenant-Id": str(without)})
    assert r.status_code == 403
    r = await client.get("/features/reactivation/preview", headers={"X-Tenant-Id": str(with_it)})
    assert r.status_code == 200


async def test_me_lists_only_enabled_nav(make_tenant, client):
    tenant = await make_tenant(features=("reactivation",))
    r = await client.get("/me", headers={"X-Tenant-Id": str(tenant)})
    assert r.status_code == 200
    body = r.json()
    assert [n["feature"] for n in body["nav"]] == ["reactivation"]
    assert {f["key"] for f in body["features"]} >= {"reactivation", "blueprints", "scribe"}
