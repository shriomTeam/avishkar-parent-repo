"""The settings API through the HTTP client, at server level (no UI)."""

import asyncio

import pytest
from lr_api import URL, body, build_app, client_for, headers, put
from sqlalchemy import func, select, text

import clinic_lead_response.api.settings as settings_api
from clinic_core.database import tenant_session
from clinic_db.models.lead_response import PracticeSettings
from clinic_db.models.ops import AuditLog
from clinic_lead_response.settings_model import LeadResponseSettings
from clinic_lead_response.settings_store import current_settings

app = build_app()


@pytest.fixture
async def client():
    async with client_for(app) as c:
        yield c


async def _versions(tenant) -> list[int]:
    async with tenant_session(tenant) as s:
        return list(await s.scalars(select(PracticeSettings.version).order_by(PracticeSettings.version)))


async def _audit_count(tenant) -> int:
    async with tenant_session(tenant) as s:
        return await s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.like("lead_response.%")))


# --- reading ---------------------------------------------------------------------------------------------------


async def test_get_without_a_row_returns_the_version_0_defaults(client, make_tenant):
    t = await make_tenant()
    response = await client.get(URL, headers=headers(t))
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 0 and data["updated_by"] is None and data["updated_at"] is None
    assert data["config"] == LeadResponseSettings().model_dump(mode="json") == data["defaults"]
    assert data["timezone"] == "America/New_York"
    assert await _versions(t) == []  # reading never writes


async def test_get_after_a_save_returns_the_latest_version(client, make_tenant):
    t = await make_tenant()
    assert (await put(client, t, 0, body(holding_minutes=10))).status_code == 200
    assert (await put(client, t, 1, body(holding_minutes=20))).status_code == 200
    data = (await client.get(URL, headers=headers(t))).json()
    assert data["version"] == 2 and data["config"]["holding_minutes"] == 20
    assert data["defaults"]["holding_minutes"] == 15


