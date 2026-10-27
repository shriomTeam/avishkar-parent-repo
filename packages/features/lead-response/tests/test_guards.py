"""The guards, tested at the server level with no UI: a test-only app that applies them the way routers will."""

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI

from clinic_core.api import require_feature, require_role
from clinic_core.auth.database import create_database
from clinic_core.settings import Settings
from clinic_db.models.core import StaffRole
from clinic_lead_response.roles import SETTINGS_ROLES, TASK_ROLES

router = APIRouter(dependencies=[Depends(require_feature("lead_response"))])


@router.get("/tasks", dependencies=[Depends(require_role(*TASK_ROLES))])
async def tasks() -> dict:
    return {"ok": True}


@router.put("/settings", dependencies=[Depends(require_role(*SETTINGS_ROLES))])
async def settings() -> dict:
    return {"ok": True}


app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)  # the explicit dev-header adapter, as other isolated router tests
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _h(tenant, role):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


def test_role_sets():
    assert set(TASK_ROLES) == {StaffRole.OWNER, StaffRole.OFFICE_MANAGER, StaffRole.FRONT_DESK, StaffRole.CONSULTANT}
    assert set(SETTINGS_ROLES) == {StaffRole.OWNER, StaffRole.OFFICE_MANAGER}
    assert StaffRole.PROVIDER not in TASK_ROLES + SETTINGS_ROLES


async def test_a_tenant_without_the_feature_is_blocked(client, make_tenant):
    t = await make_tenant(())
    for method, path in (("GET", "/tasks"), ("PUT", "/settings")):
        response = await client.request(method, path, headers=_h(t, "owner"))
        assert response.status_code == 403
        assert "lead_response" in response.json()["detail"]


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("office_manager", 200), ("front_desk", 200), ("consultant", 200), ("provider", 403)],
)
async def test_task_roles(client, make_tenant, role, status):
    t = await make_tenant()
    assert (await client.get("/tasks", headers=_h(t, role))).status_code == status


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("office_manager", 200), ("front_desk", 403), ("consultant", 403), ("provider", 403)],
)
async def test_settings_roles(client, make_tenant, role, status):
    t = await make_tenant()
    assert (await client.put("/settings", headers=_h(t, role))).status_code == status
