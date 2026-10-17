import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Patient, Service
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


async def _run(tenant, status="completed", minutes_ago=0, **kw):
    async with tenant_session(tenant) as s:
        run = Run(
            tenant_id=tenant,
            trigger="manual",
            status=status,
            settings_version=0,
            settings=kw.pop("settings", {}),
            finished_at=datetime.now(UTC) - timedelta(minutes=minutes_ago) if status == "completed" else None,
            **kw,
        )
        s.add(run)
        await s.flush()
        return run.id


async def _patient(tenant, run_id, first="A", last="B", **kw):
    async with tenant_session(tenant) as s:
        p = Patient(tenant_id=tenant, first_name=first, last_name=last)
        s.add(p)
        await s.flush()
        defaults = dict(status="dormant", primary_type="one_and_done", visit_count=1, total_spend_cents=1000)
        s.add(RunPatient(tenant_id=tenant, run_id=run_id, patient_id=p.id, **{**defaults, **kw}))
        return p.id


def _type_row(tenant, run_id, key, **kw):
    base = dict(
        patient_count=3,
        basis_total_cents=30000,
        rate_low=0.08,
        rate_high=0.15,
        rate_source="assumed",
        revenue_low_cents=2400,
        revenue_high_cents=4500,
        revenue_kind="new",
    )
    return RunType(tenant_id=tenant, run_id=run_id, type_key=key, **{**base, **kw})


async def test_latest_returns_newest_completed_and_ignores_others(client):
    t = await create_test_tenant()
    await _run(t, minutes_ago=60)
    newest = await _run(t, minutes_ago=5, summary={"dormant_count": 7})
    await _run(t, "failed", error_code="x")
    queued = await _run(t, "queued")
    r = await client.get("/runs/latest", headers=_h(t, "front_desk"))
    body = r.json()
    assert r.status_code == 200
    assert body["id"] == str(newest)
    assert body["summary"] == {"dormant_count": 7}
    assert body["active_run"]["id"] == str(queued)
    assert body["active_run"]["status"] == "queued"


async def test_latest_active_run_is_the_running_one(client):
    t = await create_test_tenant()
    await _run(t)
    running = await _run(t, "running", progress_pct=60)
    body = (await client.get("/runs/latest", headers=_h(t))).json()
    assert body["active_run"] == {"id": str(running), "status": "running", "progress_pct": 60}


async def test_latest_is_404_without_a_completed_run(client):
    t = await create_test_tenant()
    await _run(t, "queued")
    await _run(t, "failed")
    r = await client.get("/runs/latest", headers=_h(t))
    assert (r.status_code, r.json()["detail"]) == (404, "no_completed_run")


async def test_types_match_stored_rows_and_mark_unavailable(client):
    t = await create_test_tenant()
    config = ReactivationSettings().model_dump(mode="json")
    config["types"]["overdue_maintenance"]["enabled"] = False
    async with tenant_session(t) as s:
        service = Service(tenant_id=t, name="Neurotoxin")
        s.add(service)
        await s.flush()
        service_id = service.id
    run_id = await _run(
        t,
        settings=config,
        summary={
            "unclassified_dormant": 4,
            "types_data_available": {"one_and_done": True, "unused_balance": False, "churned_member": False},
        },
    )
    async with tenant_session(t) as s:
        s.add(_type_row(t, run_id, "one_and_done", top_service_id=service_id))
        s.add(_type_row(t, run_id, "unused_balance", revenue_kind="retention", patient_count=0))
    r = await client.get(f"/runs/{run_id}/types", headers=_h(t, "front_desk"))
    assert r.status_code == 200
    by_key = {e["type_key"]: e for e in r.json()}
    assert set(by_key) == {
        "lapsed_high_value",
        "churned_member",
        "consult_not_converted",
        "lapsed_regular",
        "one_and_done",
        "unused_balance",
        "unclassified",
    }  # overdue_maintenance is switched off
    one = by_key["one_and_done"]
    assert (one["patient_count"], one["revenue_low_cents"], one["revenue_high_cents"]) == (3, 2400, 4500)
    assert (one["rate_low"], one["rate_high"], one["rate_source"]) == (0.08, 0.15, "assumed")
    assert (one["top_service_name"], one["kind"], one["available"], one["label"]) == (
        "Neurotoxin",
        "new",
        True,
        "One-and-done",
    )
    assert one["description"]
    for key in ("unused_balance", "churned_member", "lapsed_high_value"):
        e = by_key[key]
        assert e["available"] is False
        assert (e["patient_count"], e["revenue_low_cents"], e["revenue_high_cents"]) == (None, None, None)
        assert e["top_service_name"] is None
    assert by_key["unused_balance"]["rate_source"] == "assumed"  # stored row kept, figures nulled
    assert by_key["churned_member"]["rate_source"] is None
    un = by_key["unclassified"]
    assert un["patient_count"] == 4 and un["available"] is True
    assert (un["revenue_low_cents"], un["revenue_high_cents"], un["rate_low"], un["top_service_name"]) == (
        None,
        None,
        None,
        None,
    )


