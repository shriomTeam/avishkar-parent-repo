"""Admin console tests. They run against the local Postgres (pnpm db:up && pnpm db:migrate), like the API tests."""

import re
import time
import uuid

import httpx
import pytest
from sqlalchemy import select

from clinic_admin.app import create_app
from clinic_admin.security import new_session
from clinic_admin.service import feature_catalog
from clinic_admin.settings import AdminSettings
from clinic_core.database import system_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Tenant, TenantFeature
from clinic_db.models.ops import AuditLog

PASSWORD = "a-long-test-password-for-admin"


def make_settings(**changes) -> AdminSettings:
    values = {"username": "operator", "password": PASSWORD, "session_key": "k" * 40, "app_env": "test"}
    return AdminSettings(**(values | changes))


@pytest.fixture
async def client():
    app = create_app(make_settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def signed_in(client):
    r = await client.post("/login", data={"username": "operator", "password": PASSWORD})
    assert r.status_code == 303
    return client


def token_of(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def csrf(client, path="/") -> str:
    return token_of((await client.get(path)).text)


async def test_pages_need_a_session(client):
    for path in ("/", "/audit", f"/clinics/{uuid.uuid4()}"):
        r = await client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert (await client.get("/health")).status_code == 200


async def test_login_rejects_wrong_credentials_and_sets_a_strict_cookie(client):
    bad = await client.post("/login", data={"username": "operator", "password": "wrong"})
    assert bad.status_code == 401 and "admin_session" not in bad.headers.get("set-cookie", "")
    good = await client.post("/login", data={"username": "operator", "password": PASSWORD})
    cookie = good.headers["set-cookie"].lower()
    assert good.status_code == 303 and "httponly" in cookie and "samesite=strict" in cookie


async def test_login_is_blocked_after_repeated_failures():
    app = create_app(make_settings(max_login_failures=3))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        for _ in range(3):
            assert (await c.post("/login", data={"username": "operator", "password": "x"})).status_code == 401
        blocked = await c.post("/login", data={"username": "operator", "password": PASSWORD})
        assert blocked.status_code == 429


async def test_forged_or_expired_cookie_is_refused(client, monkeypatch):
    settings = make_settings()
    cookie = new_session(settings)
    client.cookies.set("admin_session", cookie)
    assert (await client.get("/")).status_code == 200
    client.cookies.set("admin_session", cookie[:-1] + ("0" if cookie[-1] != "0" else "1"))
    assert (await client.get("/")).status_code == 303
    client.cookies.set("admin_session", "e30=.deadbeef")
    assert (await client.get("/")).status_code == 303
    client.cookies.set("admin_session", cookie)
    later = time.time() + settings.session_ttl_seconds + 5
    monkeypatch.setattr("clinic_admin.security.time.time", lambda: later)
    assert (await client.get("/")).status_code == 303


async def test_security_headers_are_set(signed_in):
    r = await signed_in.get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_clinic_list_shows_and_filters_clinics(signed_in):
    tenant_id = await create_test_tenant(("reactivation",))
    async with system_session() as s:
        name = (await s.get(Tenant, tenant_id)).name
    page = (await signed_in.get("/", params={"q": name})).text
    assert name in page and f"/clinics/{tenant_id}" in page
    # A search with LIKE wildcards matches only a literal percent sign, not everything.
    assert f"/clinics/{tenant_id}" not in (await signed_in.get("/", params={"q": "%"})).text


async def test_turning_a_feature_on_and_off_is_saved_and_audited(signed_in):
    tenant_id = await create_test_tenant()
    key = next(iter(feature_catalog()))
    path = f"/clinics/{tenant_id}/features/{key}"
    token = await csrf(signed_in, f"/clinics/{tenant_id}")

    r = await signed_in.post(path, data={"enabled": "1", "csrf": token})
    assert r.status_code == 303
    async with system_session() as s:
        row = await s.get(TenantFeature, (key, tenant_id))
        assert row.enabled and row.expires_at is None

    await signed_in.post(path, data={"enabled": "0", "csrf": token})
    async with system_session() as s:
        assert not (await s.get(TenantFeature, (key, tenant_id))).enabled
        actions = list(
            await s.scalars(select(AuditLog.action).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id))
        )
    assert actions == ["admin.feature.enabled", "admin.feature.disabled"]


async def test_changing_a_feature_keeps_the_clinic_settings(signed_in):
    key = next(iter(feature_catalog()))
    tenant_id = await create_test_tenant()
    async with system_session() as s:
        s.add(TenantFeature(feature_key=key, tenant_id=tenant_id, enabled=True, config={"mode": "custom"}))
    token = await csrf(signed_in, f"/clinics/{tenant_id}")
    await signed_in.post(
        f"/clinics/{tenant_id}/features/{key}", data={"enabled": "1", "expires": "2999-01-01", "csrf": token}
    )
    async with system_session() as s:
        row = await s.get(TenantFeature, (key, tenant_id))
        assert row.config == {"mode": "custom"} and row.expires_at.year == 2999


async def test_unknown_feature_and_past_date_are_refused(signed_in):
    tenant_id = await create_test_tenant()
    token = await csrf(signed_in, f"/clinics/{tenant_id}")
    key = next(iter(feature_catalog()))
    unknown = await signed_in.post(f"/clinics/{tenant_id}/features/not_a_feature", data={"enabled": "1", "csrf": token})
    past = await signed_in.post(
        f"/clinics/{tenant_id}/features/{key}", data={"enabled": "1", "expires": "2001-01-01", "csrf": token}
    )
    bad = await signed_in.post(
        f"/clinics/{tenant_id}/features/{key}", data={"enabled": "1", "expires": "soon", "csrf": token}
    )
    assert unknown.status_code == past.status_code == bad.status_code == 400
    async with system_session() as s:
        assert await s.scalar(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id)) is None


