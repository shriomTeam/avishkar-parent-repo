"""Helpers for the intake tests. Every number, id and word here is made up; nothing can reach the network.

``reference_signature`` is written out separately from the code under test, so a test never checks the code against
itself."""

import base64
import hashlib
import hmac
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from clinic_core.database import tenant_session
from clinic_lead_response.config import IntakeSettings
from clinic_lead_response.feature import feature
from clinic_lead_response.intake import routes
from clinic_lead_response.intake.parse import parse_form

TOKEN = "test-auth-token-not-a-real-secret"
PUBLIC = "https://api.example.test"
OUR_NUMBER = "+14155550100"
LEAD_NUMBER = "+14155550142"
SID = "SM" + "a1" * 16  # a Twilio message sid is SM or MM plus 32 hex characters
BODY = "Zebra-Quartz sentinel wording that must never be logged"


def reference_signature(token: str, url: str, pairs: list[tuple[str, str]]) -> str:
    text = url
    for name, value in sorted(pairs):
        text += name + value
    return base64.b64encode(hmac.new(token.encode(), text.encode(), hashlib.sha1).digest()).decode()


def twilio_pairs(**overrides: str) -> list[tuple[str, str]]:
    """What Twilio posts for one inbound text. A value of None in ``overrides`` removes the field."""
    fields = {
        "MessageSid": SID,
        "SmsSid": SID,
        "SmsMessageSid": SID,
        "AccountSid": "AC" + "b2" * 16,
        "MessagingServiceSid": "",
        "From": LEAD_NUMBER,
        "To": OUR_NUMBER,
        "Body": BODY,
        "NumMedia": "0",
        "NumSegments": "1",
        "SmsStatus": "received",
        "ApiVersion": "2010-04-01",
    }
    fields.update(overrides)
    return [(name, value) for name, value in fields.items() if value is not None]


def form_bytes(pairs: list[tuple[str, str]]) -> bytes:
    return urlencode(pairs).encode()


# --- an app that mounts the real router, and small readers (they need the test database) -------------------------

PATH = "/features/lead_response"
FORM = "application/x-www-form-urlencoded"


class Intake:
    """The real public router in a test app, with the platform settings and the public address replaced. Nothing here
    can reach the network: requests go straight into the app."""

    def __init__(self, monkeypatch, *, base: str = PUBLIC, token: str = TOKEN, number: str = OUR_NUMBER, hook=None):
        platform = SimpleNamespace(twilio_auth_token=token, twilio_from_number=number)
        monkeypatch.setattr(routes, "get_settings", lambda: platform)
        monkeypatch.setattr(routes, "get_intake_settings", lambda: IntakeSettings(_env_file=None, public_api_url=base))
        self.app = FastAPI()

        @self.app.exception_handler(RequestValidationError)
        async def validation_error(request, exc):  # the same handler apps/api registers
            return JSONResponse({"detail": "invalid_request"}, status_code=422)

        router = feature.websocket_router if hook is None else routes.build_router(hook)
        self.app.include_router(router, prefix=PATH)

    def client(self, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=raise_app_exceptions)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def post(
        self,
        tenant,
        pairs: list[tuple[str, str]] | None = None,
        *,
        raw: bytes | None = None,
        sign: bool = True,
        token: str = TOKEN,
        signed_path: str | None = None,
        query: str = "",
        channel: str = "sms",
        headers: dict[str, str] | None = None,
        content_type: str = FORM,
        raise_app_exceptions: bool = True,
    ) -> httpx.Response:
        """Post a text the way Twilio does. By default the signature is correct for what is sent; ``signed_path`` signs
        another path, ``sign=False`` sends none."""
        path = f"{PATH}/in/{channel}/{tenant}"
        body = raw if raw is not None else form_bytes(pairs if pairs is not None else twilio_pairs())
        send = {"content-type": content_type, **(headers or {})}
        if sign:
            url = PUBLIC + (signed_path or path) + (f"?{query}" if query else "")
            send["x-twilio-signature"] = reference_signature(token, url, parse_form(body))
        async with self.client(raise_app_exceptions=raise_app_exceptions) as client:
            return await client.post(path + (f"?{query}" if query else ""), content=body, headers=send)

    async def post_status(
        self,
        tenant,
        pairs: list[tuple[str, str]],
        *,
        m=None,
        raw: bytes | None = None,
        sign: bool = True,
        token: str = TOKEN,
        signed_path: str | None = None,
        signed_query: str | None = None,
        channel: str = "sms",
        headers: dict[str, str] | None = None,
        content_type: str = FORM,
        raise_app_exceptions: bool = True,
    ) -> httpx.Response:
        """Post a delivery receipt the way Twilio does, to the URL the gateway would have given it (``m`` is the
        message id in the query). The signature is correct for what is sent unless ``signed_path`` or
        ``signed_query`` say otherwise."""
        path = f"{PATH}/status/{channel}/{tenant}"
        query = f"m={m}" if m else ""
        body = raw if raw is not None else form_bytes(pairs)
        send = {"content-type": content_type, **(headers or {})}
        if sign:
            signed = query if signed_query is None else signed_query
            url = PUBLIC + (signed_path or path) + (f"?{signed}" if signed else "")
            send["x-twilio-signature"] = reference_signature(token, url, parse_form(body))
        async with self.client(raise_app_exceptions=raise_app_exceptions) as client:
            return await client.post(path + (f"?{query}" if query else ""), content=body, headers=send)


def receipt_pairs(message_sid: str, status: str = "delivered", **overrides: str) -> list[tuple[str, str]]:
    """What Twilio posts to a StatusCallback. A value of None in ``overrides`` removes the field."""
    fields = {
        "MessageSid": message_sid,
        "SmsSid": message_sid,
        "MessageStatus": status,
        "SmsStatus": status,
        "AccountSid": "AC" + "b2" * 16,
        "From": OUR_NUMBER,
        "To": LEAD_NUMBER,
        "ApiVersion": "2010-04-01",
    }
    fields.update(overrides)
    return [(name, value) for name, value in fields.items() if value is not None]


async def rows(tenant, model, *order):
    async with tenant_session(tenant) as session:
        return list(await session.scalars(select(model).order_by(*order)))


async def count(tenant, model) -> int:
    async with tenant_session(tenant) as session:
        return await session.scalar(select(func.count()).select_from(model))


def sid(n: int) -> str:
    return f"SM{n:032x}"


class Counter:
    """Counts the SQL statements run while it is open."""

    def __enter__(self):
        self.statements: list[str] = []
        event.listen(Engine, "before_cursor_execute", self._seen)
        return self.statements

    def _seen(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __exit__(self, *exc):
        event.remove(Engine, "before_cursor_execute", self._seen)
