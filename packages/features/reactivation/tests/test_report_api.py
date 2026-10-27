"""GET /runs/{id}/report: the rows behind the Export report button. Names are patient data, so who may call it, whose
data it returns and what it writes to the audit log are tested as carefully as the rows themselves."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Patient, Service
from clinic_db.models.ops import AuditLog
from clinic_db.models.reactivation import Run, RunPatient, RunType
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


async def _run(tenant, status="completed"):
    async with tenant_session(tenant) as s:
        run = Run(
            tenant_id=tenant,
            trigger="manual",
            status=status,
            settings_version=0,
            settings={},
            finished_at=datetime.now(UTC) if status == "completed" else None,
        )
        s.add(run)
        await s.flush()
        s.add(
            RunType(
                tenant_id=tenant,
                run_id=run.id,
                type_key="one_and_done",
                patient_count=0,
                basis_total_cents=0,
                rate_low=0.08,
                rate_high=0.15,
                rate_source="assumed",
                revenue_low_cents=0,
                revenue_high_cents=0,
                revenue_kind="new",
            )
        )
        return run.id


async def _patient(tenant, run_id, first, last, service=None, **kw):
    async with tenant_session(tenant) as s:
        p = Patient(
            tenant_id=tenant, first_name=first, last_name=last, email=f"{first}@secret.test", phone="5550101234"
        )
        s.add(p)
        service_id = None
        if service:
            svc = Service(tenant_id=tenant, name=service)
            s.add(svc)
            await s.flush()
            service_id = svc.id
        await s.flush()
        defaults = dict(
            status="dormant",
            primary_type="one_and_done",
            visit_count=1,
            total_spend_cents=1000,
            likelihood_score=50,
            revenue_basis_cents=20000,
            usual_service_id=service_id,
            last_visit_at=datetime.now(UTC) - timedelta(days=300),
            days_since_last_visit=300,
            reasons=["One visit and no return"],
            points={"internal": "scoring detail"},
        )
        s.add(RunPatient(tenant_id=tenant, run_id=run_id, patient_id=p.id, **{**defaults, **kw}))
        return p.id


async def test_returns_every_dormant_patient_in_one_call_with_no_contact_or_scoring_details(client):
    t = await create_test_tenant()
    run = await _run(t)
    for i in range(130):  # more than one page of the paged list
        await _patient(t, run, f"First{i:03d}", "Last", likelihood_score=i % 100)
    await _patient(t, run, "Quiet", "Risk", status="at_risk", primary_type=None)  # not dormant: left out
    await _patient(t, run, "Plain", "Unclassified", primary_type=None, service="Botox")
    r = await client.get(f"/runs/{run}/report", headers=_h(t))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 131 == len(body["patients"])
    assert body["run_id"] == str(run)
    assert all(p["status"] == "dormant" for p in body["patients"])
    assert {p["primary_type"] for p in body["patients"]} == {"one_and_done", None}
    first = body["patients"][0]
    assert set(first) == {
        "patient_id", "display_name", "status", "primary_type", "reasons", "usual_service_name", "last_visit_at",
        "days_since_last_visit", "likelihood_score", "revenue_basis_cents", "revenue_kind", "revenue_low_cents",
        "revenue_high_cents", "offer_service_name",
    }  # fmt: skip
    text = r.text
    assert "secret.test" not in text and "5550101234" not in text and "scoring detail" not in text
    scores = [p["likelihood_score"] for p in body["patients"]]
    assert scores == sorted(scores, reverse=True)  # the list's own order
    assert any(p["usual_service_name"] == "Botox" for p in body["patients"])


async def test_the_response_is_never_cached(client):
    t = await create_test_tenant()
    run = await _run(t)
    await _patient(t, run, "A", "B")
    r = await client.get(f"/runs/{run}/report", headers=_h(t))
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("role", ["front_desk", "provider", "consultant"])
async def test_only_the_owner_and_office_manager_may_export(client, role):
    t = await create_test_tenant()
    run = await _run(t)
    await _patient(t, run, "A", "B")
    assert (await client.get(f"/runs/{run}/report", headers=_h(t, role))).status_code == 403
    for ok in ("owner", "office_manager"):
        assert (await client.get(f"/runs/{run}/report", headers=_h(t, ok))).status_code == 200
    async with tenant_session(t) as s:  # a refused call leaves no audit entry
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.report.export"))).all()
    assert len(rows) == 2


async def test_another_clinics_run_and_patients_are_out_of_reach(client):
    mine, theirs = await create_test_tenant(), await create_test_tenant()
    my_run, their_run = await _run(mine), await _run(theirs)
    await _patient(mine, my_run, "Mine", "Patient")
    await _patient(theirs, their_run, "Theirs", "Patient")
    assert (await client.get(f"/runs/{their_run}/report", headers=_h(mine))).status_code == 404
    body = (await client.get(f"/runs/{my_run}/report", headers=_h(mine))).json()
    assert [p["display_name"] for p in body["patients"]] == ["Mine Patient"]


async def test_an_unknown_run_is_not_found_and_an_unfinished_one_is_refused_like_the_list(client):
    t = await create_test_tenant()
    queued = await _run(t, status="queued")
    assert (await client.get(f"/runs/{queued}/report", headers=_h(t))).status_code == 409
    assert (await client.get(f"/runs/{uuid.uuid4()}/report", headers=_h(t))).status_code == 404


async def test_one_audit_entry_with_counts_and_no_values(client):
    t = await create_test_tenant()
    run = await _run(t)
    for i in range(120):
        await _patient(t, run, f"Zelda{i}", "Canary")
    await _patient(t, run, "Pat", "Unclassified", primary_type=None)
    assert (await client.get(f"/runs/{run}/report", headers=_h(t))).status_code == 200
    async with tenant_session(t) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.entity_id == run))).all()
    entries = [r for r in rows if r.action == "reactivation.report.export"]
    assert len(entries) == 1  # one entry however many patients, unlike 100 a page on the list
    assert entries[0].details == {"patients": 121, "groups": 2}
    blob = json.dumps([r.details for r in rows], default=str)
    assert "Zelda" not in blob and "Canary" not in blob and "secret.test" not in blob


async def test_the_report_query_turns_off_nested_loops_which_made_it_take_ten_seconds(client):
    """Under row-level security the planner chose a nested loop that took 10 s for 12,000 patients and over 30 s
    for 25,000 (the dev proxy gave up). A hash join takes under a second, as in the facts query."""
    t = await create_test_tenant()
    run = await _run(t)
    await _patient(t, run, "A", "B")
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)  # every engine: tenant sessions use their own
    try:
        assert (await client.get(f"/runs/{run}/report", headers=_h(t))).status_code == 200
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    setting = next(i for i, sql in enumerate(statements) if "enable_nestloop" in sql)
    big_read = next(i for i, sql in enumerate(statements) if "run_patients" in sql and "JOIN" in sql)
    assert setting < big_read  # the setting is in place before the join runs
