"""GET /runs/{id}/summary: the numbers behind the summary report PDF. Totals and groups only, so the tests check
who may call it, that no patient data comes back, and that the audit entry holds counts alone."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Patient
from clinic_db.models.ops import AuditLog
from clinic_db.models.reactivation import Run, RunPatient, RunType
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.router import router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


SUMMARY = {
    "dormant_count": 5,
    "patients_total": 40,
    "new_revenue_low_cents": 120_000,
    "new_revenue_high_cents": 260_000,
    "unclassified_dormant": 1,
}


async def _run(tenant, *, status="completed", settings=None, version=0):
    async with tenant_session(tenant) as s:
        run = Run(
            tenant_id=tenant,
            trigger="manual",
            status=status,
            settings_version=version,
            settings=settings if settings is not None else {},
            summary=SUMMARY,
            finished_at=datetime.now(UTC) if status == "completed" else None,
        )
        s.add(run)
        await s.flush()
        s.add(
            RunType(
                tenant_id=tenant,
                run_id=run.id,
                type_key="one_and_done",
                patient_count=4,
                basis_total_cents=1_000_000,
                rate_low=0.08,
                rate_high=0.15,
                rate_source="assumed",
                revenue_low_cents=120_000,
                revenue_high_cents=260_000,
                revenue_kind="new",
            )
        )
        p = Patient(
            tenant_id=tenant, first_name="Zelda", last_name="Canaryname", email="zelda@secret.test", phone="5550102222"
        )
        s.add(p)
        await s.flush()
        s.add(
            RunPatient(
                tenant_id=tenant,
                run_id=run.id,
                patient_id=p.id,
                status="dormant",
                primary_type="one_and_done",
                visit_count=1,
                total_spend_cents=1000,
                revenue_basis_cents=20000,
                days_since_last_visit=300,
                last_visit_at=datetime.now(UTC) - timedelta(days=300),
                reasons=["One visit and no return"],
                points={},
            )
        )
        return run.id


async def test_totals_groups_and_settings_come_back_with_no_patient_data(client):
    t = await create_test_tenant()
    config = ReactivationSettings().model_dump(mode="json")
    config["dormant"]["min_days_since_visit"] = 200
    config["types"]["lapsed_high_value"]["spend_cents_min"] = 500_000
    run = await _run(t, settings=config, version=3)
    r = await client.get(f"/runs/{run}/summary", headers=_h(t))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"run_id", "finished_at", "settings_version", "settings_source", "settings", "summary", "types"}
    assert (body["settings_version"], body["settings_source"]) == (3, "saved")
    assert body["settings"]["dormant"]["min_days_since_visit"] == 200
    assert body["settings"]["types"]["lapsed_high_value"]["spend_cents_min"] == 500_000
    assert body["summary"]["dormant_count"] == 5
    rows = {x["type_key"]: x for x in body["types"]}
    assert rows["one_and_done"]["patient_count"] == 4 and rows["one_and_done"]["revenue_high_cents"] == 260_000
    assert "unclassified" in rows
    for secret in ("Zelda", "Canaryname", "secret.test", "5550102222", "One visit and no return"):
        assert secret not in r.text
    assert r.headers["cache-control"] == "no-store"


async def test_a_run_with_no_saved_settings_reports_the_standard_ones(client):
    t = await create_test_tenant()
    run = await _run(t)  # version 0, empty copy
    body = (await client.get(f"/runs/{run}/summary", headers=_h(t))).json()
    assert (body["settings_version"], body["settings_source"]) == (0, "defaults")
    assert body["settings"] == ReactivationSettings().model_dump(mode="json")


@pytest.mark.parametrize("role", ["front_desk", "provider", "consultant"])
async def test_only_the_owner_and_office_manager_may_download(client, role):
    t = await create_test_tenant()
    run = await _run(t)
    assert (await client.get(f"/runs/{run}/summary", headers=_h(t, role))).status_code == 403
    for ok in ("owner", "office_manager"):
        assert (await client.get(f"/runs/{run}/summary", headers=_h(t, ok))).status_code == 200


async def test_the_audit_entry_holds_counts_only(client):
    t = await create_test_tenant()
    run = await _run(t)
    await client.get(f"/runs/{run}/summary", headers={**_h(t), "X-Staff-Id": "alice"})
    async with tenant_session(t) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.summary_report.export"))).all()
    assert len(rows) == 1
    assert rows[0].actor_id == "alice" and rows[0].entity_id == run
    assert rows[0].details == {"dormant_count": 5, "groups": 2}  # one_and_done and unclassified
    assert "Zelda" not in str(rows[0].details)


async def test_unknown_unfinished_and_other_clinics_runs_are_refused(client):
    t, other = await create_test_tenant(), await create_test_tenant()
    assert (await client.get(f"/runs/{uuid.uuid4()}/summary", headers=_h(t))).status_code == 404
    queued = await _run(t, status="queued")
    assert (await client.get(f"/runs/{queued}/summary", headers=_h(t))).status_code == 409
    theirs = await _run(other)
    assert (await client.get(f"/runs/{theirs}/summary", headers=_h(t))).status_code == 404


async def test_a_stored_config_that_no_longer_validates_is_refused_not_guessed(client):
    t = await create_test_tenant()
    run = await _run(t, settings={"dormant": {"min_days_since_visit": 0}}, version=2)
    assert (await client.get(f"/runs/{run}/summary", headers=_h(t))).status_code == 409
