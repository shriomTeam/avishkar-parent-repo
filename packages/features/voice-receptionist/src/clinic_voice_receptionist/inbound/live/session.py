"""One live call: caller audio in, agent audio out, transcript and captured fields saved on the way.

The call talks to two things through small interfaces: a ``Transport`` (the browser WebSocket now,
Twilio Media Streams later) and a ``ModelConnector`` (Gemini). Neither is imported here.
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol

from clinic_voice_receptionist.inbound.live.audio import CallAudio
from clinic_voice_receptionist.inbound.live.events import (
    AudioOut,
    GoAway,
    Interrupted,
    ModelClosed,
    ModelConnector,
    Resumable,
    ToolCall,
    ToolResult,
    Transcript,
    TurnComplete,
    Usage,
)
from clinic_voice_receptionist.inbound.live.fields import coerce_all
from clinic_voice_receptionist.inbound.live.prompt import END_TOOL, SAVE_TOOL
from clinic_voice_receptionist.inbound.live.recorder import CallRecorder
from clinic_voice_receptionist.inbound.live.storage import RecordingStore, recording_name
from clinic_voice_receptionist.tools.runner import STORED_LIMIT, ToolOutcome, limited

log = logging.getLogger("voice.call")

MAX_FRAME_BYTES = 32_000  # one second of 16 kHz PCM16; anything larger is not a live-audio frame
OUTBOUND_AUDIO_QUEUE = 256  # chunks buffered for a slow client before the oldest are dropped
FLUSH_SECONDS = 2.0
MAX_RECONNECTS = 3
PENDING_FRAMES = 50  # about one second of caller audio kept while the model connection is (re)opening


class Transport(Protocol):
    def frames(self) -> AsyncIterator[bytes | dict]:
        """Caller audio (PCM16 16 kHz) as bytes, or control messages such as {"type": "hangup"}."""

    async def send_audio(self, pcm: bytes) -> None: ...

    async def send_event(self, event: dict) -> None: ...


class CallSession:
    def __init__(
        self,
        *,
        snapshot: dict,
        transport: Transport,
        connector: ModelConnector,
        recorder: CallRecorder,
        max_seconds: int,
        tool_runner=None,
        audio: CallAudio | None = None,
        store: RecordingStore | None = None,
    ):
        self.snapshot = snapshot
        self.fields = snapshot.get("fields", [])
        self.tool_runner = tool_runner
        self.audio, self.store = audio, store  # audio is None when this call is not being recorded
        self._tools = {t["name"]: t for t in snapshot.get("tools", [])}
        self.transport, self.connector, self.recorder = transport, connector, recorder
        self.max_seconds = max_seconds
        self.started_at = datetime.now(UTC)
        self._t0 = time.monotonic()
        self._model = None
        self._pending: deque[bytes] = deque(maxlen=PENDING_FRAMES)
        self._handle: str | None = None
        self._usage: dict = {}
        self._values: dict = {}
        self._partial: dict[str, str] = {}
        self._partial_offset: dict[str, int] = {}
        self._speaker: str | None = None
        self._out: asyncio.Queue[bytes] = asyncio.Queue(OUTBOUND_AUDIO_QUEUE)
        self._hangup_after_turn = False
        self.end_reason: str | None = None
        self.failed = False

    def _offset_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    # ---- lifecycle -------------------------------------------------------------------------------------

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(coro)
            for coro in (self._caller_to_model(), self._audio_to_caller(), self._model_loop(), self._housekeeping())
        ]
        try:
            # The call lasts until any task finishes. Each one calls ``_end`` first when it ends on purpose.
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception():
                    log.error("call %s task crashed", self.recorder.call_id, exc_info=task.exception())
                    self._end("error", failed=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._finish()

    def _end(self, reason: str, *, failed: bool = False) -> None:
        """Record why the call ended. The first reason wins."""
        if self.end_reason is None:
            self.end_reason, self.failed = reason, failed

    async def _finish(self) -> None:
        self._close_turn()
        status = "failed" if self.failed else "completed"
        reason = self.end_reason or "completed"
        recording = await self._save_recording()
        try:
            await self.recorder.finish(
                status=status, end_reason=reason, started_at=self.started_at, usage=self._usage, recording=recording
            )
        except Exception:
            log.exception("could not save call %s", self.recorder.call_id)
        try:
            await self.transport.send_event({"type": "ended", "reason": reason})
        except Exception:
            pass

    async def _save_recording(self) -> tuple[str | None, str] | None:
        """Upload the call audio. Returns (object name, "saved"/"failed"), or None if there is nothing to keep."""
        if self.audio is None or self.audio.seconds < 0.5:
            return None
        name = recording_name(self.recorder.tenant_id, self.recorder.call_id)
        if self.store is None:
            log.error("call %s should be recorded but no storage is configured", self.recorder.call_id)
            return None, "failed"
        data = self.audio.to_wav()
        for attempt in (1, 2):
            try:
                await self.store.put(name, data)
                return name, "saved"
            except Exception:
                log.exception("could not upload the recording of call %s (attempt %s)", self.recorder.call_id, attempt)
        return None, "failed"

    # ---- caller -> model -------------------------------------------------------------------------------

    async def _caller_to_model(self) -> None:
        async for frame in self.transport.frames():
            if isinstance(frame, dict):
                if frame.get("type") == "hangup":
                    self._end("caller_hangup")
                    return
                continue
            if len(frame) > MAX_FRAME_BYTES or len(frame) % 2:
                continue  # not a PCM16 frame
            if self.audio is not None:
                self.audio.caller(frame, time.monotonic() - self._t0)
            model = self._model
            if model is None:
                self._pending.append(frame)  # kept briefly; older audio is dropped like a lost packet
                continue
            try:
                await model.send_audio(frame)
            except Exception:
                pass  # the model loop notices a dead connection and handles it
        self._end("caller_disconnected")

    # ---- model -> caller -------------------------------------------------------------------------------

    async def _model_loop(self) -> None:
        reconnects = 0
        while True:
            try:
                async with self.connector.connect(self.snapshot, self.fields, self._handle) as model:
                    if reconnects == 0:
                        await model.send_text(self._opening())
                    while self._pending:
                        await model.send_audio(self._pending.popleft())
                    self._model = model
                    if await self._read(model):
                        return  # the call ended while reading
            except ModelClosed:
                pass
            except Exception:
                log.exception("model connection failed for call %s", self.recorder.call_id)
            finally:
                self._model = None
            if self._hangup_after_turn:
                self._end("agent_ended")
                return
            if self._handle is None or reconnects >= MAX_RECONNECTS:
                self._end("model_disconnected", failed=True)
                return
            reconnects += 1
            await asyncio.sleep(0.2 * reconnects)

    def _opening(self) -> str:
        greeting = self.snapshot.get("greeting")
        if greeting:
            return f'The call has just connected. Greet the caller by saying: "{greeting}"'
        return "The call has just connected. Greet the caller."

    async def _read(self, model) -> bool:
        """Handle model messages. True if the call is over, False if the model asked us to reconnect."""
        async for received in model.messages():
            if received.raw is not None:
                self.recorder.event("model", received.raw)
            reconnect = False
            results: list[ToolResult] = []
            for event in received.events:
                match event:
                    case AudioOut(data):
                        if self.audio is not None:
                            self.audio.agent(data, time.monotonic() - self._t0)
                        self._queue_audio(data)
                    case Transcript(speaker, text):
                        await self._on_transcript(speaker, text)
                    case Interrupted():
                        self._drain_audio()
                        if self.audio is not None:
                            self.audio.interrupt(time.monotonic() - self._t0)
                        self._close_turn(interrupted=True)
                        await self.transport.send_event({"type": "interrupted"})
                    case TurnComplete():
                        self._close_turn()
                        if self._hangup_after_turn:
                            await self._out.join()  # let the goodbye finish playing
                            self._end("agent_ended")
                            return True
                    case ToolCall():
                        results.append(await self._on_tool(event))
                    case Usage(data):
                        self._usage = data
                    case Resumable(handle):
                        self._handle = handle
                    case GoAway():
                        reconnect = True
            if results:
                await model.send_tool_results(results)
            if reconnect:
                return False  # the caller reconnects with the resumption handle
        return False

    async def _on_transcript(self, speaker: str, text: str) -> None:
        if self._speaker not in (None, speaker):
            self._close_turn()
        self._speaker = speaker
        self._partial_offset.setdefault(speaker, self._offset_ms())
        self._partial[speaker] = self._partial.get(speaker, "") + text
        await self.transport.send_event(
            {"type": "transcript", "speaker": speaker, "text": self._partial[speaker].strip(), "final": False}
        )

    def _close_turn(self, *, interrupted: bool = False) -> None:
        for speaker, text in list(self._partial.items()):
            self.recorder.turn(
                speaker, text, self._partial_offset.get(speaker, 0), interrupted=interrupted and speaker == "agent"
            )
        self._partial.clear()
        self._partial_offset.clear()
        self._speaker = None

    async def _on_tool(self, call: ToolCall) -> ToolResult:
        if call.name == END_TOOL:
            self._hangup_after_turn = True
            return ToolResult(call.id, call.name, {"ok": True})
        if call.name != SAVE_TOOL:
            ref = self._tools.get(call.name)
            if ref is None or self.tool_runner is None:
                return ToolResult(call.id, call.name, {"ok": False, "error": "unknown function"})
            return await self._run_tool(ref, call)
        valid, errors = coerce_all(self.fields, call.args)
        if valid:
            self._values.update(valid)
            self.recorder.values(valid)
            await self.transport.send_event({"type": "fields", "values": self._values})
        response: dict = {"ok": not errors, "saved": sorted(valid)}
        if errors:
            response["invalid"] = errors  # the model reads this and asks the caller again
        return ToolResult(call.id, call.name, response)

    async def _run_tool(self, ref: dict, call: ToolCall) -> ToolResult:
        """Run a configured tool. The caller hears silence while it runs (the model waits), so it is time-boxed."""
        await self.transport.send_event({"type": "tool", "name": ref["name"], "status": "running"})
        key = f"{self.recorder.call_id}:{call.name}:{call.id}"
        try:
            outcome = await asyncio.wait_for(
                self.tool_runner.run(ref, call.args, key), timeout=ref.get("timeout_seconds", 5) + 3
            )
        except TimeoutError:
            response = {"ok": False, "error": "The tool took too long to answer."}
            outcome = ToolOutcome(False, response, "timed out", 0, response)
        self.recorder.execution(
            {
                "tool_id": uuid.UUID(ref["id"]),
                "tool_name": ref["name"],
                "input": limited(call.args, STORED_LIMIT),
                "output": outcome.stored_output,
                "success": outcome.success,
                "error": outcome.error,
                "duration_ms": outcome.duration_ms,
                "idempotency_key": key,
            }
        )
        await self.transport.send_event(
            {
                "type": "tool",
                "name": ref["name"],
                "status": "ok" if outcome.success else "failed",
                "duration_ms": outcome.duration_ms,
            }
        )
        return ToolResult(call.id, call.name, outcome.response)

    # ---- agent audio to the caller ---------------------------------------------------------------------

    def _queue_audio(self, data: bytes) -> None:
        if self._out.full():
            self._out.get_nowait()  # drop the oldest chunk rather than grow without bound
            self._out.task_done()
        self._out.put_nowait(data)

    def _drain_audio(self) -> None:
        while not self._out.empty():
            self._out.get_nowait()
            self._out.task_done()

    async def _audio_to_caller(self) -> None:
        while True:
            chunk = await self._out.get()
            try:
                await self.transport.send_audio(chunk)
            finally:
                self._out.task_done()

    # ---- limits and persistence ------------------------------------------------------------------------

    async def _housekeeping(self) -> None:
        deadline = self._t0 + self.max_seconds
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            try:
                await self.recorder.flush()
            except Exception:
                log.warning("flush failed for call %s; will retry", self.recorder.call_id)
            if time.monotonic() >= deadline:
                self._end("max_duration")
                return
