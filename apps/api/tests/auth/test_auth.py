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
    events = (await client.get(path + "/audit")).json()["items"]
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


class InvitationGoogle(FakeGoogle):
    async def identity(self, code, nonce, verifier):
        return {"sub": code, "email": code + "@example.com", "name": code, "email_verified": True, "hd": "example.com"}


async def invitation_setup(system):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    app, client = system
    app.state.google = InvitationGoogle()
    settings = app.state.settings
    settings.invitations_enabled = True
    settings.email_provider = "test"
    settings.email_payload_encryption_key = SecretStr(Fernet.generate_key().decode())
    await login(client, "owner" + uuid.uuid4().hex)
    csrf = await headers(client)
    workspace = (
        await client.post("/api/v1/workspaces", headers=csrf, json={"name": "Shared workspace", "timezone": "UTC"})
    ).json()
    return app, client, csrf, workspace


async def invitation_link(app):
    from clinic_engagement.email.service import deliver_due

    messages = []

    async def capture(**kwargs):
        messages.append(kwargs)
        return "captured"

    await deliver_due(app.state.settings, sender=capture)
    assert messages
    import re

    return re.search(r"/invite#token=([^\s]+)", messages[-1]["template"].text).group(1)


def feature_denied_status(key):
    # The platform-removal check also runs this suite without optional features installed.
    from clinic_core.features import load_features

    return 403 if key in load_features() else 404


async def test_invitation_accepts_same_workspace_and_cannot_escalate(system):
    from sqlalchemy import func

    from clinic_db.models.core import Staff
    from clinic_db.models.membership import EmailDelivery

    app, owner, csrf, workspace = await invitation_setup(system)
    recipient = "recipient" + uuid.uuid4().hex
    base = "/api/v1/workspaces/" + workspace["id"]
    data = {"email": recipient + "@example.com", "role": "front_desk"}
    assert (await owner.post(base + "/invitations", json=data)).status_code == 403
    assert (await owner.post(base + "/invitations", headers=csrf, json={**data, "role": "owner"})).status_code == 403
    created = await owner.post(base + "/invitations", headers=csrf, json=data)
    assert created.status_code == 201, created.text
    assert (await owner.post(base + "/invitations", headers=csrf, json=data)).status_code == 409
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.scalar(select(EmailDelivery).where(EmailDelivery.tenant_id == uuid.UUID(workspace["id"])))
        assert recipient not in row.payload  # recipient and bearer link are encrypted at rest
    token = await invitation_link(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as user:
        assert (await user.post("/api/v1/invitations/context", json={"token": token})).status_code == 403
        assert (
            await user.post(
                "/api/v1/invitations/context", headers={"Origin": "http://localhost:3000"}, json={"token": token}
            )
        ).status_code == 200
        result = await login(user, recipient)
        assert result.headers["location"].endswith("/invite")
        assert (await user.get("/api/v1/invitations/current")).json()["workspace_name"] == "Shared workspace"
        user_csrf = await headers(user)
        result = await user.post("/api/v1/invitations/accept", headers=user_csrf, json={"role": "owner"})
        assert result.status_code == 422
        context_cookie = user.cookies.get("avishkar_invitation")
        requests = [
            user.build_request("POST", "/api/v1/invitations/accept", headers=user_csrf, json={}) for _ in range(2)
        ]
        accepted = await asyncio.gather(*(user.send(request) for request in requests))
        assert [result.status_code for result in accepted] == [200, 200], [result.text for result in accepted]
        me = (await user.get("/api/v1/auth/me")).json()
        assert me["workspace"]["id"] == workspace["id"]
        assert me["memberships"][0]["role"] == "front_desk"
        assert len(me["memberships"]) == 1
        assert (await owner.get(base + "/invitations")).json()["invitations"] == []
        assert (
            await user.post(
                base + "/invitations", headers=user_csrf, json={"email": "other@example.com", "role": "office_manager"}
            )
        ).status_code == 403
        assert (await user.get(base + "/members")).status_code == 403
        assert (await user.get("/me", headers={"X-Tenant-Id": str(uuid.uuid4())})).status_code == 403
        assert (
            await user.post("/features/voice_receptionist/inbound/agents", headers=user_csrf, json={})
        ).status_code in {feature_denied_status("voice_receptionist"), 422}
        # A lost response/replayed same-browser accept cannot grant another membership.
        user.cookies.set("avishkar_invitation", context_cookie)
        assert (await user.post("/api/v1/invitations/accept", headers=user_csrf, json={})).status_code == 200
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            # Other packages create tenants concurrently under Turbo. Assert this
            # recipient received no new owner workspace instead of counting global tenants.
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Staff)
                    .where(Staff.user_id == uuid.UUID(me["user"]["id"]), Staff.role == "owner")
                )
                == 0
            )
            staff = await db.scalar(
                select(Staff).where(
                    Staff.tenant_id == uuid.UUID(workspace["id"]), Staff.user_id == uuid.UUID(me["user"]["id"])
                )
            )
            staff_id = str(staff.id)
            from clinic_db.models.ops import AuditLog

            accepted_audit = await db.scalar(
                select(AuditLog).where(AuditLog.tenant_id == staff.tenant_id, AuditLog.action == "invitation.accepted")
            )
            assert accepted_audit.actor_type == "staff" and accepted_audit.actor_id == staff_id
        assert (
            await owner.post(base + "/members/" + staff_id, headers=csrf, json={"role": "consultant"})
        ).status_code == 200
        assert (await user.get("/features/voice_receptionist/inbound/calls")).status_code == feature_denied_status(
            "voice_receptionist"
        )
        assert (
            await owner.post(base + "/members/" + staff_id, headers=csrf, json={"deactivate": True})
        ).status_code == 200
        assert (await user.post("/api/v1/invitations/accept", headers=user_csrf, json={})).status_code == 403


