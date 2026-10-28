"""``/features/voice_receptionist/twilio/stream``: where Twilio sends the call audio once the webhook has answered.

Twilio opens the WebSocket, sends ``connected`` and ``start`` (with our one-time ticket as a custom parameter), then
``media`` messages of 20 ms of 8 kHz mu-law audio until ``stop``. The ticket was only ever given to Twilio inside the
signed webhook answer, works once, and must belong to the same call, so nothing else can open this stream.
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_db.models.voice import Call
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.ws import (
    FEATURE_KEY,
    POLICY_VIOLATION,
    call_ended,
    call_started,
    calls_full,
    fail_call,
    run_session,
)
from clinic_voice_receptionist.twilio_calls.audio import ModelToPhone, phone_to_model

log = logging.getLogger("voice.twilio")
START_TIMEOUT_SECONDS = 10

router = APIRouter(prefix="/twilio", tags=["voice_receptionist"])


class PhoneTransport:
    """The call engine's view of a phone line: PCM16 in at 16 kHz, PCM16 out at 24 kHz."""

    def __init__(self, ws: WebSocket, stream_sid: str):
        self._ws, self._stream_sid, self._to_phone = ws, stream_sid, ModelToPhone()

    async def frames(self) -> AsyncIterator[bytes | dict]:
        while True:
            try:
                message = await self._ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return
            try:
                event = json.loads(message)
            except ValueError:
                continue
            kind = event.get("event") if isinstance(event, dict) else None
            if kind == "media":
                try:
                    yield phone_to_model(base64.b64decode(event["media"]["payload"]))
                except (KeyError, TypeError, ValueError):
                    continue
            elif kind == "stop":
                return

    async def _send(self, message: dict) -> None:
        if self._ws.application_state == WebSocketState.CONNECTED:
            try:
                await self._ws.send_text(json.dumps(message))
            except (WebSocketDisconnect, RuntimeError):
                pass  # the receive side sees the hang-up and ends the call

    async def send_audio(self, pcm: bytes) -> None:
        mulaw = self._to_phone.convert(pcm)
        if mulaw:
            payload = base64.b64encode(mulaw).decode()
            await self._send({"event": "media", "streamSid": self._stream_sid, "media": {"payload": payload}})

    async def send_event(self, event: dict) -> None:
        if event.get("type") == "interrupted":
            # The caller spoke over the agent: throw away what Twilio has buffered but not yet played.
            self._to_phone.reset()
            await self._send({"event": "clear", "streamSid": self._stream_sid})


async def _read_start(ws: WebSocket) -> dict | None:
    """The ``start`` message, after the ``connected`` greeting. None if it does not come soon or is not valid."""
    try:
        async with asyncio.timeout(START_TIMEOUT_SECONDS):
            while True:
                event = json.loads(await ws.receive_text())
                if isinstance(event, dict) and event.get("event") == "start":
                    return event.get("start") or {}
    except (TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
        return None


@router.websocket("/stream")
async def phone_stream(ws: WebSocket) -> None:
    settings = ws.app.state.settings
    await ws.accept()  # Twilio sends its first messages right away; refusing later is a close with a code
    start = await _read_start(ws)
    ticket = ((start or {}).get("customParameters") or {}).get("ticket")
    stream_sid, call_sid = (start or {}).get("streamSid"), (start or {}).get("callSid")
    if not ticket or not stream_sid or calls_full():
        await ws.close(POLICY_VIOLATION)
        return
    redeemed = await tickets.redeem(ticket, settings.database_url)
    if redeemed is None:
        await ws.close(POLICY_VIOLATION)
        return
    tenant_id, call_id = redeemed
    async with tenant_session(tenant_id, database_url=settings.database_url) as session:
        call = await session.get(Call, call_id)
        entitled = FEATURE_KEY in await enabled_feature_keys(session)
        snapshot = call.agent_snapshot if call else None
        # A browser test call has no provider id, and the client chooses what to send as callSid: both being empty
        # must not count as a match, or a test-call ticket could open this stream and skip the browser socket's checks.
        same_call = bool(call and call_sid and call.channel == "twilio" and call.provider_call_id == call_sid)
    if not entitled or snapshot is None or not same_call:  # a ticket only opens the stream of its own call
        await fail_call(tenant_id, call_id, "not_allowed", settings.database_url)
        await ws.close(POLICY_VIOLATION)
        return
    call_started()
    try:
        await run_session(ws.app, tenant_id, call_id, snapshot, PhoneTransport(ws, stream_sid))
    finally:
        call_ended()
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.close()
