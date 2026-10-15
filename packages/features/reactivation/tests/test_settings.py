from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog
from clinic_db.models.reactivation import Run
from clinic_reactivation.analysis.settings import ReactivationSettings, RunSchedule, compute_next_run
from clinic_reactivation.router import router

app = FastAPI()
app.include_router(router)

NY = "America/New_York"


def _h(tenant, role="owner", **extra):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role, **extra}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _config(**overrides):
    config = ReactivationSettings().model_dump(mode="json")
    for dotted, value in overrides.items():
        *path, leaf = dotted.split(".")
        node = config
        for key in path:
            node = node[key]
        node[leaf] = value
    return config


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


# --- defaults -------------------------------------------------------------------------------


def test_defaults_validate_and_match_the_spec():
    s = ReactivationSettings()
    assert ReactivationSettings.model_validate(s.model_dump(mode="json")) == s
    assert (s.dormant.min_days_since_visit, s.dormant.default_rebooking_days) == (180, 120)
    assert (s.revenue.rate_low, s.revenue.rate_high, s.revenue.min_sample) == (0.08, 0.15, 30)
    assert (s.revenue.attribution_window_days, s.types.churned_member.membership_months) == (30, 6)
    assert [getattr(s.types, n).priority for n in type(s.types).model_fields] == [1, 2, 3, 4, 5, 6]
    assert s.points.seasonality is False
    assert all(v for k, v in s.points.model_dump().items() if k != "seasonality")
    assert s.schedule.frequency in ("weekly", "monthly")


MODULE_DEFAULTS = {
    "analysis_enabled": True,
    "export_enabled": True,
    "campaign_handoff_enabled": False,
    "ai_summary_enabled": False,
}


def test_module_switch_defaults():
    assert ReactivationSettings().modules.model_dump() == MODULE_DEFAULTS
    assert _config()["modules"] == MODULE_DEFAULTS


@pytest.mark.parametrize("switch", list(MODULE_DEFAULTS))
async def test_each_module_switch_can_be_saved_and_read_back(client, switch):
    t = await create_test_tenant()
    flipped = not MODULE_DEFAULTS[switch]
    r = await client.put(
        "/settings", headers=_h(t, **{"If-Match": "0"}), json=_config(**{f"modules.{switch}": flipped})
    )
    assert r.status_code == 200 and r.json()["config"]["modules"][switch] is flipped
    got = (await client.get("/settings", headers=_h(t))).json()["config"]["modules"]
    assert got == {**MODULE_DEFAULTS, switch: flipped}


async def test_unknown_module_switch_gives_422_and_non_bool_gives_422(client):
    t = await create_test_tenant()
    h = _h(t, **{"If-Match": "0"})
    assert (await client.put("/settings", headers=h, json=_config(**{"modules.nope": True}))).status_code == 422
    bad = _config()
    bad["modules"]["export_enabled"] = "maybe"
    assert (await client.put("/settings", headers=h, json=bad)).status_code == 422


def test_settings_hold_no_campaign_shape():
    names = set(ReactivationSettings.model_fields)
    assert names.isdisjoint({"audience", "content", "message", "messages", "campaign", "category"})


async def test_get_returns_defaults_with_version_zero_when_nothing_saved(client):
    t = await create_test_tenant()
    r = await client.get("/settings", headers=_h(t))
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 0 and body["next_run_at"] is None and body["timezone"] == NY
    assert body["config"] == _config()


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"types.one_and_done.priority": 1},  # duplicate priority
        {"revenue.rate_low": 0.5, "revenue.rate_high": 0.1},  # low > high
        {"revenue.rate_high": 1.5},
        {"dormant.min_days_since_visit": 0},
        {"schedule.frequency": "daily"},
        {"schedule.day_of_month": 31},
        {"schedule.day_of_week": 7},
        {"schedule.local_time": "25:00"},
        {"types.overdue_maintenance.overdue_ratio_min": 3.0},
        {"dormant.rebooking_days_by_category": {"botox": 0}},
    ],
)
async def test_bad_values_give_422(client, overrides):
    t = await create_test_tenant()
    r = await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=_config(**overrides))
    assert r.status_code == 422, r.text


async def test_unknown_and_campaign_shaped_fields_give_422(client):
    t = await create_test_tenant()
    for extra in ({"audience": {"x": 1}}, {"content": {"sms": "hi"}}, {"surprise": True}):
        body = {**_config(), **extra}
        r = await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=body)
        assert r.status_code == 422, extra


def test_priorities_validator_raises_value_error_message():
    with pytest.raises(ValidationError, match="priorities must be unique"):
        ReactivationSettings.model_validate(_config(**{"types.unused_balance.priority": 5}))


# --- versioning and roles -------------------------------------------------------------------