async def test_invitation_wrong_email_resend_revoke_and_expiry(system):
    from clinic_db.models.membership import Invitation

    app, owner, csrf, workspace = await invitation_setup(system)
    base = "/api/v1/workspaces/" + workspace["id"]
    created = await owner.post(
        base + "/invitations", headers=csrf, json={"email": "intended@example.com", "role": "provider"}
    )
    ident = created.json()["id"]
    token = await invitation_link(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as wrong:
        await wrong.post(
            "/api/v1/invitations/context", headers={"Origin": "http://localhost:3000"}, json={"token": token}
        )
        await login(wrong, "wrong" + uuid.uuid4().hex)
        assert (await wrong.get("/api/v1/invitations/current")).status_code == 403
        assert (
            await wrong.post("/api/v1/invitations/accept", headers=await headers(wrong), json={})
        ).status_code == 403
    assert (await owner.post(base + "/invitations/" + ident + "/resend", headers=csrf)).status_code == 429
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.get(Invitation, uuid.UUID(ident))
        row.last_sent_at = now() - timedelta(minutes=2)
    assert (await owner.post(base + "/invitations/" + ident + "/resend", headers=csrf)).status_code == 200
    assert (await owner.post("/api/v1/invitations/context", headers=csrf, json={"token": token})).status_code == 410
    fresh = await invitation_link(app)
    assert fresh != token
    assert (await owner.post(base + "/invitations/" + ident + "/revoke", headers=csrf)).status_code == 200
    assert (await owner.get(base + "/invitations")).json()["invitations"] == []
    assert (await owner.post("/api/v1/invitations/context", headers=csrf, json={"token": fresh})).status_code == 410

    expired = await owner.post(
        base + "/invitations", headers=csrf, json={"email": "expired@example.com", "role": "provider"}
    )
    expired_token = await invitation_link(app)
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.get(Invitation, uuid.UUID(expired.json()["id"]))
        row.expires_at = now() - timedelta(seconds=1)
    assert (await owner.get(base + "/invitations")).json()["invitations"] == []
    assert (
        await owner.post("/api/v1/invitations/context", headers=csrf, json={"token": expired_token})
    ).status_code == 410


async def test_email_transport_template_and_retry(system):
    from pydantic import SecretStr

    from clinic_engagement.email import send_email
    from clinic_engagement.email.service import EmailFailure
    from clinic_engagement.email.template import invitation

    app, _, _, _ = await invitation_setup(system)
    settings = app.state.settings
    settings.email_provider, settings.sendgrid_api_key = "sendgrid", SecretStr("test-never-sent")
    settings.email_from_address = "sender@example.com"
    content = invitation(
        workspace='<script>alert("x")</script>',
        inviter="Owner",
        role="provider",
        email="user@example.com",
        url="https://example.com/invite#token=abc",
        hours=72,
    )
    assert "<script>" not in content.html
    assert "&lt;script&gt;" in content.html

    def transport(request):
        import json

        body = json.loads(request.content)
        assert request.url.host == "api.sendgrid.com"
        assert body["tracking_settings"]["click_tracking"]["enable"] is False
        return httpx.Response(202, headers={"X-Message-Id": "test-id"})

    assert (
        await send_email(
            to="user@example.com", template=content, settings=settings, transport=httpx.MockTransport(transport)
        )
        == "test-id"
    )
    with pytest.raises(EmailFailure):
        await send_email(
            to="user@example.com",
            template=content,
            settings=settings,
            transport=httpx.MockTransport(lambda _: httpx.Response(403)),
        )


async def test_invitation_existing_user_selects_target_workspace_and_requires_mailbox_proof(system):
    from clinic_db.models.auth import AuthSession
    from clinic_engagement.email.service import deliver_due

    app, owner, csrf, workspace = await invitation_setup(system)
    recipient = "existing" + uuid.uuid4().hex
    base = "/api/v1/workspaces/" + workspace["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as user:
        await login(user, recipient)
        user_headers = await headers(user)
        previous = (
            await user.post(
                "/api/v1/workspaces", headers=user_headers, json={"name": "Original workspace", "timezone": "UTC"}
            )
        ).json()
        assert (
            await owner.post(
                base + "/invitations", headers=csrf, json={"email": recipient + "@example.com", "role": "provider"}
            )
        ).status_code == 201
        token = await invitation_link(app)
        await user.post("/api/v1/invitations/context", headers=user_headers, json={"token": token})
        # Non-authoritative Google email claims require a second, current mailbox proof.
        async with app.state.session_factory() as db:
            session = await db.scalar(
                select(AuthSession).where(AuthSession.token_hash == digest(user.cookies.get("avishkar_session")))
            )
            session.mailbox_authoritative = False
            await db.commit()
        assert (await user.post("/api/v1/invitations/accept", headers=user_headers, json={})).status_code == 403
        assert (await user.post("/api/v1/invitations/verification", headers=user_headers, json={})).status_code == 200
        messages = []

        async def capture(**kw):
            messages.append(kw)
            return "verified-captured"

        await deliver_due(app.state.settings, sender=capture)
        import re

        code = re.search(r"\b\d{6}\b", messages[-1]["template"].text).group(0)
        assert (
            await user.post(
                "/api/v1/invitations/accept",
                headers=user_headers,
                json={"verification_code": "000000" if code != "000000" else "111111"},
            )
        ).status_code == 403
        accepted = await user.post("/api/v1/invitations/accept", headers=user_headers, json={"verification_code": code})
        assert accepted.status_code == 200, accepted.text
        me = (await user.get("/api/v1/auth/me")).json()
        assert len(me["memberships"]) == 2
        assert me["workspace"]["id"] == workspace["id"]
        # Provider does not inherit owner rights from the user's other workspace.
        assert (await user.get(base + "/members")).status_code == 403
        assert (await user.get("/features/voice_receptionist/inbound/calls")).status_code == feature_denied_status(
            "voice_receptionist"
        )
        assert (
            await user.post("/api/v1/auth/workspace", headers=user_headers, json={"workspace_id": str(uuid.uuid4())})
        ).status_code == 403
        assert (
            await user.post("/api/v1/auth/workspace", headers=user_headers, json={"workspace_id": previous["id"]})
        ).status_code == 200
        assert (await user.get("/api/v1/auth/me")).json()["workspace"]["id"] == previous["id"]
        assert (await user.get("/api/v1/workspaces/" + previous["id"] + "/members")).status_code == 200


async def test_email_retry_is_durable_and_revocation_stops_queued_delivery(system):
    from clinic_db.models.membership import EmailDelivery
    from clinic_engagement.email.service import EmailFailure, deliver_due

    app, owner, csrf, workspace = await invitation_setup(system)
    result = await owner.post(
        "/api/v1/workspaces/" + workspace["id"] + "/invitations",
        headers=csrf,
        json={"email": "retry@example.com", "role": "front_desk"},
    )
    invite_id = uuid.UUID(result.json()["id"])

    async def unavailable(**kw):
        raise EmailFailure(429, "600")

    await deliver_due(app.state.settings, sender=unavailable)
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.scalar(select(EmailDelivery).where(EmailDelivery.invitation_id == invite_id))
        assert row.status == "retry" and row.payload and row.error == "provider_429"
        assert row.next_attempt_at >= now() + timedelta(seconds=590)
        row.next_attempt_at = now() - timedelta(seconds=1)
    assert (
        await owner.post(f"/api/v1/workspaces/{workspace['id']}/invitations/{invite_id}/revoke", headers=csrf)
    ).status_code == 200

    async def never_send(**kw):
        pytest.fail("Revoked invitations must not be dispatched")

    await deliver_due(app.state.settings, sender=never_send)
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.scalar(select(EmailDelivery).where(EmailDelivery.invitation_id == invite_id))
        assert row.status == "cancelled" and row.payload is None


async def test_invitation_sends_immediately_after_commit_and_preserves_retry(system, monkeypatch):
    from clinic_db.models.membership import EmailDelivery, Invitation
    from clinic_engagement.email import service

    app, owner, csrf, workspace = await invitation_setup(system)
    base = f"/api/v1/workspaces/{workspace['id']}/invitations"
    # Existing backlog must not delay or get dispatched by this request.
    backlog = await owner.post(base, headers=csrf, json={"email": "backlog@example.com", "role": "provider"})
    assert backlog.status_code == 201
    calls = []
    fail = False

    async def provider(*, to, template, settings):
        async with system_session(database_url=settings.database_system_url) as db:
            invite = await db.scalar(
                select(Invitation).where(Invitation.tenant_id == uuid.UUID(workspace["id"]), Invitation.email == to)
            )
            assert invite is not None  # Visible from another connection: enqueue transaction already committed.
        calls.append(to)
        if fail:
            raise service.EmailFailure(429, "600")
        return "immediate-provider-id"

    monkeypatch.setattr(service, "send_email", provider)
    app.state.settings.email_provider = "sendgrid"
    created = await owner.post(base, headers=csrf, json={"email": "immediate@example.com", "role": "front_desk"})
    assert created.status_code == 201, created.text
    ident = uuid.UUID(created.json()["id"])
    assert calls == ["immediate@example.com"]  # No worker/scheduler/captured-dispatch call.
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        delivered = await db.scalar(select(EmailDelivery).where(EmailDelivery.invitation_id == ident))
        assert delivered.status == "accepted" and delivered.attempts == 1 and delivered.payload is None
        old = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.invitation_id == uuid.UUID(backlog.json()["id"]))
        )
        assert old.status == "queued" and old.attempts == 0
        invite = await db.get(Invitation, ident)
        invite.last_sent_at = now() - timedelta(minutes=2)
    fail = True
    resent = await owner.post(f"{base}/{ident}/resend", headers=csrf)
    assert resent.status_code == 200  # Transient provider errors do not undo the valid invitation.
    assert calls == ["immediate@example.com", "immediate@example.com"]
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        retry = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.invitation_id == ident, EmailDelivery.generation == 2)
        )
        assert retry.status == "retry" and retry.payload and retry.error == "provider_429"
        assert retry.next_attempt_at >= now() + timedelta(seconds=590)
        retry.next_attempt_at = now() - timedelta(seconds=1)
        delivery_id = retry.id
    fail = False
    # Concurrent API/worker wakeups must respect the same lease and submit only once.
    await asyncio.gather(*(service.deliver_email(delivery_id, app.state.settings) for _ in range(2)))
    assert calls == ["immediate@example.com"] * 3
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        retry = await db.get(EmailDelivery, delivery_id)
        assert retry.status == "accepted" and retry.attempts == 2


