"""``POST /features/voice_receptionist/twilio/voice``: Twilio calls this when someone dials one of our numbers.

There is no staff session here, so the request is trusted only if Twilio's signature checks out. We then find the clinic
and agent from the number that was dialled, record the call, and answer with TwiML that tells Twilio to stream the call
audio to our WebSocket, carrying a one-time ticket for that stream.
"""

import logging
import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, unquote
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_core.settings import get_settings
from clinic_db.models.voice import Agent, Call, PhoneNumber
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.call_setup import build_snapshot, expire_stale_calls
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.ws import calls_full
from clinic_voice_receptionist.numbers.client import VOICE_PATH
from clinic_voice_receptionist.twilio_calls import signature

log = logging.getLogger("voice.twilio")
FEATURE_KEY = "voice_receptionist"
STREAM_PATH = "/features/voice_receptionist/twilio/stream"

router = APIRouter(prefix="/twilio", tags=["voice_receptionist"])

CALL_SID = re.compile(r"^CA[0-9a-fA-F]{32}$")
E164 = re.compile(r"^\+[1-9]\d{6,14}$")

SIP_ADDRESS = re.compile(r"^sip:([^@;]+)@", re.IGNORECASE)


def dialled_number(to: str, allow_sip: bool) -> str:
    """The number that was dialled. A SIP-domain call (local testing only) carries it inside a SIP address."""
    match = SIP_ADDRESS.match(to) if allow_sip else None
    if not match:
        return to
    user = unquote(match.group(1)).replace("-", "").replace(" ", "")
    if re.fullmatch(r"1\d{10}", user):
        return "+" + user
    if re.fullmatch(r"\d{10}", user):
        return "+1" + user
    return user


NOT_IN_SERVICE = "This number is not in service. Goodbye."
BUSY = "We are sorry, we cannot take your call right now. Please try again in a few minutes."


def xml(body: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="text/xml")


def say_and_hang_up(message: str) -> Response:
    return xml(f"<Say>{message}</Say><Hangup/>")


def connect_stream(public_url: str, ticket: str) -> Response:
    ws_url = re.sub(r"^http", "ws", public_url.rstrip("/")) + STREAM_PATH
    stream = f'<Stream url={quoteattr(ws_url)}><Parameter name="ticket" value={quoteattr(ticket)}/></Stream>'
    return xml(f"<Connect>{stream}</Connect>")


@router.post("/voice")
async def incoming_call(request: Request) -> Response:
    voice, core = get_voice_settings(), get_settings()
    public = voice.public_api_url.strip().rstrip("/")
    if not public or not core.twilio_auth_token:
        return Response("Phone calls are not set up on this server.", status_code=503)
    params = dict(parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))
    if not signature.is_valid(
        core.twilio_auth_token, public + VOICE_PATH, params, request.headers.get("x-twilio-signature")
    ):
        return Response("Forbidden", status_code=403)  # nothing from the request has been used yet

    call_sid, from_number = params.get("CallSid", ""), params.get("From", "")
    to_number = dialled_number(params.get("To", ""), voice.allow_sip_test_calls)
    if not CALL_SID.match(call_sid) or not E164.match(to_number):
        return Response("Bad request", status_code=400)
    caller = from_number if E164.match(from_number) else None  # withheld numbers arrive as text, not E.164

    # Which clinic owns the dialled number is not known yet, so this one lookup uses the system role.
    async with system_session(database_url=core.database_system_url) as db:
        owner = (
            await db.execute(select(PhoneNumber.tenant_id, PhoneNumber.agent_id).where(PhoneNumber.number == to_number))
        ).one_or_none()
    if owner is None:
        return say_and_hang_up(NOT_IN_SERVICE)
    tenant_id, agent_id = owner
    if agent_id is None:
        return say_and_hang_up(NOT_IN_SERVICE)
    if calls_full():
        return say_and_hang_up(BUSY)

    now = datetime.now(UTC)
    async with tenant_session(tenant_id, database_url=core.database_url) as session:
        agent = await session.get(Agent, agent_id)
        if agent is None or not agent.is_active or FEATURE_KEY not in await enabled_feature_keys(session):
            return say_and_hang_up(NOT_IN_SERVICE)
        await expire_stale_calls(session, voice, now)
        # Twilio retries a webhook it did not get an answer to: the same CallSid is the same call.
        call = await session.scalar(select(Call).where(Call.provider_call_id == call_sid))
        if call is not None and call.status != "connecting":
            return say_and_hang_up(BUSY)
        if call is None:
            snapshot = await build_snapshot(session, agent, tenant_id, caller_number=caller, now=now)
            call = Call(
                tenant_id=tenant_id,
                agent_id=agent.id,
                agent_snapshot=snapshot,
                direction="inbound",
                channel="twilio",
                is_test=False,
                status="connecting",
                model=agent.model,
                from_number=caller,
                to_number=to_number,
                provider_call_id=call_sid,
            )
            session.add(call)
            await session.flush()
        ticket = tickets.mint(call)
        call_id = call.id
    log.info("incoming call %s accepted for call %s", call_sid, call_id)  # no numbers in logs: they identify people
    return connect_stream(public, ticket)