async def test_current_settings_reads_the_latest_version_for_the_engine(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        version, settings = await current_settings(s)
    assert (version, settings) == (0, LeadResponseSettings())
    async with client_for(app) as c:
        await put(c, t, 0, body(sla_minutes=90))
    async with tenant_session(t) as s:
        version, settings = await current_settings(s)
    assert (version, settings.sla_minutes) == (1, 90)


# --- saving and versions ---------------------------------------------------------------------------------------


async def test_put_creates_the_next_version_and_keeps_the_previous_one(client, make_tenant):
    t = await make_tenant()
    first = await put(client, t, 0, body(holding_minutes=10, sla_minutes=40))
    assert first.status_code == 200 and first.json()["version"] == 1
    second = await put(client, t, 1, body(holding_minutes=20, sla_minutes=60))
    assert second.status_code == 200 and second.json()["version"] == 2
    async with tenant_session(t) as s:
        rows = (await s.execute(select(PracticeSettings).order_by(PracticeSettings.version))).scalars().all()
    assert [(r.version, r.holding_minutes, r.sla_minutes) for r in rows] == [(1, 10, 40), (2, 20, 60)]


async def test_put_stores_every_setting(client, make_tenant):
    t = await make_tenant()
    payload = body(
        holding_minutes=12,
        sla_minutes=45,
        ack_text="  We got your message.  ",
        ai_active_mode="overflow",
        overflow_minutes=20,
        escalation_role="owner",
        business_hours={"mon": [{"start": "09:00", "end": "17:00"}]},
        quiet_hours={"start": "21:00", "end": "08:00"},
    )
    assert (await put(client, t, 0, payload)).status_code == 200
    config = (await client.get(URL, headers=headers(t))).json()["config"]
    assert config["ack_text"] == "We got your message."
    assert config["business_hours"]["mon"] == [{"start": "09:00", "end": "17:00"}]
    assert config["business_hours"]["tue"] == []
    assert config["quiet_hours"] == {"start": "21:00", "end": "08:00"}
    assert (config["ai_active_mode"], config["overflow_minutes"], config["escalation_role"]) == (
        "overflow",
        20,
        "owner",
    )
    async with tenant_session(t) as s:
        row = (await s.execute(text("SELECT business_hours, quiet_hours FROM lead_response.practice_settings"))).one()
    assert row.business_hours == {"mon": [{"start": "09:00", "end": "17:00"}]}  # only days with windows are stored


# --- concurrency -----------------------------------------------------------------------------------------------


async def test_a_stale_version_is_refused(client, make_tenant):
    t = await make_tenant()
    await put(client, t, 0, body(holding_minutes=10))
    await put(client, t, 1, body(holding_minutes=20))
    stale = await put(client, t, 1, body(holding_minutes=30, sla_minutes=60))
    assert stale.status_code == 412 and "reload" in stale.json()["detail"]
    assert await _versions(t) == [1, 2]


async def test_a_stale_version_is_refused_even_when_nothing_changed(client, make_tenant):
    t = await make_tenant()
    await put(client, t, 0, body(holding_minutes=10))
    await put(client, t, 1, body(holding_minutes=20))
    same_as_current = await put(client, t, 1, body(holding_minutes=20))
    assert same_as_current.status_code == 412
    assert await _versions(t) == [1, 2]


@pytest.mark.parametrize("header", [None, "abc", "-1", "99", ""])
async def test_a_missing_or_wrong_if_match_is_refused(client, make_tenant, header):
    t = await make_tenant()
    extra = {} if header is None else {"If-Match": header}
    response = await client.put(URL, json=body(holding_minutes=10), headers=headers(t, **extra))
    assert response.status_code == 412
    assert await _versions(t) == []


async def test_if_match_accepts_a_quoted_or_weak_etag(client, make_tenant):
    t = await make_tenant()
    assert (
        await client.put(URL, json=body(holding_minutes=10), headers=headers(t, **{"If-Match": '"0"'}))
    ).status_code == 200
    assert (
        await client.put(URL, json=body(holding_minutes=20), headers=headers(t, **{"If-Match": 'W/"1"'}))
    ).status_code == 200


@pytest.mark.parametrize("current", [0, 1])
async def test_two_saves_at_the_same_moment_have_exactly_one_winner(make_tenant, monkeypatch, current):
    t = await make_tenant()
    async with client_for(app) as seed_client:
        if current:
            await put(seed_client, t, 0, body(holding_minutes=8))

    # Hold both requests after they have read the current version and before either inserts, so both pass the
    # If-Match check and the loser can only be stopped by the unique (tenant_id, version) key.
    barrier = asyncio.Barrier(2)
    read = settings_api.current_row
    passed_check: list[int] = []

    async def synchronised(session):
        row = await read(session)
        passed_check.append(row.version if row else 0)
        await barrier.wait()
        return row

    monkeypatch.setattr(settings_api, "current_row", synchronised)

    async with client_for(app) as a, client_for(app) as b:
        first, second = await asyncio.gather(
            put(a, t, current, body(holding_minutes=10)), put(b, t, current, body(holding_minutes=20))
        )

    assert passed_check == [current, current]  # both were current when they started
    assert sorted([first.status_code, second.status_code]) == [200, 412]
    loser = first if first.status_code == 412 else second
    assert "reload" in loser.json()["detail"]
    assert await _versions(t) == list(range(1, current + 2))  # exactly one new version
    assert await _audit_count(t) == current + 1  # and exactly one audit entry for it


async def test_a_save_with_no_changes_at_the_current_version_writes_nothing(client, make_tenant):
    t = await make_tenant()
    await put(client, t, 0, body(holding_minutes=10))
    audits = await _audit_count(t)
    again = await put(client, t, 1, body(holding_minutes=10))
    assert again.status_code == 200 and again.json()["version"] == 1
    assert await _versions(t) == [1]
    assert await _audit_count(t) == audits


async def test_saving_the_defaults_when_no_version_exists_writes_nothing(client, make_tenant):
    t = await make_tenant()
    response = await put(client, t, 0, body())
    assert response.status_code == 200 and response.json()["version"] == 0
    assert await _versions(t) == [] and await _audit_count(t) == 0


# --- validation through the API --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        body(holding_minutes=4),
        body(holding_minutes=61, sla_minutes=100),
        body(sla_minutes=9, holding_minutes=5),
        body(sla_minutes=241),
        body(holding_minutes=30, sla_minutes=30),
        body(holding_minutes=40, sla_minutes=30),
        body(ai_active_mode="overflow"),
        body(ack_text="x" * 321),
        body(ack_text=""),
        body(ack_text="Hi {name}"),
        body(ack_text="bell\x07"),
        body(surprise=True),
        body(escalation_role="front_desk"),
        body(escalation_role="admin"),
        body(capabilities={"book_appointments": True, "show_open_slots": False}),
        body(business_hours={"mon": [{"start": "17:00", "end": "09:00"}]}),
        body(quiet_hours={"start": "21:00", "end": "21:00"}),
    ],
)
async def test_invalid_bodies_get_422_and_write_nothing(client, make_tenant, payload):
    t = await make_tenant()
    response = await put(client, t, 0, payload)
    assert response.status_code == 422 and response.json() == {"detail": "invalid_request"}
    assert await _versions(t) == [] and await _audit_count(t) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"ai_enabled": True},
        {"send_mode": "auto"},
        {"capabilities": {"answer_questions": True}},
        {"capabilities": {"show_open_slots": True, "book_appointments": True}},
    ],
)
async def test_turning_the_ai_on_is_refused_until_it_exists(client, make_tenant, overrides):
    t = await make_tenant()
    response = await put(client, t, 0, body(**overrides))
    assert response.status_code == 422 and response.json() == {"detail": "ai_settings_not_available_yet"}
    assert await _versions(t) == []