async def test_office_manager_grants_are_scoped_and_demotion_revokes_pending_invites(system):
    from clinic_core.database import tenant_session
    from clinic_db.models.core import Staff, Tenant
    from clinic_db.models.membership import EmailDelivery, Invitation

    app, owner, csrf, workspace = await invitation_setup(system)
    base = f"/api/v1/workspaces/{workspace['id']}"
    manager_subject = "manager" + uuid.uuid4().hex
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as manager:
        await login(manager, manager_subject)
        identity = (await manager.get("/api/v1/auth/me")).json()
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            member = Staff(
                tenant_id=uuid.UUID(workspace["id"]),
                user_id=uuid.UUID(identity["user"]["id"]),
                email=manager_subject + "@example.com",
                name="Office manager",
                role="office_manager",
                active=True,
            )
            db.add(member)
            foreign = Tenant(name="Foreign workspace", timezone="UTC", clinic_type="wellness")
            db.add(foreign)
            await db.flush()
            manager_id, foreign_id = member.id, foreign.id
            owner_member = await db.scalar(
                select(Staff).where(Staff.tenant_id == uuid.UUID(workspace["id"]), Staff.role == "owner")
            )
            owner_id = owner_member.id
        manager_csrf = await headers(manager)
        assert (await manager.get(base + "/members")).status_code == 200
        for role in ("owner", "office_manager"):
            assert (
                await manager.post(
                    base + "/invitations", headers=manager_csrf, json={"email": "forbidden@example.com", "role": role}
                )
            ).status_code == 403
        for target in (owner_id, manager_id):
            assert (
                await manager.post(f"{base}/members/{target}", headers=manager_csrf, json={"deactivate": True})
            ).status_code == 403
        foreign_base = f"/api/v1/workspaces/{foreign_id}"
        assert (await manager.get(foreign_base + "/members")).status_code == 403
        assert (
            await manager.post(
                foreign_base + "/invitations",
                headers=manager_csrf,
                json={"email": "other@example.com", "role": "front_desk"},
            )
        ).status_code == 403
        created = await manager.post(
            base + "/invitations", headers=manager_csrf, json={"email": "allowed@example.com", "role": "front_desk"}
        )
        assert created.status_code == 201, created.text
        invitation_id = uuid.UUID(created.json()["id"])
        # Runtime-role RLS hides both the invitation and its encrypted email from a different tenant.
        async with tenant_session(foreign_id, database_url=app.state.settings.database_url) as db:
            assert await db.get(Invitation, invitation_id) is None
            assert await db.scalar(select(EmailDelivery).where(EmailDelivery.invitation_id == invitation_id)) is None
        assert (
            await owner.post(f"{base}/members/{manager_id}", headers=csrf, json={"role": "front_desk"})
        ).status_code == 200
        assert (await manager.get(base + "/members")).status_code == 403
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            invite = await db.get(Invitation, invitation_id)
            delivery = await db.scalar(select(EmailDelivery).where(EmailDelivery.invitation_id == invitation_id))
            assert invite.status == "revoked"
            assert delivery.status == "cancelled" and delivery.payload is None
            from clinic_db.models.ops import AuditLog

            audit = await db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == uuid.UUID(workspace["id"]), AuditLog.action == "member.role_changed"
                )
            )
            assert audit.entity_type == "staff" and audit.entity_id == manager_id


