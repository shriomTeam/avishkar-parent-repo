"""The settings page decides what an API refusal means by its exact text (web/lib/gate.ts). Nothing else asserted
these texts, so they are pinned here: if the platform words a refusal differently, this fails before the page quietly
shows a 404 (or the wrong view) to people who should see something else.
"""

import re
from pathlib import Path

import pytest
from lr_api import URL, build_app, client_for, headers

from clinic_core.api import require_role
from clinic_db.models.core import StaffRole

GATE_SOURCE = (Path(__file__).resolve().parents[1] / "web" / "lib" / "gate.ts").read_text()

NOT_ENABLED = "Feature 'lead_response' is not enabled"
ROLE_REFUSED = "feature_access_denied"
ROLE_DEPENDENCY_REFUSED = "Not allowed for your role"

app = build_app()


@pytest.fixture
async def client():
    async with client_for(app) as c:
        yield c


def gate_pattern(name: str) -> re.Pattern:
    """A regular expression literal from gate.ts (/^...$/), read as the page reads it."""
    found = re.search(rf"const {name} = /(.+)/;", GATE_SOURCE)
    assert found, f"gate.ts no longer defines {name}"
    return re.compile(found.group(1))


async def test_a_clinic_without_the_feature_gets_the_exact_not_enabled_text(client, make_tenant):
    t = await make_tenant(features=())
    r = await client.get(URL, headers=headers(t, "owner"))
    assert r.status_code == 403
    assert r.json() == {"detail": NOT_ENABLED}


async def test_the_page_matches_that_text_as_not_found(client, make_tenant):
    t = await make_tenant(features=())
    detail = (await client.get(URL, headers=headers(t, "owner"))).json()["detail"]
    assert gate_pattern("NOT_ENABLED").match(detail)


async def test_a_clinic_with_the_feature_is_not_told_it_is_not_enabled(client, make_tenant):
    t = await make_tenant()
    r = await client.get(URL, headers=headers(t, "owner"))
    assert r.status_code == 200


@pytest.mark.parametrize("role", ["front_desk", "consultant", "provider"])
async def test_a_role_the_platform_refuses_gets_the_exact_role_text(client, make_tenant, role):
    t = await make_tenant()
    r = await client.get(URL, headers=headers(t, role))
    assert r.status_code == 403
    assert r.json() == {"detail": ROLE_REFUSED}
    assert not gate_pattern("NOT_ENABLED").match(r.json()["detail"])


async def test_the_role_check_inside_the_feature_uses_the_text_the_page_expects():
    """Not reachable through the platform today (it refuses those roles first), so the dependency is called directly."""
    from types import SimpleNamespace

    dependency = require_role(StaffRole.OWNER)
    with pytest.raises(Exception) as caught:
        await dependency(SimpleNamespace(role=StaffRole.FRONT_DESK))
    assert caught.value.status_code == 403
    assert caught.value.detail == ROLE_DEPENDENCY_REFUSED


def test_the_page_knows_both_role_texts():
    assert f'"{ROLE_REFUSED}"' in GATE_SOURCE
    assert f'"{ROLE_DEPENDENCY_REFUSED}"' in GATE_SOURCE