async def test_types_order_follows_priority(client):
    t = await create_test_tenant()
    run_id = await _run(t, settings=ReactivationSettings().model_dump(mode="json"), summary={})
    keys = [e["type_key"] for e in (await client.get(f"/runs/{run_id}/types", headers=_h(t))).json()]
    assert keys == [
        "lapsed_high_value",
        "churned_member",
        "consult_not_converted",
        "overdue_maintenance",
        "lapsed_regular",  # priority 5 ties with one_and_done and sorts first by key
        "one_and_done",
        "unused_balance",
        "unclassified",
    ]


async def test_patients_filter_paginate_and_order_stably(client):
    t = await create_test_tenant()
    run_id = await _run(t)
    async with tenant_session(t) as s:
        svc = Service(tenant_id=t, name="Filler")
        s.add(svc)
        await s.flush()
        svc_id = svc.id
    ids = []
    # scores 90, 80, 80 (spend tiebreak 500 vs 100), 80/100 (id tiebreak pair), 10
    spec = [(90, 100), (80, 500), (80, 100), (80, 100), (10, 100)]
    for score, spend in spec:
        ids.append(await _patient(t, run_id, likelihood_score=score, total_spend_cents=spend, usual_service_id=svc_id))
    other = await _patient(t, run_id, primary_type="overdue_maintenance", likelihood_score=50)
    risk = await _patient(t, run_id, status="at_risk", primary_type=None, likelihood_score=40)
    unc = await _patient(t, run_id, primary_type=None, likelihood_score=30)
    base = f"/runs/{run_id}/patients"

    full = (await client.get(base, headers=_h(t))).json()
    assert full["total"] == 8
    expected = [ids[0], ids[1], *sorted([ids[2], ids[3]], key=str), other, risk, unc, ids[4]]
    # scores: 90, 80(500), 80, 80, 50, 40, 30, 10
    assert [i["patient_id"] for i in full["items"]] == [str(x) for x in expected]

    seen = []
    for offset in range(0, 8, 3):
        page = (await client.get(base, params={"limit": 3, "offset": offset}, headers=_h(t))).json()
        assert (page["total"], page["limit"], page["offset"]) == (8, 3, offset)
        seen += [i["patient_id"] for i in page["items"]]
    assert seen == [str(x) for x in expected]

    by_type = (await client.get(base, params={"type": "one_and_done"}, headers=_h(t))).json()
    assert by_type["total"] == 5
    unclassified = (await client.get(base, params={"type": "unclassified"}, headers=_h(t))).json()
    assert [i["patient_id"] for i in unclassified["items"]] == [str(risk), str(unc)]
    only_unc_dormant = (
        await client.get(base, params={"type": "unclassified", "status": "dormant"}, headers=_h(t))
    ).json()
    assert [i["patient_id"] for i in only_unc_dormant["items"]] == [str(unc)]
    at_risk = (await client.get(base, params={"status": "at_risk"}, headers=_h(t))).json()
    assert (at_risk["total"], at_risk["items"][0]["patient_id"]) == (1, str(risk))

    row = full["items"][0]
    assert (row["display_name"], row["usual_service_name"], row["likelihood_score"]) == ("A B", "Filler", 90)
    assert row["revenue_basis_cents"] == 0 and row["points"] == {} and row["matched_types"] == []