async def test_reinvite_restores_original_membership_only_after_fresh_acceptance(system):
    from sqlalchemy import func

    from clinic_db.models.core import Staff
    from clinic_db.models.membership import Invitation
    from clinic_db.models.ops import AuditLog

    app, owner, csrf, workspace = await invitation_setup(system)
    subject = "returning" + uuid.uuid4().hex
    base = f"/api/v1/workspaces/{workspace['id']}"
    invitation_data = {"email": subject + "@example.com", "role": "office_manager"}
    assert (await owner.post(base + "/invitations", headers=csrf, json=invitation_data)).status_code == 201
    original_token = await invitation_link(app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as user:
        await user.post("/api/v1/invitations/context", headers=csrf, json={"token": original_token})
        await login(user, subject)
        user_csrf = await headers(user)
        old_context = user.cookies.get("avishkar_invitation")
        assert (await user.post("/api/v1/invitations/accept", headers=user_csrf, json={})).status_code == 200
        identity = (await user.get("/api/v1/auth/me")).json()
        member = next(m for m in (await owner.get(base + "/members")).json() if m["user_id"] == identity["user"]["id"])
        member_id = member["id"]
        # A legacy outstanding grant must also be invalidated when access is removed.
        stale_token = uuid.uuid4().hex + uuid.uuid4().hex
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            inviter = await db.scalar(
                select(Staff).where(Staff.tenant_id == uuid.UUID(workspace["id"]), Staff.role == "owner")
            )
            db.add(
                Invitation(
                    tenant_id=inviter.tenant_id,
                    email=invitation_data["email"],
                    role="front_desk",
                    invited_by=inviter.id,
                    token_hash=digest(stale_token),
                    generation=1,
                    status="pending",
                    expires_at=now() + timedelta(hours=1),
                    last_sent_at=now(),
                )
            )
        assert (
            await owner.post(base + "/members/" + member_id, headers=csrf, json={"deactivate": True})
        ).status_code == 200
        assert (await user.get("/me")).status_code == 403
        assert (
            await user.post("/api/v1/invitations/context", headers=user_csrf, json={"token": stale_token})
        ).status_code == 410
        reinvite = {**invitation_data, "role": "front_desk"}
        assert (await owner.post(base + "/invitations", headers=csrf, json=reinvite)).status_code == 201
        assert (await owner.post(base + "/invitations", headers=csrf, json=reinvite)).status_code == 409
        fresh_token = await invitation_link(app)
        assert fresh_token != original_token
        # Issuing the new invitation does not reactivate membership or make old accepts usable.
        user.cookies.set("avishkar_invitation", old_context, domain="localhost.local", path="/")
        assert (await user.post("/api/v1/invitations/accept", headers=user_csrf, json={})).status_code == 403
        assert (await user.get("/me")).status_code == 403

        class ReassignedGoogle(InvitationGoogle):
            async def identity(self, code, nonce, verifier):
                claims = await super().identity(code, nonce, verifier)
                if code == "reassigned":
                    claims["email"] = invitation_data["email"]
                return claims

        app.state.google = ReassignedGoogle()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
        ) as other:
            await other.post("/api/v1/invitations/context", headers=csrf, json={"token": fresh_token})
            await login(other, "reassigned")
            assert (
                await other.post("/api/v1/invitations/accept", headers=await headers(other), json={})
            ).status_code == 409
            assert (await other.get("/me")).status_code == 403
        await user.post("/api/v1/invitations/context", headers=user_csrf, json={"token": fresh_token})
        requests = [
            user.build_request("POST", "/api/v1/invitations/accept", headers=user_csrf, json={}) for _ in range(2)
        ]
        accepted = await asyncio.gather(*(user.send(request) for request in requests))
        assert [r.status_code for r in accepted] == [200, 200], [r.text for r in accepted]
        restored = (await user.get("/api/v1/auth/me")).json()
        assert restored["workspace"]["id"] == workspace["id"]
        assert restored["memberships"][0]["role"] == "front_desk"
        assert len(restored["memberships"]) == 1
        assert (await user.get(base + "/members")).status_code == 403  # Old manager rights were not restored.
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            rows = (
                await db.scalars(
                    select(Staff).where(
                        Staff.tenant_id == uuid.UUID(workspace["id"]),
                        Staff.user_id == uuid.UUID(identity["user"]["id"]),
                    )
                )
            ).all()
            assert len(rows) == 1 and str(rows[0].id) == member_id and rows[0].active
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.tenant_id == uuid.UUID(workspace["id"]), AuditLog.action == "member.restored")
                )
                == 1
            )