async def test_booking_without_open_slots_is_refused_for_its_own_reason(client, make_tenant):
    t = await make_tenant()
    response = await put(client, t, 0, body(capabilities={"book_appointments": True, "show_open_slots": False}))
    assert response.json() == {"detail": "invalid_request"}  # the dependency rule, not the AI gate


async def test_the_valid_edges_are_accepted(client, make_tenant):
    t = await make_tenant()
    for version, (holding, sla) in enumerate([(5, 10), (60, 240), (5, 240), (59, 60)]):
        response = await put(client, t, version, body(holding_minutes=holding, sla_minutes=sla))
        assert response.status_code == 200, (holding, sla)


async def test_validation_runs_before_the_version_check(client, make_tenant):
    t = await make_tenant()
    response = await put(client, t, 7, body(holding_minutes=4))
    assert response.status_code == 422


# --- isolation and the feature gate ---------------------------------------------------------------------------


async def test_tenant_a_cannot_see_or_overwrite_tenant_bs_settings(client, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await put(client, a, 0, body(holding_minutes=10, ack_text="Tenant A wording"))
    assert (await client.get(URL, headers=headers(b))).json()["version"] == 0
    assert (await client.get(URL, headers=headers(b))).json()["config"]["ack_text"] != "Tenant A wording"
    # B cannot save against A's version: B is at version 0, so version 1 is stale for B and nothing of A is touched.
    assert (await put(client, b, 1, body(holding_minutes=50, sla_minutes=60))).status_code == 412
    assert (await put(client, b, 0, body(holding_minutes=50, sla_minutes=60))).status_code == 200
    a_view = (await client.get(URL, headers=headers(a))).json()
    assert a_view["version"] == 1 and a_view["config"]["holding_minutes"] == 10
    assert await _versions(a) == [1] and await _versions(b) == [1]


async def test_a_tenant_without_the_feature_gets_403_on_get_and_put(client, make_tenant):
    t = await make_tenant(())
    got = await client.get(URL, headers=headers(t))
    saved = await put(client, t, 0, body(holding_minutes=10))
    for response in (got, saved):
        assert response.status_code == 403 and "lead_response" in response.json()["detail"]
    assert await _versions(t) == []


async def test_updated_by_is_the_staff_id_only(client, make_tenant):
    t = await make_tenant()
    saved = await put(client, t, 0, body(holding_minutes=10), staff="staff-abc")
    assert saved.json()["updated_by"] == "staff-abc"
    data = (await client.get(URL, headers=headers(t))).json()
    assert data["updated_by"] == "staff-abc"
    assert set(data) == {"version", "config", "defaults", "timezone", "updated_by", "updated_at"}
    async with tenant_session(t) as s:
        assert await s.scalar(select(PracticeSettings.created_by)) == "staff-abc"