async def test_patient_row_carries_stored_fields(client):
    t = await create_test_tenant()
    run_id = await _run(t)
    visit = datetime(2025, 1, 5, tzinfo=UTC)
    points = {"best_offer": {"service": "x"}, "reachable": {"reachable": True}, "change_since_last": {"change": "new"}}
    pid = await _patient(
        t,
        run_id,
        first=None,
        last=None,
        matched_types=["one_and_done", "unused_balance"],
        reasons=["Visited once"],
        last_visit_at=visit,
        days_since_last_visit=200,
        revenue_basis_cents=4200,
        points=points,
        likelihood_score=55,
    )
    item = (await client.get(f"/runs/{run_id}/patients", headers=_h(t))).json()["items"][0]
    assert item["patient_id"] == str(pid)
    assert item["display_name"] is None
    assert item["matched_types"] == ["one_and_done", "unused_balance"]
    assert item["reasons"] == ["Visited once"]
    assert (item["days_since_last_visit"], item["revenue_basis_cents"], item["points"]) == (200, 4200, points)
    assert item["last_visit_at"].startswith("2025-01-05")


async def test_deleted_patient_does_not_break_the_list(client):
    t = await create_test_tenant()
    run_id = await _run(t)
    keep = await _patient(t, run_id, likelihood_score=10)
    gone = await _patient(t, run_id, likelihood_score=90)
    async with tenant_session(t) as s:
        await s.execute(delete(Patient).where(Patient.id == gone))
    r = await client.get(f"/runs/{run_id}/patients", headers=_h(t))
    assert r.status_code == 200
    body = r.json()
    assert (body["total"], [i["patient_id"] for i in body["items"]]) == (1, [str(keep)])


async def test_other_practice_gets_404(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    run_id = await _run(a)
    for path in ("types", "patients"):
        assert (await client.get(f"/runs/{run_id}/{path}", headers=_h(b))).status_code == 404
    await _run(b)
    assert (await client.get("/runs/latest", headers=_h(b))).json()["id"] != str(run_id)


async def test_roles(client):
    t = await create_test_tenant()
    run_id = await _run(t)
    for role in ("provider", "consultant"):
        for path in (f"/runs/{run_id}/types", f"/runs/{run_id}/patients", "/runs/latest"):
            assert (await client.get(path, headers=_h(t, role))).status_code == 403
    fd = _h(t, "front_desk")
    assert (await client.get(f"/runs/{run_id}/patients", headers=fd)).status_code == 403
    assert (await client.get(f"/runs/{run_id}/types", headers=fd)).status_code == 200
    assert (await client.get(f"/runs/{run_id}/patients", headers=_h(t, "office_manager"))).status_code == 200


async def test_patients_read_is_audited_and_types_is_not(client):
    t = await create_test_tenant()
    run_id = await _run(t)
    await _patient(t, run_id)
    await client.get(f"/runs/{run_id}/types", headers=_h(t))
    await client.get(f"/runs/{run_id}/patients", params={"limit": 5, "type": "one_and_done"}, headers=_h(t))
    async with tenant_session(t) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action.like("reactivation.%.read")))).all()
    assert len(rows) == 1
    a = rows[0]
    assert (a.action, a.entity_id, a.actor_id) == ("reactivation.patients.read", run_id, "dev-user")
    assert a.details == {"type": "one_and_done", "status": None, "limit": 5, "offset": 0, "returned": 1}


async def test_run_not_completed_and_bad_params(client):
    t = await create_test_tenant()
    queued = await _run(t, "queued")
    for path in ("types", "patients"):
        r = await client.get(f"/runs/{queued}/{path}", headers=_h(t))
        assert (r.status_code, r.json()["detail"]) == (409, "run_not_completed")
    done = await _run(t)
    base = f"/runs/{done}/patients"
    assert (await client.get(base, params={"limit": 101}, headers=_h(t))).status_code == 422
    assert (await client.get(base, params={"limit": 0}, headers=_h(t))).status_code == 422
    assert (await client.get(base, params={"offset": -1}, headers=_h(t))).status_code == 422
    assert (await client.get(base, params={"status": "active"}, headers=_h(t))).status_code == 422
    assert (await client.get(base, params={"type": "nope"}, headers=_h(t))).status_code == 422
    assert (await client.get(f"/runs/{uuid.uuid4()}/types", headers=_h(t))).status_code == 404
