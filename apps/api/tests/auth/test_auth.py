"""Run against a disposable migrated database; never use a production database."""

import asyncio
import os
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from clinic_api.main import create_app
from clinic_core.auth.security import digest, now
from clinic_core.database import system_session
from clinic_core.settings import Settings
from clinic_db.models.auth import AuthSession, OAuthTransaction, User


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


async def test_onboarding_restart_logout_and_replay(system):
    app, client = system
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    result = await login(client)
    assert result.headers["location"].endswith("/onboarding")
    cookie = client.cookies.get("avishkar_session")
    assert "HttpOnly" in result.headers.get_list("set-cookie")[0]
    assert "SameSite=lax" in result.headers.get_list("set-cookie")[0]
    assert (await client.post("/api/v1/workspaces", json={"name": "Practice", "timezone": "UTC"})).status_code == 403
    csrf = await headers(client)
    payload = {"name": "Practice", "timezone": "UTC"}
    results = await asyncio.gather(*(client.post("/api/v1/workspaces", headers=csrf, json=payload) for _ in range(2)))
    assert all(r.status_code in (200, 201) for r in results)
    assert results[0].json()["id"] == results[1].json()["id"]
    restarted = create_app(app.state.settings, google=FakeGoogle())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted),
        base_url="http://localhost:3000",
        cookies={"avishkar_session": cookie},
    ) as other:
        assert (await other.get("/api/v1/auth/me")).json()["workspace"]["name"] == "Practice"
    await restarted.state.engine.dispose()
    assert (
        await client.post("/api/v1/auth/logout", headers={**csrf, "Origin": "https://evil.example"})
    ).status_code == 403
    assert (await client.post("/api/v1/auth/logout", headers=csrf)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers={"Cookie": "avishkar_session=" + cookie})).status_code == 401


async def test_binding_state_expiry_and_replay(system):
    app, client = system
    state = await begin(client)
    binding = client.cookies.get("avishkar_oauth")
    client.cookies.clear()
    result = await client.get("/api/v1/auth/google/callback", params={"state": state, "code": "test"})
    assert "invalid_login" in result.headers["location"]
    client.cookies.set("avishkar_oauth", binding)
    result = await client.get("/api/v1/auth/google/callback", params={"state": state, "code": str(uuid.uuid4())})
    assert result.headers["location"].endswith("/onboarding")
    client.cookies.set("avishkar_oauth", binding)
    assert (
        "invalid_login"
        in (await client.get("/api/v1/auth/google/callback", params={"state": state, "code": "test"})).headers[
            "location"
        ]
    )
    state = await begin(client)
    async with app.state.session_factory() as db:
        txn = (
            await db.execute(select(OAuthTransaction).where(OAuthTransaction.state_hash == digest(state)))
        ).scalar_one()
        txn.expires_at = now() - timedelta(seconds=1)
        await db.commit()
    assert (
        "invalid_login"
        in (await client.get("/api/v1/auth/google/callback", params={"state": state, "code": "test"})).headers[
            "location"
        ]
    )


async def test_identity_does_not_merge_email_and_workspace_isolation(system):
    app, first = system
    subject = str(uuid.uuid4())
    await login(first, subject)
    first_id = (await first.get("/api/v1/auth/me")).json()["user"]["id"]
    workspace = (
        await first.post(
            "/api/v1/workspaces",
            headers=await headers(first),
            json={"name": "One", "timezone": "UTC"},
        )
    ).json()
    await login(first, subject)
    assert (await first.get("/api/v1/auth/me")).json()["user"]["id"] == first_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(str(uuid.uuid4()), 123)), base_url="http://localhost:3000"
    ) as second:
        await login(second)
        me = (await second.get("/api/v1/auth/me")).json()
        assert me["user"]["id"] != first_id
        assert me["needs_onboarding"]
        assert (await second.get("/api/v1/workspaces/" + workspace["id"])).status_code == 403


@pytest.mark.parametrize("condition", ["expired", "disabled"])
async def test_inactive_session_rejected(system, condition):
    app, client = system
    await login(client)
    async with app.state.session_factory() as db:
        session = (
            await db.execute(
                select(AuthSession).where(AuthSession.token_hash == digest(client.cookies.get("avishkar_session")))
            )
        ).scalar_one()
        if condition == "expired":
            session.expires_at = now() - timedelta(seconds=1)
        else:
            user = await db.get(User, session.user_id)
            user.active = False
        await db.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_cancel_and_provider_failure(system):
    _, client = system
    state = await begin(client)
    result = await client.get("/api/v1/auth/google/callback", params={"state": state, "error": "access_denied"})
    assert "cancelled" in result.headers["location"]
    assert "failed" in (await login(client, "bad")).headers["location"]
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_callback_race_and_session_rotation(system):
    _, client = system
    subject = str(uuid.uuid4())
    state = await begin(client)
    binding = client.cookies.get("avishkar_oauth")
    results = await asyncio.gather(
        *(
            client.get(
                "/api/v1/auth/google/callback",
                params={"state": state, "code": subject},
                headers={"Cookie": "avishkar_oauth=" + binding},
            )
            for _ in range(2)
        )
    )
    assert sum(r.headers["location"].endswith("/onboarding") for r in results) == 1
    assert sum("invalid_login" in r.headers["location"] for r in results) == 1
    old = client.cookies.get("avishkar_session")
    await login(client, subject)
    assert client.cookies.get("avishkar_session") != old
    assert (await client.get("/api/v1/auth/me", headers={"Cookie": "avishkar_session=" + old})).status_code == 401


