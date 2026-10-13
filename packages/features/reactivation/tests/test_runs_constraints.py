import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from clinic_core.database import system_session, tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.reactivation import Run, Settings
from clinic_db.rls import RLS_COVERAGE_SQL


def _run(tenant, status="queued", **kw):
    return Run(tenant_id=tenant, trigger="manual", status=status, settings_version=0, settings={}, **kw)


async def _add(tenant, *runs):
    async with tenant_session(tenant) as s:
        s.add_all(runs)


async def test_second_running_run_for_a_tenant_fails():
    t = await create_test_tenant()
    await _add(t, _run(t, "running"))
    with pytest.raises(IntegrityError, match="uq_runs_one_running"):
        await _add(t, _run(t, "running"))


async def test_second_queued_run_for_a_tenant_fails():
    t = await create_test_tenant()
    await _add(t, _run(t, "queued"))
    with pytest.raises(IntegrityError, match="uq_runs_one_queued"):
        await _add(t, _run(t, "queued"))


async def test_one_running_and_one_queued_coexist_and_finished_runs_are_unlimited():
    t = await create_test_tenant()
    await _add(t, _run(t, "running"), _run(t, "queued"), _run(t, "completed"), _run(t, "completed"))


async def test_another_tenant_has_its_own_running_and_queued_run():
    a, b = await create_test_tenant(), await create_test_tenant()
    await _add(a, _run(a, "running"), _run(a, "queued"))
    await _add(b, _run(b, "running"), _run(b, "queued"))


async def test_same_idempotency_key_for_one_tenant_fails():
    t = await create_test_tenant()
    await _add(t, _run(t, "completed", idempotency_key="k1"))
    with pytest.raises(IntegrityError, match="uq_runs_idem"):
        await _add(t, _run(t, "completed", idempotency_key="k1"))


async def test_idempotency_key_may_repeat_across_tenants_and_be_null():
    a, b = await create_test_tenant(), await create_test_tenant()
    await _add(a, _run(a, "completed", idempotency_key="k"), _run(a, "completed"), _run(a, "completed"))
    await _add(b, _run(b, "completed", idempotency_key="k"))


async def test_no_settings_row_exists_for_a_new_tenant():
    t = await create_test_tenant()
    async with tenant_session(t) as s:
        assert (await s.scalars(select(Settings))).all() == []


async def test_reactivation_tables_have_rls():
    async with system_session() as s:
        uncovered = (await s.execute(text(RLS_COVERAGE_SQL))).scalars().all()
    assert [t for t in uncovered if t.startswith("reactivation.")] == []