async def test_office_manager_cannot_reinvite_removed_manager_as_lower_role(system):
    from clinic_db.models.core import Staff

    app, owner, csrf, workspace = await invitation_setup(system)
    base = f"/api/v1/workspaces/{workspace['id']}"
    subject = "manager" + uuid.uuid4().hex
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(uuid.uuid4().hex, 123)), base_url="http://localhost:3000"
    ) as manager:
        await login(manager, subject)
        identity = (await manager.get("/api/v1/auth/me")).json()
        async with app.state.session_factory() as auth_db:
            removed_user = User(email="removed-manager@example.com", display_name="Removed manager")
            auth_db.add(removed_user)
            await auth_db.flush()
            removed_user_id = removed_user.id
            await auth_db.commit()
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            db.add(
                Staff(
                    tenant_id=uuid.UUID(workspace["id"]),
                    user_id=uuid.UUID(identity["user"]["id"]),
                    email=subject + "@example.com",
                    name="Active manager",
                    role="office_manager",
                    active=True,
                )
            )
            db.add(
                Staff(
                    tenant_id=uuid.UUID(workspace["id"]),
                    user_id=removed_user_id,
                    email="removed-manager@example.com",
                    name="Removed manager",
                    role="office_manager",
                    active=False,
                )
            )
        assert (
            await manager.post(
                base + "/invitations",
                headers=await headers(manager),
                json={"email": "removed-manager@example.com", "role": "front_desk"},
            )
        ).status_code == 403


async def test_audit_history_filters_pagination_export_and_permissions(system):
    import csv
    import io
    from datetime import UTC, datetime

    from clinic_db.models.core import Staff, Tenant
    from clinic_db.models.ops import AuditLog

    app, client = system
    await login(client)
    workspace = (
        await client.post(
            "/api/v1/workspaces",
            headers=await headers(client),
            json={"name": "Audit clinic", "timezone": "Asia/Kolkata"},
        )
    ).json()
    wid = uuid.UUID(workspace["id"])
    path = f"/api/v1/workspaces/{wid}/audit"
    instant = datetime(2026, 10, 22, 18, 30, tzinfo=UTC)  # Oct 23 midnight in clinic timezone
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        member = await db.scalar(select(Staff).where(Staff.tenant_id == wid))
        member.name = '=HYPERLINK("evil")'
        actor_id = str(member.id)
        foreign_id = uuid.uuid4()
        db.add(Tenant(id=foreign_id, name="Other clinic", timezone="UTC", clinic_type="wellness"))
        await db.flush()
        for _ in range(555):
            db.add(
                AuditLog(
                    tenant_id=wid,
                    actor_type="staff",
                    actor_id=actor_id,
                    action="member.role_changed",
                    occurred_at=instant,
                )
            )
        db.add(
            AuditLog(
                tenant_id=wid, actor_type="system", action="workspace.updated", occurred_at=instant + timedelta(days=1)
            )
        )
        db.add(AuditLog(tenant_id=foreign_id, actor_type="system", action="foreign.secret", occurred_at=instant))
    result = await client.get(path)
    assert result.status_code == 200, result.text
    first = result.json()
    assert first["total"] == 556 and first["page_size"] == 50 and len(first["items"]) == 50
    second = (await client.get(path, params={"before": first["next_cursor"]})).json()
    assert not ({x["id"] for x in first["items"]} & {x["id"] for x in second["items"]})
    last = second
    while last["next_cursor"]:
        last = (await client.get(path, params={"before": last["next_cursor"]})).json()
    assert len(last["items"]) == 6
    query = {
        "start_date": "2026-10-23",
        "end_date": "2026-10-23",
        "actor": f"staff:{actor_id}",
        "action": "member.role_changed",
    }
    filtered = (await client.get(path, params=query)).json()
    assert filtered["total"] == 555
    assert (await client.get(path, params={"end_date": "2026-10-22"})).json()["total"] == 0
    assert (await client.get(path, params={"start_date": "2026-10-24"})).json()["total"] == 1
    assert (await client.get(path, params={"action": "foreign.secret"})).json()["total"] == 0
    opts = (await client.get(path + "/options")).json()
    assert "foreign.secret" not in opts["events"]
    assert {"value": f"staff:{actor_id}", "label": '=HYPERLINK("evil")'} in opts["actors"]
    download = await client.get(path + "/export", params=query)
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert "no-store" in download.headers["cache-control"]
    records = list(csv.DictReader(io.StringIO(download.text.lstrip("\ufeff"))))
    assert len(records) == 555 and len({row["ID"] for row in records}) == 555
    assert all(row["Actor"].startswith("'=") for row in records)
    assert len(list(csv.DictReader(io.StringIO((await client.get(path + "/export")).text.lstrip("\ufeff"))))) == 556
    for suffix in ("", "/export"):
        assert (
            await client.get(path + suffix, params={"start_date": "2026-10-24", "end_date": "2026-10-23"})
        ).status_code == 422
        assert (await client.get(path + suffix, params={"actor": "invalid"})).status_code == 422
        assert (await client.get(path + suffix, params={"end_date": "9999-12-31"})).status_code == 422
    assert (await client.get(path, params={"before": 0})).status_code == 422
    for suffix in ("", "/options", "/export"):
        assert (await client.get(f"/api/v1/workspaces/{foreign_id}/audit" + suffix)).status_code == 403
    for role in ("office_manager", "front_desk", "provider", "consultant"):
        async with system_session(database_url=app.state.settings.database_system_url) as db:
            member = await db.scalar(select(Staff).where(Staff.tenant_id == wid))
            member.role = role
        for suffix in ("", "/options", "/export"):
            response = await client.get(path + suffix)
            assert response.status_code == (200 if role == "office_manager" else 403)


