"""What the call logic sees from a speech model, independent of the provider.

The Gemini adapter turns provider messages into these events, and tests use a fake
model that emits them directly. Audio is PCM16 mono: 16 kHz into the model, 24 kHz out.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

INPUT_RATE = 16_000
OUTPUT_RATE = 24_000


@dataclass(frozen=True)
class AudioOut:
    data: bytes


@dataclass(frozen=True)
class Transcript:
    speaker: Literal["caller", "agent"]
    text: str  # a fragment; fragments of one turn are joined by the call session


@dataclass(frozen=True)
class Interrupted:
    """The caller spoke over the agent: playback must stop now."""


@dataclass(frozen=True)
class TurnComplete:
    pass


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    data: dict[str, Any]


@dataclass(frozen=True)
class Resumable:
    handle: str


@dataclass(frozen=True)
class GoAway:
    """The provider will close this connection soon; reconnect with the resumption handle."""


ModelEvent = AudioOut | Transcript | Interrupted | TurnComplete | ToolCall | Usage | Resumable | GoAway


@dataclass
class Received:
    events: list[ModelEvent]
    raw: dict | None = None  # the provider message without audio bytes; None when it carried nothing else


class ModelClosed(Exception):
    """The model connection ended (normally or not)."""


@dataclass
class ToolResult:
    id: str
    name: str
    response: dict[str, Any] = field(default_factory=dict)


class ModelSession(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...

    async def send_text(self, text: str) -> None: ...

    async def send_tool_results(self, results: list[ToolResult]) -> None: ...

    def messages(self) -> AsyncIterator[Received]: ...


class ModelConnector(Protocol):
    """Opens a model session. ``resume_handle`` continues an earlier session after a reconnect."""

    def connect(self, agent: dict, fields: list[dict], resume_handle: str | None): ...  # async context manager
