"""Gemini Live on Vertex AI, behind the provider-neutral ``ModelConnector`` interface."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from google import genai
from google.genai import types

from clinic_voice_receptionist.config import VoiceSettings
from clinic_voice_receptionist.inbound.live.events import (
    INPUT_RATE,
    AudioOut,
    GoAway,
    Interrupted,
    ModelClosed,
    ModelEvent,
    Received,
    Resumable,
    ToolCall,
    ToolResult,
    Transcript,
    TurnComplete,
    Usage,
)
from clinic_voice_receptionist.inbound.live.prompt import function_declarations, system_instruction

# Phone-call tuning. Barge-in is detected quickly (HIGH start), but the agent waits for a real pause
# before answering (LOW end, 700 ms) so callers can spell out numbers without being cut off.
START_SENSITIVITY = types.StartSensitivity.START_SENSITIVITY_HIGH
END_SENSITIVITY = types.EndSensitivity.END_SENSITIVITY_LOW
PREFIX_PADDING_MS = 100
SILENCE_MS = 700

# Left out of the stored raw record: audio bytes (large), per-chunk usage counters (noisy),
# and the resumption handle (a credential for the live session).
_RAW_EXCLUDE = {
    "usage_metadata": True,
    "session_resumption_update": True,
    "server_content": {"model_turn": {"parts": {"__all__": {"inline_data"}}}},
}


def build_config(agent: dict, fields: list[dict], resume_handle: str | None) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=system_instruction(agent, fields),
        speech_config=types.SpeechConfig(
            language_code=agent["language"],
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=agent["voice"])),
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=START_SENSITIVITY,
                end_of_speech_sensitivity=END_SENSITIVITY,
                prefix_padding_ms=PREFIX_PADDING_MS,
                silence_duration_ms=SILENCE_MS,
            )
        ),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(**d) for d in function_declarations(fields, agent.get("tools"))
                ]
            )
        ],
    )


def _raw(msg: types.LiveServerMessage) -> dict | None:
    raw = msg.model_dump(mode="json", exclude_none=True, exclude=_RAW_EXCLUDE)
    content = raw.get("server_content")
    if content is not None:
        parts = [p for p in content.get("model_turn", {}).get("parts", []) if p]
        if parts:
            content["model_turn"]["parts"] = parts
        else:
            content.pop("model_turn", None)
        if not content:
            raw.pop("server_content")
    return raw or None


def _events(msg: types.LiveServerMessage) -> list[ModelEvent]:
    events: list[ModelEvent] = []
    if (content := msg.server_content) is not None:
        for part in content.model_turn.parts or [] if content.model_turn else []:
            if part.inline_data and part.inline_data.data:
                events.append(AudioOut(part.inline_data.data))
        if content.input_transcription and content.input_transcription.text:
            events.append(Transcript("caller", content.input_transcription.text))
        if content.output_transcription and content.output_transcription.text:
            events.append(Transcript("agent", content.output_transcription.text))
        if content.interrupted:
            events.append(Interrupted())
        if content.turn_complete:
            events.append(TurnComplete())
    if msg.tool_call:
        for call in msg.tool_call.function_calls or []:
            events.append(ToolCall(id=call.id or call.name, name=call.name, args=dict(call.args or {})))
    if msg.usage_metadata:
        events.append(Usage(msg.usage_metadata.model_dump(mode="json", exclude_none=True, exclude={"traffic_type"})))
    update = msg.session_resumption_update
    if update and update.resumable and update.new_handle:
        events.append(Resumable(update.new_handle))
    if msg.go_away:
        events.append(GoAway())
    return events


class GeminiSession:
    def __init__(self, session: Any):
        self._session = session

    async def send_audio(self, pcm: bytes) -> None:
        await self._session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={INPUT_RATE}"))

    async def send_text(self, text: str) -> None:
        await self._session.send_realtime_input(text=text)

    async def send_tool_results(self, results: list[ToolResult]) -> None:
        await self._session.send_tool_response(
            function_responses=[types.FunctionResponse(id=r.id, name=r.name, response=r.response) for r in results]
        )

    async def messages(self) -> AsyncIterator[Received]:
        # receive() ends after each model turn, so keep asking; a pass with no messages means the socket closed.
        try:
            while True:
                seen = False
                async for msg in self._session.receive():
                    seen = True
                    yield Received(_events(msg), _raw(msg))
                if not seen:
                    raise ModelClosed("model connection closed")
        except ModelClosed:
            raise
        except Exception as exc:
            raise ModelClosed(f"{type(exc).__name__}") from exc


class GeminiConnector:
    def __init__(self, settings: VoiceSettings):
        self._settings = settings

    @asynccontextmanager
    async def connect(self, agent: dict, fields: list[dict], resume_handle: str | None = None):
        client = genai.Client(
            vertexai=True, project=self._settings.gcp_project or None, location=self._settings.gcp_location
        )
        async with client.aio.live.connect(
            model=agent["model"], config=build_config(agent, fields, resume_handle)
        ) as session:
            yield GeminiSession(session)