async def test_audit_resolves_legacy_account_ids_only_within_workspace(system):
    import csv
    import io

    from clinic_db.models.core import Staff, Tenant
    from clinic_db.models.ops import AuditLog

    app, client = system
    await login(client)
    workspace = (
        await client.post(
            "/api/v1/workspaces", headers=await headers(client), json={"name": "Legacy audit", "timezone": "UTC"}
        )
    ).json()
    wid = uuid.UUID(workspace["id"])
    foreign_user = uuid.uuid4()
    async with app.state.session_factory() as auth_db:
        auth_db.add(User(id=foreign_user, email="foreign-actor@example.com", display_name="Private foreign name"))
        await auth_db.commit()
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        member = await db.scalar(select(Staff).where(Staff.tenant_id == wid))
        account_id, member_id, name = str(member.user_id), str(member.id), member.name
        foreign_tenant = Tenant(name="Other workspace", timezone="UTC", clinic_type="wellness")
        db.add(foreign_tenant)
        await db.flush()
        db.add(
            Staff(
                tenant_id=foreign_tenant.id,
                user_id=foreign_user,
                name="Private foreign name",
                email="foreign-actor@example.com",
                role="front_desk",
                active=True,
            )
        )
        for ident in (account_id, member_id, str(foreign_user)):
            db.add(AuditLog(tenant_id=wid, actor_type="staff", actor_id=ident, action="invitation.accepted"))
    path = f"/api/v1/workspaces/{wid}/audit"
    rows = (await client.get(path)).json()["items"]
    assert [row["actor"] for row in rows].count(name) == 2
    assert [row["actor"] for row in rows].count("Unknown member") == 1
    options = (await client.get(path + "/options")).json()["actors"]
    assert {"value": f"staff:{account_id}", "label": name} in options
    assert {"value": f"staff:{member_id}", "label": name} in options
    filtered = (await client.get(path, params={"actor": f"staff:{account_id}"})).json()
    assert filtered["total"] == 1 and filtered["items"][0]["actor"] == name
    download = await client.get(path + "/export")
    records = list(csv.DictReader(io.StringIO(download.text.lstrip("\ufeff"))))
    assert {row["Actor ID"]: row["Actor"] for row in records} == {
        account_id: name,
        member_id: name,
        str(foreign_user): "Unknown member",
    }


