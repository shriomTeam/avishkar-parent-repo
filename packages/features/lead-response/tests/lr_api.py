"""A test app that mounts the real lead response router the way apps/api does, plus small request helpers."""

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from clinic_core.api import require_feature
from clinic_core.auth.database import create_database
from clinic_core.settings import Settings
from clinic_lead_response.feature import feature
from clinic_lead_response.settings_model import LeadResponseSettings

PLATFORM_GAP = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="platform permissions.py does not grant lead_response to this role yet; roles.py keeps the approved design",
)

URL = "/features/lead_response/settings"


def build_app() -> FastAPI:
    app = FastAPI()
    # This isolated router test intentionally exercises the explicit dev-header adapter.
    app.state.settings = Settings(allow_dev_auth=True)
    app.state.engine, app.state.session_factory = create_database(app.state.settings)

    # The same handler apps/api registers: a rejected body is never echoed back or logged.
    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    app.include_router(
        feature.router, prefix="/features/lead_response", dependencies=[Depends(require_feature("lead_response"))]
    )
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def headers(tenant, role="owner", staff="staff-1", **extra):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role, "X-Staff-Id": staff, **extra}


def body(**overrides):
    """A complete valid body: the defaults with the given top-level settings replaced."""
    return {**LeadResponseSettings().model_dump(mode="json"), **overrides}


async def put(client, tenant, version, payload=None, **kw):
    extra = {} if version is None else {"If-Match": str(version)}
    return await client.put(URL, json=body() if payload is None else payload, headers=headers(tenant, **kw, **extra))
