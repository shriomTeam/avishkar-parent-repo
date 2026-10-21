"""Customisable figures: the audit diff, the schedule's settings version, the dollar cutoff field, the file echo."""

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from test_csv_api import make_file  # noqa: I001 - the one CSV builder the file-analysis tests use

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.api.settings import config_changes
from clinic_reactivation.router import router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


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


async def _audit_details(tenant):
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.settings.saved"))).all()
    return sorted((r.details for r in rows), key=lambda d: d["to_version"])


# --- the diff -------------------------------------------------------------------------------


def test_no_difference_gives_no_changes():
    assert config_changes(_config(), _config()) == []


def test_changes_name_the_setting_and_the_old_and_new_numbers():
    new = _config(**{"dormant.min_days_since_visit": 200, "types.one_and_done.enabled": False})
    new["types"]["lapsed_high_value"]["spend_cents_min"] = 500000
    assert config_changes(_config(), new) == [
        {"setting": "dormant.min_days_since_visit", "from": 180, "to": 200},
        {"setting": "types.lapsed_high_value.spend_cents_min", "from": None, "to": 500000},
        {"setting": "types.one_and_done.enabled", "from": True, "to": False},
    ]


def test_a_changed_map_is_named_without_its_keys_or_values():
    new = _config(**{"dormant.rebooking_days_by_category": {"secret clinic word": 90}})
    changes = config_changes(_config(), new)
    assert changes == [{"setting": "dormant.rebooking_days_by_category"}]
    assert "secret clinic word" not in str(changes)


# --- the endpoints --------------------------------------------------------------------------


async def test_save_audit_holds_the_changes_and_nothing_else(client):
    t = await create_test_tenant()
    body = _config(**{"dormant.min_days_since_visit": 200, "revenue.rate_high": 0.2})
    r = await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=body)
    assert r.status_code == 200
    assert await _audit_details(t) == [
        {
            "from_version": 0,
            "to_version": 1,
            "changes": [
                {"setting": "dormant.min_days_since_visit", "from": 180, "to": 200},
                {"setting": "revenue.rate_high", "from": 0.15, "to": 0.2},
            ],
        }
    ]
    again = await client.put("/settings", headers=_h(t, **{"If-Match": "1"}), json=_config())
    assert again.status_code == 200  # reset to defaults is a new version
    assert (await _audit_details(t))[-1]["changes"][0] == {
        "setting": "dormant.min_days_since_visit",
        "from": 200,
        "to": 180,
    }


async def test_schedule_carries_the_settings_version_for_every_viewer(client):
    t = await create_test_tenant()
    assert (await client.get("/schedule", headers=_h(t, "front_desk"))).json()["settings_version"] == 0
    await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=_config())
    assert (await client.get("/schedule", headers=_h(t, "front_desk"))).json()["settings_version"] == 1


# --- the dollar cutoff field ----------------------------------------------------------------


def test_the_cutoff_is_empty_by_default_and_an_old_config_still_loads():
    assert ReactivationSettings().types.lapsed_high_value.spend_cents_min is None
    legacy = ReactivationSettings().model_dump(mode="json")
    del legacy["types"]["lapsed_high_value"]["spend_cents_min"]
    assert ReactivationSettings.model_validate(legacy) == ReactivationSettings()


@pytest.mark.parametrize("value", [0, -5, 100_000_001, 1.5, "abc"])
async def test_a_bad_cutoff_gives_422(client, value):
    t = await create_test_tenant()
    body = _config()
    body["types"]["lapsed_high_value"]["spend_cents_min"] = value
    assert (await client.put("/settings", headers=_h(t, **{"If-Match": "0"}), json=body)).status_code == 422


# --- the file analysis echoes the settings it used -----------------------------------------


async def test_a_file_analysis_echoes_the_settings_and_their_version(client):
    t = await create_test_tenant()
    r = await client.post("/csv-analysis", content=make_file(25), headers={**_h(t), "Content-Type": "text/csv"})
    assert r.status_code == 200
    body = r.json()
    assert (body["settings_source"], body["settings_version"]) == ("defaults", 0)
    assert body["settings"] == _config()
    await client.put(
        "/settings", headers=_h(t, **{"If-Match": "0"}), json=_config(**{"dormant.min_days_since_visit": 300})
    )
    body = (
        await client.post("/csv-analysis", content=make_file(25), headers={**_h(t), "Content-Type": "text/csv"})
    ).json()
    assert (body["settings_source"], body["settings_version"]) == ("saved", 1)
    assert body["settings"]["dormant"]["min_days_since_visit"] == 300
