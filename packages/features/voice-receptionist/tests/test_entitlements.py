"""Run against a disposable migrated database; never use a production database."""

import os
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import pytest_asyncio

from clinic_api.main import create_app
from clinic_core.database import tenant_session
from clinic_core.entitlements import set_feature
from clinic_core.settings import Settings


class FakeGoogle:
    async def authorization_url(self, state, nonce, verifier):
        return "https://accounts.google.com/test?" + urlencode({"state": state})

    async def identity(self, code, nonce, verifier):
        if code == "bad":
            raise ValueError("provider rejected token")
        return {
            "sub": code,
            "email": "same@example.com",
            "name": "Test Owner",
            "email_verified": True,
        }


@pytest_asyncio.fixture
async def system():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable migrated PostgreSQL database")
    settings = Settings(
        database_url=url,
        database_auth_url=os.environ.get("TEST_AUTH_DATABASE_URL", url),
        database_system_url=os.environ.get("TEST_SYSTEM_DATABASE_URL", url),
        google_client_id="test",
        google_client_secret="test",
    )
    app = create_app(settings, google=FakeGoogle())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(str(uuid.uuid4()), 123)), base_url="http://localhost:3000"
    ) as client:
        yield app, client
    await app.state.engine.dispose()


async def begin(client):
    response = await client.get("/api/v1/auth/google/login")
    assert response.status_code == 302
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


async def login(client, subject=None):
    state = await begin(client)
    return await client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": subject or str(uuid.uuid4())},
    )


async def headers(client):
    me = (await client.get("/api/v1/auth/me")).json()
    return {"Origin": "http://localhost:3000", "X-CSRF-Token": me["csrf_token"]}


async def test_voice_entitlement_gates_backend_and_navigation(system):
    app, client = system
    await login(client)
    workspace = (
        await client.post(
            "/api/v1/workspaces", headers=await headers(client), json={"name": "Voice clinic", "timezone": "UTC"}
        )
    ).json()
    tenant_id = uuid.UUID(workspace["id"])
    me = (await client.get("/me")).json()
    assert any(item["feature"] == "voice_receptionist" for item in me["nav"])
    assert (await client.get("/features/voice_receptionist/status")).status_code == 200
    async with tenant_session(tenant_id, database_url=app.state.settings.database_url) as db:
        await set_feature(db, tenant_id, "voice_receptionist", enabled=False)
    assert (await client.get("/features/voice_receptionist/status")).status_code == 403
    assert not any(item["feature"] == "voice_receptionist" for item in (await client.get("/me")).json()["nav"])