async def test_every_workspace_management_endpoint_rejects_foreign_ids(system):
    from clinic_core.tenancy.invitations import create_invitation
    from clinic_db.models.core import Staff, Tenant
    from clinic_db.models.membership import Invitation

    app, client, csrf, workspace = await invitation_setup(system)
    own = f"/api/v1/workspaces/{workspace['id']}"
    own_invite = (
        await client.post(own + "/invitations", headers=csrf, json={"email": "own@test.example", "role": "front_desk"})
    ).json()["id"]
    async with app.state.session_factory() as auth_db:
        stranger = User(email="stranger@test.example", display_name="Stranger")
        auth_db.add(stranger)
        await auth_db.commit()
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        tenant = Tenant(name="Foreign workspace", timezone="UTC", clinic_type="wellness")
        db.add(tenant)
        await db.flush()
        member = Staff(
            tenant_id=tenant.id,
            user_id=stranger.id,
            name="Foreign Owner",
            email=stranger.email,
            role="owner",
            active=True,
        )
        db.add(member)
        await db.flush()
        invite, _ = await create_invitation(
            db, tenant, member, email="foreign@test.example", role="front_desk", settings=app.state.settings
        )
        foreign_id, member_id, invitation_id = tenant.id, member.id, invite.id
    foreign = f"/api/v1/workspaces/{foreign_id}"
    for suffix in ("settings", "members", "audit", "audit/options", "audit/export", "invitations"):
        assert (await client.get(foreign + "/" + suffix)).status_code == 403
    assert (
        await client.post(
            foreign + "/settings",
            headers=csrf,
            json={"name": "hacked", "timezone": "UTC", "clinic_type": "wellness", "address": "", "phone": None},
        )
    ).status_code == 403
    assert (
        await client.post(
            foreign + "/invitations", headers=csrf, json={"email": "hacked@test.example", "role": "front_desk"}
        )
    ).status_code == 403
    for action in ("resend", "revoke"):
        assert (await client.post(f"{own}/invitations/{invitation_id}/{action}", headers=csrf)).status_code == 404
        assert (await client.post(f"{foreign}/invitations/{own_invite}/{action}", headers=csrf)).status_code == 403
    for body in ({"role": "front_desk"}, {"deactivate": True}):
        assert (await client.post(f"{own}/members/{member_id}", headers=csrf, json=body)).status_code == 404
        assert (await client.post(f"{foreign}/members/{member_id}", headers=csrf, json=body)).status_code == 403
    assert (await client.get(own + "/audit", params={"action": "invitation.created"})).json()["total"] == 1
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        assert (await db.get(Tenant, foreign_id)).name == "Foreign workspace"
        assert (await db.get(Staff, member_id)).active
        assert (await db.get(Invitation, invitation_id)).status == "pending"


async def test_invitation_delivery_statuses_are_fetched_in_one_query(system):
    from sqlalchemy import event

    from clinic_core.database import _system_engine

    app, client, csrf, workspace = await invitation_setup(system)
    path = f"/api/v1/workspaces/{workspace['id']}/invitations"
    for index in range(5):
        assert (
            await client.post(path, headers=csrf, json={"email": f"batch{index}@test.example", "role": "front_desk"})
        ).status_code == 201
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "ops.email_deliveries" in statement and statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    engine = _system_engine(app.state.settings.database_system_url).sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.status_code == 200
    assert len(result.json()["invitations"]) == 5
    assert {row["delivery_status"] for row in result.json()["invitations"]} == {"queued"}
    assert len(queries) == 1


async def test_immediate_email_timeout_is_five_seconds_and_queue_recovers(system, monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from clinic_db.models.membership import EmailDelivery
    from clinic_engagement.email import service

    app, client, csrf, workspace = await invitation_setup(system)
    app.state.settings.email_provider = "sendgrid"
    app.state.settings.sendgrid_api_key = SecretStr("fake-test-key")
    app.state.settings.email_from_address = "sender@test.example"
    app.state.settings.email_payload_encryption_key = SecretStr(Fernet.generate_key().decode())
    budgets = []
    real_timeout = asyncio.timeout

    def bounded(seconds):
        budgets.append(seconds)
        return real_timeout(0.05)  # Exercise cancellation without waiting five seconds.

    async def slow_provider(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(service.asyncio, "timeout", bounded)
    monkeypatch.setattr(service, "send_email", slow_provider)
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/invitations",
        headers=csrf,
        json={"email": "slow@test.example", "role": "front_desk"},
    )
    assert response.status_code == 201
    assert budgets == [5]
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        delivery = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.invitation_id == uuid.UUID(response.json()["id"]))
        )
        assert delivery.status == "sending" and delivery.payload
        delivery.next_attempt_at = now() - timedelta(seconds=1)
        ident = delivery.id

    async def captured(**kwargs):
        return "recovered-after-timeout"

    assert await service.deliver_due(app.state.settings, sender=captured, delivery_id=ident, limit=1) == 1
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        delivery = await db.get(EmailDelivery, ident)
        assert delivery.status == "accepted" and delivery.payload is None


def cloud_email_config(settings):
    from pydantic import SecretStr

    settings.email_provider = "sendgrid"
    settings.sendgrid_api_key = SecretStr("fake-cloud-task-test-key")
    settings.email_from_address = "sender@example.com"
    settings.email_tasks_project = "test-project"
    settings.email_tasks_region = "us-east1"
    settings.email_tasks_queue = "test-email"
    settings.email_tasks_url = "https://email.example.com"
    settings.email_tasks_audience = "https://email.example.com"
    settings.email_tasks_invoker_email = "tasks@test-project.iam.gserviceaccount.com"