async def test_put_increments_version_and_stale_if_match_gives_412(client):
    t = await create_test_tenant()
    h0 = _h(t, **{"If-Match": "0"})
    first = await client.put("/settings", headers=h0, json=_config(**{"dormant.min_days_since_visit": 200}))
    assert first.status_code == 200
    assert first.json()["version"] == 1 and first.json()["next_run_at"] is not None

    assert (await client.put("/settings", headers=h0, json=_config())).status_code == 412  # stale
    assert (await client.put("/settings", headers=_h(t), json=_config())).status_code == 412  # missing
    assert (await client.put("/settings", headers=_h(t, **{"If-Match": "abc"}), json=_config())).status_code == 412

    second = await client.put("/settings", headers=_h(t, **{"If-Match": '"1"'}), json=_config())
    assert second.status_code == 200 and second.json()["version"] == 2

    got = await client.get("/settings", headers=_h(t))
    assert got.json()["version"] == 2 and got.json()["config"] == _config()


async def test_front_desk_cannot_put_or_get_settings_but_can_get_schedule(client):
    t = await create_test_tenant()
    fd = _h(t, "front_desk", **{"If-Match": "0"})
    assert (await client.put("/settings", headers=fd, json=_config())).status_code == 403
    assert (await client.get("/settings", headers=_h(t, "front_desk"))).status_code == 403
    assert (await client.get("/schedule", headers=_h(t, "front_desk"))).status_code == 200
    for role in ("provider", "consultant"):
        assert (await client.get("/schedule", headers=_h(t, role))).status_code == 403
    assert (
        await client.put("/settings", headers=_h(t, "office_manager", **{"If-Match": "0"}), json=_config())
    ).status_code == 200


async def test_save_is_audited_without_settings_content(client):
    t = await create_test_tenant()
    r = await client.put("/settings", headers=_h(t, **{"If-Match": "0", "X-Staff-Id": "alice"}), json=_config())
    assert r.status_code == 200
    async with tenant_session(t) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.settings.saved"))).all()
    assert len(rows) == 1
    assert rows[0].actor_type == "staff" and rows[0].actor_id == "alice"
    assert rows[0].details == {"from_version": 0, "to_version": 1}


async def test_schedule_shows_next_run_and_last_run(client):
    t = await create_test_tenant()
    empty = (await client.get("/schedule", headers=_h(t))).json()
    assert empty == {"next_run_at": None, "last_run": None}

    await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=_config())
    async with tenant_session(t) as s:
        s.add(Run(tenant_id=t, trigger="manual", status="queued", settings_version=1, settings={}))
    body = (await client.get("/schedule", headers=_h(t))).json()
    assert body["next_run_at"] is not None
    assert body["last_run"]["status"] == "queued" and body["last_run"]["trigger"] == "manual"


# --- next_run_at ----------------------------------------------------------------------------


def _weekly(dow, at):
    return RunSchedule(frequency="weekly", day_of_week=dow, local_time=at)


def _monthly(dom, at):
    return RunSchedule(frequency="monthly", day_of_month=dom, local_time=at)


def test_weekly_keeps_local_time_across_spring_forward():
    # Sunday 09:00. 2026-03-01 is EST (UTC-5); 2026-03-08 is EDT (UTC-4) after the 02:00 jump.
    before = compute_next_run(_weekly(6, "09:00"), NY, _utc(2026, 2, 22, 15))  # Sun 10:00 EST, already past
    assert before == _utc(2026, 3, 1, 14)
    across = compute_next_run(_weekly(6, "09:00"), NY, _utc(2026, 3, 1, 15))
    assert across == _utc(2026, 3, 8, 13)  # 09:00 EDT


def test_weekly_time_inside_the_spring_forward_gap_moves_to_first_valid_minute():
    # Sunday 2026-03-08 02:30 does not exist in New York; the clock jumps 02:00 -> 03:00.
    assert compute_next_run(_weekly(6, "02:30"), NY, _utc(2026, 3, 2, 12)) == _utc(2026, 3, 8, 7)  # 03:00 EDT


def test_weekly_keeps_local_time_across_fall_back():
    # 2026-11-01 02:00 EDT falls back to 01:00 EST.
    assert compute_next_run(_weekly(6, "09:00"), NY, _utc(2026, 10, 25, 14)) == _utc(2026, 11, 1, 14)  # 09:00 EST


def test_monthly_keeps_local_time_across_spring_forward():
    # day 15 at 09:00: Feb is EST (14:00 UTC), March is EDT (13:00 UTC).
    assert compute_next_run(_monthly(15, "09:00"), NY, _utc(2026, 2, 20, 12)) == _utc(2026, 3, 15, 13)


def test_monthly_repeated_time_after_fall_back_uses_first_occurrence():
    # 2026-11-01 01:30 happens twice; the first is EDT (UTC-4) = 05:30 UTC.
    assert compute_next_run(_monthly(1, "01:30"), NY, _utc(2026, 10, 2, 12)) == _utc(2026, 11, 1, 5, 30)


def test_strictly_after_now_and_year_rollover():
    s = _monthly(1, "06:00")
    exactly = _utc(2026, 12, 1, 11)  # 06:00 EST
    assert compute_next_run(s, NY, exactly) == _utc(2027, 1, 1, 11)
    assert compute_next_run(_weekly(0, "06:00"), NY, _utc(2026, 6, 1, 10)) == _utc(2026, 6, 8, 10)
