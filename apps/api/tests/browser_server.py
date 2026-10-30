"""Browser-test entry point only. Never deploy this simulated identity provider."""

import os
import uuid
from urllib.parse import urlencode

from fastapi import Request, Response

from clinic_api.main import create_app
from clinic_core.settings import Settings

try:  # Only present when the voice feature is installed. Removing a feature must not break platform tests.
    from clinic_voice_receptionist.testing import (
        FakeNumbers,
        MemoryRecordingStore,
        ScriptedConnector,
        scripted_voice_preview,
    )
except ModuleNotFoundError as exc:
    if exc.name != "clinic_voice_receptionist":
        raise  # a real import problem inside voice, not its absence
    ScriptedConnector = MemoryRecordingStore = FakeNumbers = None

# Browser tests point custom tools at this server's own /_test/echo, so private addresses must be allowed.
os.environ.setdefault("VOICE_TOOL_ALLOW_PRIVATE_HOSTS", "true")

if not os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Browser tests require a disposable TEST_DATABASE_URL")

settings = Settings(
    app_env="test",
    trusted_proxy_hops=0,
    database_url=os.environ["TEST_DATABASE_URL"],
    database_auth_url=os.environ.get("TEST_AUTH_DATABASE_URL", os.environ["TEST_DATABASE_URL"]),
    database_system_url=os.environ.get("TEST_SYSTEM_DATABASE_URL", os.environ["TEST_DATABASE_URL"]),
    public_app_origin="http://127.0.0.1:3100",
    google_redirect_uri="http://127.0.0.1:3100/api/v1/auth/google/callback",
    invitations_enabled=True,
    email_provider="test",
    email_tasks_project="",
    email_tasks_region="",
    email_tasks_queue="",
    email_tasks_url="",
    email_tasks_audience="",
    email_tasks_invoker_email="",
    email_payload_encryption_key="dGVzdC1vbmx5LW5vdC1hLXByb2R1Y3Rpb24ta2V5ISE=",
    google_client_id="browser-test",
    google_client_secret="browser-test",
)


class BrowserGoogle:
    async def authorization_url(self, state, nonce, verifier):
        return settings.google_redirect_uri + "?" + urlencode({"state": state, "code": str(uuid.uuid4())})

    async def identity(self, code, nonce, verifier):
        return {
            "sub": code,
            "email": "browser@example.com",
            "name": "Browser Owner",
            "email_verified": True,
            "hd": "example.com",
        }


class BrowserClientIsolation:
    """Test-only client identities keep independent cookie jars out of one IP bucket.

    Every context retains the real limiter within its own identity. Production
    never imports this module and continues to count actual client addresses.
    """

    cookie_name = "browser_test_client"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        raw = Request(scope).cookies.get(self.cookie_name, "")
        valid = len(raw) == 32 and all(c in "0123456789abcdef" for c in raw)
        ident = raw if valid else uuid.uuid4().hex
        scope = {**scope, "client": ("browser-test-" + ident, 0)}

        async def reply(message):
            if message["type"] == "http.response.start" and not valid:
                cookie = Response()
                cookie.set_cookie(self.cookie_name, ident, max_age=3600, httponly=True, samesite="lax")
                message = {
                    **message,
                    "headers": [*message.get("headers", []), *[h for h in cookie.raw_headers if h[0] == b"set-cookie"]],
                }
            await send(message)

        await self.app(scope, receive, reply)


app = create_app(settings, google=BrowserGoogle())
app.add_middleware(BrowserClientIsolation)
# Voice calls use a scripted model so browser tests never reach Vertex.
if ScriptedConnector is not None:
    app.state.voice_connector = ScriptedConnector()
    app.state.voice_preview_generator = scripted_voice_preview
    app.state.recording_store = MemoryRecordingStore()
    # Buying a phone number never reaches Twilio: the fake hands out sample numbers.
    app.state.twilio_numbers = FakeNumbers()
    # Knowledge-base uploads stay in memory and embeddings are fake, so browser tests never reach Google.
    from clinic_knowledge.testing import FakeEmbedder, MemoryFileStore

    app.state.knowledge_store = MemoryFileStore()
    app.state.knowledge_embedder = FakeEmbedder()


@app.api_route("/_test/echo", methods=["GET", "POST"], include_in_schema=False)
async def echo(request: Request):
    """A stand-in for a clinic's own API, for the custom-tool test."""
    return {
        "echo": dict(request.query_params) or (await request.json() if await request.body() else {}),
        "open": "9 to 5",
    }


# Explicit test-only capture endpoint. This module is never the production app entry point.
_captured_emails = []


@app.get("/_test/emails", include_in_schema=False)
async def emails():
    from clinic_engagement.email.service import deliver_due

    async def capture(*, to, template):
        _captured_emails.append({"to": to, "text": template.text, "subject": template.subject})
        return "captured"

    await deliver_due(settings, sender=capture)
    return _captured_emails


@app.post("/_test/owner-email", include_in_schema=False)
async def owner_email(request: Request):
    from sqlalchemy import select

    from clinic_core.database import system_session
    from clinic_db.models.core import Staff

    body = await request.json()
    async with system_session(database_url=settings.database_system_url) as db:
        member = await db.scalar(select(Staff).where(Staff.user_id == uuid.UUID(body["user_id"])))
        member.email = body["email"]
    return {"ok": True}