async def test_removed_membership_rejected(system):
    app, client = system
    await login(client)
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            headers=await headers(client),
            json={"name": "Removed", "timezone": "UTC"},
        )
    ).json()
    from clinic_db.models.core import Staff as Membership

    async with system_session(database_url=app.state.settings.database_system_url) as db:
        member = (
            await db.execute(select(Membership).where(Membership.tenant_id == uuid.UUID(workspace["id"])))
        ).scalar_one()
        member.active = False
        await db.commit()
    assert (await client.get("/api/v1/workspaces/" + workspace["id"])).status_code == 403
    assert (
        await client.post(
            "/api/v1/workspaces",
            headers=await headers(client),
            json={"name": "Another", "timezone": "UTC"},
        )
    ).status_code == 403


async def test_platform_context_and_tenant_authorization(system):
    app, client = system
    assert (await client.get("/me", headers={"X-Tenant-Id": str(uuid.uuid4())})).status_code == 401
    await login(client)
    workspace = (
        await client.post(
            "/api/v1/workspaces", headers=await headers(client), json={"name": "Platform clinic", "timezone": "UTC"}
        )
    ).json()
    tenant_id = workspace["id"]
    me = await client.get("/me", headers={"X-Tenant-Id": tenant_id, "X-Staff-Role": "provider", "X-Staff-Id": "forged"})
    assert me.status_code == 200
    assert me.json()["role"] == "owner"
    assert (await client.get("/me", headers={"X-Tenant-Id": str(uuid.uuid4())})).status_code == 403
    assert (await client.post("/features/reactivation/campaigns", json={"name": "No CSRF"})).status_code == 403


async def test_auth_role_cannot_read_clinic_data(system):
    app, _ = system
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with app.state.session_factory() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("SELECT * FROM core.patients"))


async def test_workspace_settings_enforce_membership_roles_csrf_and_audit(system):
    from clinic_db.models.core import Staff, Tenant

    app, client = system
    await login(client)
    csrf = await headers(client)
    workspace = (
        await client.post("/api/v1/workspaces", headers=csrf, json={"name": "Management test", "timezone": "UTC"})
    ).json()
    path = "/api/v1/workspaces/" + workspace["id"]
    user_id = uuid.UUID((await client.get("/api/v1/auth/me")).json()["user"]["id"])
    payload = {
        "name": "Updated clinic",
        "timezone": "Asia/Kolkata",
        "clinic_type": "wellness",
        "phone": "+919876543210",
        "address": "Bengaluru",
    }
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        tenant = await db.get(Tenant, uuid.UUID(workspace["id"]))
        tenant.settings = {**tenant.settings, "unrelated_config": {"enabled": True}}
    assert (await client.post(path + "/settings", json=payload)).status_code == 403
    assert (
        await client.post(path + "/settings", headers={**csrf, "Origin": "https://evil.example"}, json=payload)
    ).status_code == 403
    for field, value in (("name", "  "), ("timezone", "Invalid/Zone"), ("phone", "123"), ("clinic_type", "other")):
        assert (await client.post(path + "/settings", headers=csrf, json={**payload, field: value})).status_code == 422
    assert (
        await client.post(path + "/settings", headers=csrf, json={**payload, "baa_signed_at": "2026-01-01"})
    ).status_code == 422
    result = await client.post(path + "/settings", headers=csrf, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["name"] == "Updated clinic"
    assert (await client.get(path + "/settings")).json()["address"] == "Bengaluru"
    assert (await client.get("/api/v1/auth/me")).json()["workspace"]["name"] == "Updated clinic"
    assert len((await client.get(path + "/members")).json()) == 1
    events = (await client.get(path + "/audit")).json()
    assert any(event["action"] == "workspace.updated" for event in events)
    foreign_id = uuid.uuid4()
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        db.add(Tenant(id=foreign_id, name="Unrelated workspace", timezone="UTC", clinic_type="wellness"))
    foreign = "/api/v1/workspaces/" + str(foreign_id)
    for suffix in ("settings", "members", "audit"):
        assert (await client.get(foreign + "/" + suffix)).status_code == 403
    assert (await client.post(foreign + "/settings", headers=csrf, json=payload)).status_code == 403
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        tenant = await db.get(Tenant, uuid.UUID(workspace["id"]))
        assert tenant.settings["unrelated_config"] == {"enabled": True}
        assert tenant.baa_signed_at is None
        member = await db.scalar(select(Staff).where(Staff.user_id == user_id))
        member.role = "front_desk"
    assert (await client.get(path + "/settings")).status_code == 200
    for suffix in ("members", "audit"):
        assert (await client.get(path + "/" + suffix)).status_code == 403
    assert (await client.post(path + "/settings", headers=csrf, json=payload)).status_code == 403
    # Permission is checked from the current database membership, not a role supplied by the client.
    assert (
        await client.post(path + "/settings", headers={**csrf, "X-Staff-Role": "owner"}, json=payload)
    ).status_code == 403
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        member = await db.scalar(select(Staff).where(Staff.user_id == user_id))
        member.role = "office_manager"
    assert (await client.post(path + "/settings", headers=csrf, json=payload)).status_code == 200
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        member = await db.scalar(select(Staff).where(Staff.user_id == user_id))
        member.active = False
    assert (await client.get(path + "/settings")).status_code == 403
