"""The browser's call WebSocket: ``/features/voice_receptionist/inbound/live?ticket=...``.

Browser sends: binary PCM16 16 kHz mono frames, and {"type": "hangup"}.
Server sends: binary PCM16 24 kHz agent audio, and JSON events
  ready, transcript, fields, interrupted, ended, error.
"""

import asyncio
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
from clinic_core.tenancy.permissions import live_session_allowed
from clinic_db.models.voice import Call
from clinic_knowledge.config import get_knowledge_settings
from clinic_knowledge.queue import embedder_for
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.inbound.live.audio import CallAudio
from clinic_voice_receptionist.inbound.live.events import INPUT_RATE, OUTPUT_RATE
from clinic_voice_receptionist.inbound.live.gemini import GeminiConnector
from clinic_voice_receptionist.inbound.live.recorder import CallRecorder
from clinic_voice_receptionist.inbound.live.session import CallSession
from clinic_voice_receptionist.inbound.live.storage import store_for
from clinic_voice_receptionist.tools.runner import ToolRunner

log = logging.getLogger("voice.ws")
FEATURE_KEY = "voice_receptionist"
POLICY_VIOLATION, TRY_AGAIN_LATER = 1008, 1013

ws_router = APIRouter()
_active_calls = 0


def calls_full() -> bool:
    return _active_calls >= get_voice_settings().max_concurrent_calls


def call_started() -> None:
    global _active_calls
    _active_calls += 1


def call_ended() -> None:
    global _active_calls
    _active_calls -= 1


async def run_session(
    app,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    snapshot: dict,
    transport,
    *,
    authorize=None,
    on_revoked=None,
) -> None:
    """Run one call to its end, over any transport (browser WebSocket or phone line).

    ``authorize`` is for calls started by a signed-in staff member: it is checked before every tool runs and every few
    seconds, and the call ends when it says no. Phone calls have no staff session, so they pass none: they are trusted
    because Twilio's signature was valid and the dialled number belongs to the clinic.
    """
    settings, voice = app.state.settings, get_voice_settings()
    connector = getattr(app.state, "voice_connector", None) or GeminiConnector(voice)
    recorder = CallRecorder(tenant_id, call_id, snapshot, settings.database_url)
    running = CallSession(
        authorize=authorize,
        snapshot=snapshot,
        transport=transport,
        connector=connector,
        recorder=recorder,
        max_seconds=voice.max_call_seconds,
        tool_runner=ToolRunner(
            tenant_id=tenant_id,
            call_id=call_id,
            database_url=settings.database_url,
            embedder=embedder_for(app, get_knowledge_settings()),
        ),
        audio=CallAudio(voice.max_call_seconds) if snapshot.get("save_recording") else None,
        store=store_for(app, voice),
    )

    async def watch_access() -> None:
        while True:
            await asyncio.sleep(5)
            if not await authorize():
                running._end("access_revoked", failed=True)
                if on_revoked is not None:
                    await on_revoked()
                return

    monitor = asyncio.create_task(watch_access()) if authorize is not None else None
    try:
        await running.run()
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)


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
    settings = ws.app.state.settings
    if not _origin_allowed(ws):
        await ws.close(POLICY_VIOLATION)
        return
    if calls_full():
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
        auth_session_id = call.auth_session_id if call else None

    async def authorized():
        try:
            return await live_session_allowed(settings, auth_session_id, tenant_id)
        except Exception:
            return False  # fail closed if membership/session revalidation is unavailable

    if not entitled or snapshot is None or not await authorized():
        await fail_call(tenant_id, call_id, "not_allowed", settings.database_url)
        await ws.close(POLICY_VIOLATION)
        return

    await ws.accept()
    call_started()
    try:
        try:
            await ws.send_json({"type": "ready", "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})
        except (WebSocketDisconnect, RuntimeError):
            await fail_call(tenant_id, call_id, "caller_disconnected", settings.database_url)  # gone before it began
            return

        async def close_for_revoked_access() -> None:
            if ws.application_state == WebSocketState.CONNECTED:
                await ws.close(POLICY_VIOLATION)

        await run_session(
            ws.app,
            tenant_id,
            call_id,
            snapshot,
            WebSocketTransport(ws),
            authorize=authorized,  # a staff member's test call ends when their access does
            on_revoked=close_for_revoked_access,
        )
    finally:
        call_ended()
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.close()
