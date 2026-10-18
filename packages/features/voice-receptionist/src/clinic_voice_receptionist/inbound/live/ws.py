"""The browser's call WebSocket: ``/features/voice_receptionist/inbound/live?ticket=...``.

Browser sends: binary PCM16 16 kHz mono frames, and {"type": "hangup"}.
Server sends: binary PCM16 24 kHz agent audio, and JSON events
  ready, transcript, fields, interrupted, ended, error.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket
from sqlalchemy import update
from starlette.websockets import WebSocketDisconnect, WebSocketState

from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_db.models.voice import Call
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.events import INPUT_RATE, OUTPUT_RATE
from clinic_voice_receptionist.inbound.live.gemini import GeminiConnector
from clinic_voice_receptionist.inbound.live.recorder import CallRecorder
from clinic_voice_receptionist.inbound.live.session import CallSession
from clinic_voice_receptionist.tools.runner import ToolRunner

log = logging.getLogger("voice.ws")
FEATURE_KEY = "voice_receptionist"
POLICY_VIOLATION, TRY_AGAIN_LATER = 1008, 1013

ws_router = APIRouter()
_active_calls = 0


class WebSocketTransport:
    def __init__(self, ws: WebSocket):
        self._ws = ws

    async def frames(self) -> AsyncIterator[bytes | dict]:
        while True:
            message = await self._ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                yield message["bytes"]
            elif message.get("text"):
                try:
                    control = json.loads(message["text"])
                except ValueError:
                    continue
                if isinstance(control, dict):
                    yield control

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws.application_state == WebSocketState.CONNECTED:
            try:
                await self._ws.send_bytes(pcm)
            except (WebSocketDisconnect, RuntimeError):
                pass  # the receive side sees the disconnect and ends the call

    async def send_event(self, event: dict) -> None:
        if self._ws.application_state == WebSocketState.CONNECTED:
            try:
                await self._ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                pass


async def fail_call(tenant_id: uuid.UUID, call_id: uuid.UUID, reason: str, database_url: str | None) -> None:
    """End a call that was opened (its ticket used) but never got to run, so it is not left "in progress"."""
    async with tenant_session(tenant_id, database_url=database_url) as session:
        await session.execute(
            update(Call)
            .where(Call.id == call_id, Call.status == "in_progress")
            .values(status="failed", end_reason=reason, ended_at=datetime.now(UTC), duration_seconds=0)
        )


def _origin_allowed(ws: WebSocket) -> bool:
    """Browsers always send Origin on WebSocket handshakes; refuse pages from other sites."""
    settings = ws.app.state.settings
    return ws.headers.get("origin") in {settings.public_app_origin, *settings.cors_origins}


@ws_router.websocket("/inbound/live")
async def live_call(ws: WebSocket, ticket: str = Query(min_length=1, max_length=300)) -> None:
    global _active_calls
    settings, voice = ws.app.state.settings, get_voice_settings()
    if not _origin_allowed(ws):
        await ws.close(POLICY_VIOLATION)
        return
    if _active_calls >= voice.max_concurrent_calls:
        await ws.close(TRY_AGAIN_LATER)
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
    if not entitled or snapshot is None:
        await fail_call(tenant_id, call_id, "not_allowed", settings.database_url)
        await ws.close(POLICY_VIOLATION)
        return

    await ws.accept()
    _active_calls += 1
    try:
        try:
            await ws.send_json({"type": "ready", "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})
        except (WebSocketDisconnect, RuntimeError):
            await fail_call(tenant_id, call_id, "caller_disconnected", settings.database_url)  # gone before it began
            return
        connector = getattr(ws.app.state, "voice_connector", None) or GeminiConnector(voice)
        recorder = CallRecorder(tenant_id, call_id, snapshot, settings.database_url)
        await CallSession(
            snapshot=snapshot,
            transport=WebSocketTransport(ws),
            connector=connector,
            recorder=recorder,
            max_seconds=voice.max_call_seconds,
            tool_runner=ToolRunner(tenant_id=tenant_id, call_id=call_id, database_url=settings.database_url),
        ).run()
    finally:
        _active_calls -= 1
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.close()
