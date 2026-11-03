"""``POST /features/lead_response/in/sms/{tenant}``: Twilio calls this when someone texts the clinic's number.

The platform mounts a feature's ``websocket_router`` without the staff-session and entitlement dependencies, which is
the only public mechanism it has (voice's Twilio webhook uses it too), so this router sits there. There is no session
here: a request is trusted only if Twilio's signature checks out, and the signature is checked BEFORE anything reads the
database or even looks at the tenant in the URL. Routes are left out of the OpenAPI schema, so the generated client is
untouched.

Answers: 503 not set up, 404 unknown channel, 400 unreadable, 413 too large, 403 bad signature, then 200 with an empty
TwiML ``<Response/>`` for everything else, including texts we cannot or need not store (a 4xx would only make Twilio
alert and retry). Reasons are logged as fixed words; nothing from the request is.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from clinic_core.settings import get_settings
from clinic_lead_response.config import get_intake_settings
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.intake import service, signature
from clinic_lead_response.intake.parse import (
    MAX_BODY_BYTES,
    Dropped,
    Malformed,
    parse_form,
    parse_inbound,
)

log = logging.getLogger("lead_response.intake")

CHANNEL = "sms"
FORM = "application/x-www-form-urlencoded"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'

AfterCommit = Callable[[service.Accepted], Awaitable[None]]


def twiml() -> Response:
    return Response(EMPTY_TWIML, media_type="text/xml")


def refuse(status: int, reason: str, trace_id: uuid.UUID) -> Response:
    log_event(log, "inbound", level=logging.WARNING, outcome="refused", reason=reason, status=status, trace_id=trace_id)
    return Response(status_code=status)


async def read_limited(request: Request) -> bytes | None:
    """The body, or None when it is bigger than any Twilio post. Stops reading at the limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def requested_path(request: Request) -> str:
    raw = request.scope.get("raw_path")
    return raw.decode("ascii", "replace") if raw else request.url.path


def build_router(after_commit: AfterCommit | None = None) -> APIRouter:
    """``after_commit`` is called once a text is stored, after the commit and before the answer; a failure in it is
    logged and ignored. It is for the engine to start the ack at once. Nothing uses it in this chunk."""
    router = APIRouter(include_in_schema=False)

    @router.post("/in/{channel}/{tenant}")
    async def inbound(channel: str, tenant: str, request: Request) -> Response:
        started = time.perf_counter()
        trace_id = uuid.uuid4()  # always ours, never read from the request
        base = get_intake_settings().public_base
        platform = get_settings()
        token, our_number = platform.twilio_auth_token, platform.twilio_from_number
        if not (base and token and our_number):
            return refuse(503, "not_configured", trace_id)
        if channel != CHANNEL:
            return Response(status_code=404)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != FORM:
            return refuse(400, "bad_content_type", trace_id)
        raw = await read_limited(request)
        if raw is None:
            return refuse(413, "too_large", trace_id)

        pairs = parse_form(raw)
        query = request.scope.get("query_string", b"").decode("latin-1")
        url = signature.signed_url(base, requested_path(request), query)
        if not signature.is_valid(token, url, pairs, request.headers.get("x-twilio-signature")):
            return refuse(403, "bad_signature", trace_id)  # nothing from the request has been used yet

        try:
            text = parse_inbound(pairs)
        except Malformed as error:
            return refuse(400, error.reason, trace_id)
        except Dropped as error:
            log_event(log, "inbound", outcome="dropped", reason=error.reason, trace_id=trace_id)
            return twiml()
        if text.recipient != our_number:  # in release 1 there is one number; the tenant comes from the signed URL
            log_event(log, "inbound", outcome="dropped", reason="to_mismatch", trace_id=trace_id)
            return twiml()
        try:
            tenant_id = uuid.UUID(tenant)
        except ValueError:
            tenant_id = None
        if tenant_id is None or str(tenant_id) != tenant:
            log_event(log, "inbound", outcome="dropped", reason="tenant_not_enabled", trace_id=trace_id)
            return twiml()

        accepted = await service.accept(tenant_id, text, trace_id=trace_id, now=datetime.now(UTC))
        if accepted.outcome is service.Outcome.NOT_ENABLED:
            log_event(log, "inbound", outcome="dropped", reason="tenant_not_enabled", trace_id=trace_id)
            return twiml()
        if after_commit is not None and accepted.outcome is service.Outcome.STORED:
            try:
                await after_commit(accepted)
            except Exception:
                log_event(log, "after_commit_failed", level=logging.ERROR, tenant_id=tenant_id, trace_id=trace_id)
        log_event(
            log,
            "inbound",
            tenant_id=tenant_id,
            trace_id=trace_id,
            message_id=accepted.message_id,
            outcome=accepted.outcome.value,
            reason="throttled" if accepted.throttled else None,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return twiml()

    return router