async def test_post_without_a_valid_form_token_changes_nothing(signed_in):
    tenant_id = await create_test_tenant()
    key = next(iter(feature_catalog()))
    for token in ("", "forged"):
        r = await signed_in.post(f"/clinics/{tenant_id}/features/{key}", data={"enabled": "1", "csrf": token})
        assert r.status_code == 303 and r.headers["location"] == "/login"
    async with system_session() as s:
        assert await s.scalar(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id)) is None


async def test_suspending_needs_confirmation_and_is_audited(signed_in):
    tenant_id = await create_test_tenant()
    token = await csrf(signed_in, f"/clinics/{tenant_id}")
    path = f"/clinics/{tenant_id}/status"
    unconfirmed = await signed_in.post(path, data={"status": "suspended", "csrf": token})
    assert unconfirmed.status_code == 400
    async with system_session() as s:
        assert (await s.get(Tenant, tenant_id)).status == "active"
    done = await signed_in.post(path, data={"status": "suspended", "confirm": "yes", "csrf": token})
    assert done.status_code == 303
    async with system_session() as s:
        assert (await s.get(Tenant, tenant_id)).status == "suspended"
        action = await s.scalar(select(AuditLog.action).where(AuditLog.tenant_id == tenant_id))
    assert action == "admin.tenant.status_changed"
    assert "admin.tenant.status_changed" in (await signed_in.get("/audit")).text
    assert (await signed_in.post(path, data={"status": "bogus", "confirm": "yes", "csrf": token})).status_code == 400


async def test_unknown_clinic_is_a_404_and_names_are_escaped(signed_in):
    assert (await signed_in.get(f"/clinics/{uuid.uuid4()}")).status_code == 404
    assert (await signed_in.get("/clinics/not-a-uuid")).status_code == 400
    tenant_id = await create_test_tenant()
    async with system_session() as s:
        (await s.get(Tenant, tenant_id)).name = "<script>alert(1)</script>"
    html = (await signed_in.get(f"/clinics/{tenant_id}")).text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_settings_refuse_weak_production_values():
    with pytest.raises(ValueError):
        make_settings(session_key="short")
    with pytest.raises(ValueError):
        make_settings(app_env="production", cookie_secure=True, password="too-short")
    with pytest.raises(ValueError):
        make_settings(app_env="production", password="p" * 30)  # not Secure