async def test_invitation_queues_after_commit_worker_sends_once_and_revocation_cancels(system, monkeypatch):
    from unittest.mock import AsyncMock

    from google.oauth2 import id_token

    from clinic_core.settings import EmailWorkerSettings
    from clinic_db.models.membership import EmailDelivery
    from clinic_engagement.email import service, tasks
    from clinic_engagement.email.task_app import create_app as worker_app

    app, client, csrf, workspace = await invitation_setup(system)
    cloud_email_config(app.state.settings)
    scheduled = []
    monkeypatch.setattr(tasks, "_create_task", lambda cfg, ident, generation: scheduled.append((ident, generation)))
    sender = AsyncMock(return_value="accepted-in-worker")
    monkeypatch.setattr(service, "send_email", sender)
    monkeypatch.setattr(
        id_token,
        "verify_oauth2_token",
        lambda *a, **k: {"email": app.state.settings.email_tasks_invoker_email, "email_verified": True},
    )
    path = f"/api/v1/workspaces/{workspace['id']}/invitations"
    response = await client.post(path, headers=csrf, json={"email": "queued@example.com", "role": "front_desk"})
    assert response.status_code == 201
    assert len(scheduled) == 1 and scheduled[0][1] == 1
    sender.assert_not_awaited()  # API request never contacts SendGrid when tasks are configured.
    delivery_id = scheduled[0][0]
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.get(EmailDelivery, delivery_id)
        assert row.status == "queued" and row.payload and row.task_dispatch_at is not None
    cfg = EmailWorkerSettings(**app.state.settings.model_dump())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=worker_app(cfg)), base_url=cfg.email_tasks_url
    ) as worker:
        body, auth = {"delivery_id": str(delivery_id)}, {"Authorization": "Bearer signed-test"}
        first = await worker.post("/tasks/email/send", json=body, headers=auth)
        assert first.status_code == 200 and first.json()["status"] == "accepted"
        assert (await worker.post("/tasks/email/send", json=body, headers=auth)).status_code == 200
        sender.assert_awaited_once()
        second = await client.post(
            path, headers=csrf, json={"email": "revoked-queued@example.com", "role": "front_desk"}
        )
        assert second.status_code == 201
        assert (await client.post(f"{path}/{second.json()['id']}/revoke", headers=csrf)).status_code == 200
        cancelled = await worker.post("/tasks/email/send", json={"delivery_id": str(scheduled[-1][0])}, headers=auth)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        sender.assert_awaited_once()
        assert (await worker.post("/tasks/email/send", json={"delivery_id": str(uuid.uuid4())}, headers=auth)).json()[
            "status"
        ] == "missing"


async def test_task_enqueue_failure_concurrent_dispatch_and_lost_task_recovery(system, monkeypatch):
    from clinic_db.models.membership import EmailDelivery
    from clinic_engagement.email import tasks

    app, client, csrf, workspace = await invitation_setup(system)
    cloud_email_config(app.state.settings)

    def unavailable(*args):
        raise RuntimeError("simulated Cloud Tasks outage")

    monkeypatch.setattr(tasks, "_create_task", unavailable)
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/invitations",
        headers=csrf,
        json={"email": "recover-task@example.com", "role": "front_desk"},
    )
    assert response.status_code == 201  # Committed invitation survives enqueue failure.
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.invitation_id == uuid.UUID(response.json()["id"]))
        )
        ident = row.id
        assert row.task_dispatch_at is None and row.payload and row.status == "queued" and row.task_generation == 1
    scheduled = []
    monkeypatch.setattr(tasks, "_create_task", lambda cfg, ident, generation: scheduled.append((ident, generation)))
    assert sorted(
        await asyncio.gather(tasks.publish(ident, app.state.settings), tasks.publish(ident, app.state.settings))
    ) == [0, 1]
    assert scheduled == [(ident, 2)]
    async with system_session(database_url=app.state.settings.database_system_url) as db:
        row = await db.get(EmailDelivery, ident)
        row.task_dispatch_at = now() - tasks.DISPATCH_LEASE - timedelta(seconds=1)
        row.next_attempt_at = now() - timedelta(days=3650)  # First due record, independent of other test fixtures.
    assert await tasks.dispatch_due(app.state.settings, limit=1) == 1
    assert scheduled[-1] == (ident, 3)  # New task name rescues an exhausted/lost prior task.


async def test_email_http_worker_retries_transient_provider_errors_and_acknowledges_terminal_failure(
    system, monkeypatch
):
    from unittest.mock import AsyncMock

    from google.oauth2 import id_token

    from clinic_core.settings import EmailWorkerSettings
    from clinic_db.models.membership import EmailDelivery
    from clinic_engagement.email import service, tasks
    from clinic_engagement.email.sendgrid import EmailFailure
    from clinic_engagement.email.task_app import create_app as worker_app

    app, client, csrf, workspace = await invitation_setup(system)
    cloud_email_config(app.state.settings)
    scheduled = []
    monkeypatch.setattr(tasks, "_create_task", lambda cfg, ident, generation: scheduled.append(ident))
    monkeypatch.setattr(
        id_token,
        "verify_oauth2_token",
        lambda *a, **k: {"email": app.state.settings.email_tasks_invoker_email, "email_verified": True},
    )
    response = await client.post(
        f"/api/v1/workspaces/{workspace['id']}/invitations",
        headers=csrf,
        json={"email": "worker-retry@example.com", "role": "front_desk"},
    )
    assert response.status_code == 201
    sender = AsyncMock(side_effect=[EmailFailure(429, "300"), "accepted-after-retry"])
    monkeypatch.setattr(service, "send_email", sender)
    cfg = EmailWorkerSettings(**app.state.settings.model_dump())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=worker_app(cfg)), base_url=cfg.email_tasks_url
    ) as worker:
        body, auth = {"delivery_id": str(scheduled[0])}, {"Authorization": "Bearer signed-test"}
        result = await worker.post("/tasks/email/send", json=body, headers=auth)
        assert result.status_code == 503 and int(result.headers["Retry-After"]) > 0
        assert (await worker.post("/tasks/email/send", json=body, headers=auth)).status_code == 503
        sender.assert_awaited_once()  # Backoff/active lease cannot be bypassed by duplicate tasks.
        async with system_session(database_url=cfg.database_system_url) as db:
            row = await db.get(EmailDelivery, scheduled[0])
            assert row.status == "retry" and row.payload
            row.next_attempt_at = now() - timedelta(seconds=1)
        assert (await worker.post("/tasks/email/send", json=body, headers=auth)).json()["status"] == "accepted"
        assert sender.await_count == 2
        async with system_session(database_url=cfg.database_system_url) as db:
            row = await db.get(EmailDelivery, scheduled[0])
            assert row.payload is None
            row.status = "failed"
        assert (await worker.post("/tasks/email/send", json=body, headers=auth)).json()["status"] == "failed"
        assert sender.await_count == 2
