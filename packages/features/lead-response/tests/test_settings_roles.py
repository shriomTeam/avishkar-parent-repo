"""Who may read and who may save, through the real mount (feature gate, then the role check)."""

import pytest
from lr_api import PLATFORM_GAP, URL, body, build_app, client_for, headers, put

app = build_app()


@pytest.fixture
async def client():
    async with client_for(app) as c:
        yield c


@pytest.mark.parametrize(
    ("role", "status"),
    [
        ("owner", 200),
        ("office_manager", 200),
        pytest.param("front_desk", 200, marks=PLATFORM_GAP),
        pytest.param("consultant", 200, marks=PLATFORM_GAP),
        ("provider", 403),
    ],
)
async def test_who_may_read_settings(client, make_tenant, role, status):
    t = await make_tenant()
    assert (await client.get(URL, headers=headers(t, role))).status_code == status


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("office_manager", 200), ("front_desk", 403), ("consultant", 403), ("provider", 403)],
)
async def test_who_may_save_settings(client, make_tenant, role, status):
    t = await make_tenant()
    assert (await put(client, t, 0, body(holding_minutes=10), role=role)).status_code == status


async def test_a_refused_role_changes_nothing(client, make_tenant):
    t = await make_tenant()
    for role in ("front_desk", "consultant", "provider"):
        assert (await put(client, t, 0, body(holding_minutes=10), role=role)).status_code == 403
    assert (await client.get(URL, headers=headers(t))).json()["version"] == 0
