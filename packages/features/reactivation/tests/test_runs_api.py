from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.features import JobContext
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog, OutboxEvent
from clinic_db.models.reactivation import Run
from clinic_db.models.reactivation import Settings as SettingsRow
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.feature import feature
from clinic_reactivation.router import router
from clinic_reactivation.runs import REAP_EVERY_SECONDS, REAP_JOB, RUN_REQUESTED, reap_stuck_runs

app = FastAPI()
# This isolated router test intentionally exercises the explicit dev-header adapter.
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


def _h(tenant, role="owner", **extra):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role, **extra}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _events(tenant):
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.event_type == RUN_REQUESTED))).all()
    return [r.payload["run_id"] for r in rows]


async def _add_run(tenant, status, **kw):
    async with tenant_session(tenant) as s:
        run = Run(tenant_id=tenant, trigger="scheduled", status=status, settings_version=0, settings={}, **kw)
        s.add(run)
        await s.flush()
        return str(run.id)


async def _run(tenant, run_id):
    async with tenant_session(tenant) as s:
        return await s.get(Run, run_id)


def _ago(minutes):
    return datetime.now(UTC) - timedelta(minutes=minutes)


async def test_happy_path_creates_queued_run_audits_and_requests_it(client):
    t = await create_test_tenant()
    r = await client.post("/runs", headers=_h(t, "office_manager"))
    assert r.status_code == 202
    body = r.json()
    assert (body["status"], body["trigger"], body["deduplicated"]) == ("queued", "manual", None)
    run = await _run(t, body["id"])
    assert run.requested_by == "dev-user"
    assert await _events(t) == [body["id"]]
    async with tenant_session(t) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.run.requested"))).all()
    assert [str(a.entity_id) for a in rows] == [body["id"]]


async def test_saved_settings_and_version_are_copied(client):
    t = await create_test_tenant()
    config = ReactivationSettings().model_dump(mode="json")
    config["min_days_since_visit"] = 200
    async with tenant_session(t) as s:
        s.add(SettingsRow(tenant_id=t, version=3, config=config))
    body = (await client.post("/runs", headers=_h(t))).json()
    run = await _run(t, body["id"])
    assert (run.settings_version, run.settings, body["settings_source"]) == (3, config, "saved")


async def test_clinic_without_saved_settings_runs_on_defaults(client):
    t = await create_test_tenant()
    body = (await client.post("/runs", headers=_h(t))).json()
    run = await _run(t, body["id"])
    assert (run.settings_version, body["settings_source"]) == (0, "defaults")
    assert run.settings == ReactivationSettings().model_dump(mode="json")


async def test_same_idempotency_key_twice_gives_one_run(client):
    t = await create_test_tenant()
    h = _h(t, **{"Idempotency-Key": "k1"})
    first, second = await client.post("/runs", headers=h), await client.post("/runs", headers=h)
    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["deduplicated"] == "idempotency_key"
    async with tenant_session(t) as s:
        assert len((await s.scalars(select(Run))).all()) == 1


async def test_second_manual_run_while_one_is_queued_returns_the_queued_run(client):
    t = await create_test_tenant()
    first = await client.post("/runs", headers=_h(t, **{"Idempotency-Key": "a"}))
    second = await client.post("/runs", headers=_h(t, **{"Idempotency-Key": "b"}))
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["deduplicated"] == "already_queued"


async def test_run_stuck_for_31_minutes_is_failed_and_a_new_run_is_created(client):
    t = await create_test_tenant()
    stuck = await _add_run(t, "running", started_at=_ago(31))
    r = await client.post("/runs", headers=_h(t))
    assert r.status_code == 202 and r.json()["id"] != stuck
    old = await _run(t, stuck)
    assert (old.status, old.error_code) == ("failed", "timed_out") and old.finished_at is not None
    assert await _events(t) == [r.json()["id"]]


async def test_run_running_for_29_minutes_is_left_alone_and_the_new_run_waits(client):
    t = await create_test_tenant()
    running = await _add_run(t, "running", started_at=_ago(29))
    r = await client.post("/runs", headers=_h(t))
    assert r.status_code == 202
    assert (await _run(t, running)).status == "running"
    assert await _events(t) == []


async def test_queued_run_behind_a_stuck_run_is_requested_again(client):
    t = await create_test_tenant()
    await _add_run(t, "running", started_at=_ago(31))
    queued = await _add_run(t, "queued")
    r = await client.post("/runs", headers=_h(t))
    assert r.status_code == 200 and r.json()["id"] == queued
    assert await _events(t) == [queued]


async def test_queued_run_behind_a_live_run_is_not_requested(client):
    t = await create_test_tenant()
    await _add_run(t, "running", started_at=_ago(5))
    queued = await _add_run(t, "queued")
    assert (await client.post("/runs", headers=_h(t))).json()["id"] == queued
    assert await _events(t) == []


@pytest.mark.parametrize("role", ["front_desk", "provider", "consultant"])
async def test_other_roles_cannot_start_a_run(client, role):
    t = await create_test_tenant()
    assert (await client.post("/runs", headers=_h(t, role))).status_code == 403


async def test_viewers_can_read_but_provider_cannot(client):
    t = await create_test_tenant()
    run_id = await _add_run(t, "completed")
    assert (await client.get("/runs", headers=_h(t, "front_desk"))).status_code == 200
    assert (await client.get(f"/runs/{run_id}", headers=_h(t, "front_desk"))).status_code == 200
    assert (await client.get("/runs", headers=_h(t, "provider"))).status_code == 403


async def test_another_practice_cannot_see_the_run(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    run_id = await _add_run(a, "completed")
    assert (await client.get(f"/runs/{run_id}", headers=_h(b))).status_code == 404
    assert (await client.get("/runs", headers=_h(b))).json() == []
    assert len((await client.get("/runs", headers=_h(a))).json()) == 1


async def test_list_is_newest_first_capped_at_20_with_headline(client):
    t = await create_test_tenant()
    summary = {"dormant_count": 7, "new_revenue_low_cents": 100, "as_of": "x"}
    async with tenant_session(t) as s:
        for i in range(25):
            s.add(
                Run(
                    tenant_id=t,
                    trigger="scheduled",
                    status="completed",
                    settings_version=1,
                    settings={},
                    queued_at=_ago(1000 - i),
                    summary=summary if i == 24 else None,
                )
            )
    rows = (await client.get("/runs", headers=_h(t))).json()
    assert len(rows) == 20
    assert [r["queued_at"] for r in rows] == sorted((r["queued_at"] for r in rows), reverse=True)
    assert rows[0]["headline"] == {"dormant_count": 7, "new_revenue_low_cents": 100}


async def test_get_run_returns_summary_quality_and_error_code(client):
    t = await create_test_tenant()
    ok = await _add_run(t, "completed", summary={"dormant_count": 1}, quality={"warnings": []})
    bad = await _add_run(t, "failed", error_code="facts_query_failed")
    d = (await client.get(f"/runs/{ok}", headers=_h(t))).json()
    assert (d["summary"], d["quality"], d["error_code"]) == ({"dormant_count": 1}, {"warnings": []}, None)
    assert (await client.get(f"/runs/{bad}", headers=_h(t))).json()["error_code"] == "facts_query_failed"


# --- the scheduled reaper ------------------------------------------------------------------------------------


async def _reap(tenant):
    async with tenant_session(tenant) as s:
        await reap_stuck_runs(JobContext(tenant_id=tenant, session=s), {})


def test_the_reaper_is_scheduled():
    assert feature.jobs[REAP_JOB] is reap_stuck_runs
    assert [(s.job, s.every_seconds) for s in feature.schedules] == [(REAP_JOB, REAP_EVERY_SECONDS)]


async def test_reaper_fails_a_stuck_run_and_requests_the_queued_run_behind_it():
    t = await create_test_tenant()
    stuck = await _add_run(t, "running", started_at=_ago(31))
    queued = await _add_run(t, "queued")
    await _reap(t)
    old = await _run(t, stuck)
    assert (old.status, old.error_code) == ("failed", "timed_out")
    assert await _events(t) == [queued]


async def test_reaper_re_requests_an_orphaned_queued_run():
    # Nothing is running, so a queued run's event was lost; ask again.
    t = await create_test_tenant()
    queued = await _add_run(t, "queued")
    await _reap(t)
    assert await _events(t) == [queued]


async def test_reaper_leaves_a_live_run_and_its_queue_alone():
    t = await create_test_tenant()
    running = await _add_run(t, "running", started_at=_ago(5))
    await _add_run(t, "queued")
    await _reap(t)
    assert (await _run(t, running)).status == "running"
    assert await _events(t) == []
