"""A scripted stand-in for the speech model, for browser tests and demos that must not call Vertex.

It greets with a short tone, then answers the first second of caller audio by "hearing" a caller who
gives their details, saving every capture field through the same function call a real model makes and
creating a lead when the agent has that tool.
"""

import asyncio
import math
import random
import struct
import uuid
from contextlib import asynccontextmanager

from clinic_voice_receptionist.inbound.live.events import (
    OUTPUT_RATE,
    AudioOut,
    Received,
    ToolCall,
    Transcript,
    TurnComplete,
)

CALLER_SAYS = "Hi, I'm Sam Lee and my number is +1 415 555 0123."
SAMPLES = {"phone": "+14155550123", "email": "sam@example.com", "date": "1990-02-03", "number": 3, "boolean": True}


def tone(seconds: float = 0.4, hz: int = 440) -> bytes:
    n = int(OUTPUT_RATE * seconds)
    return b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * hz * i / OUTPUT_RATE))) for i in range(n))


class ScriptedModel:
    FRAMES_BEFORE_REPLY = 10  # 200 ms of caller audio

    def __init__(self, fields: list[dict], tools: list[dict] | None = None):
        self.fields = fields
        self.tool_names = {t["name"] for t in tools or []}
        self.inbox: asyncio.Queue[Received] = asyncio.Queue()
        self._frames = 0

    def _say(self, speaker: str, text: str) -> None:
        self.inbox.put_nowait(Received([Transcript(speaker, text)]))

    async def send_text(self, text: str) -> None:
        greeting = text.split('"')[1] if '"' in text else "Hello."
        self._say("agent", greeting)
        self.inbox.put_nowait(Received([AudioOut(tone())]))
        self.inbox.put_nowait(Received([TurnComplete()], raw={"server_content": {"turn_complete": True}}))

    async def send_audio(self, pcm: bytes) -> None:
        self._frames += 1
        if self._frames != self.FRAMES_BEFORE_REPLY:
            return
        self._say("caller", CALLER_SAYS)
        args = {
            f["key"]: f["enum_values"][0] if f["data_type"] == "enum" else SAMPLES.get(f["data_type"], "Sam Lee")
            for f in self.fields
        }
        if args:
            self.inbox.put_nowait(Received([ToolCall("scripted-1", "save_caller_details", args)]))
        if "create_lead" in self.tool_names:
            lead = {"first_name": "Sam", "last_name": "Lee", "phone": SAMPLES["phone"], "interest": "Botox"}
            self.inbox.put_nowait(Received([ToolCall("scripted-2", "create_lead", lead)]))
        self._say("agent", "Thanks Sam, I have your details.")
        self.inbox.put_nowait(Received([AudioOut(tone(hz=660))]))
        self.inbox.put_nowait(Received([TurnComplete()], raw={"server_content": {"turn_complete": True}}))

    async def send_tool_results(self, results) -> None:
        pass

    async def messages(self):
        while True:
            yield await self.inbox.get()


class MemoryRecordingStore:
    """Recordings kept in memory, so browser tests can record and play back without a bucket."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes) -> None:
        self.objects[name] = data

    async def get(self, name: str) -> bytes | None:
        return self.objects.get(name)


class ScriptedConnector:
    @asynccontextmanager
    async def connect(self, agent: dict, fields: list[dict], resume_handle: str | None = None):
        yield ScriptedModel(fields, agent.get("tools"))


class FakeNumbers:
    """A stand-in for Twilio's number API, for tests and browser tests that must not buy real numbers."""

    def __init__(self) -> None:
        self.owned: dict[str, str] = {}  # sid -> number
        self.urls: dict[str, str] = {}  # sid -> the address its incoming calls go to
        self.fail_next_buy: str | None = None
        self.recover_next_buy = False  # answer the next buy as a number that was already on the account
        self.calls: list[tuple] = []

    async def search(self, *, kind, area_code, contains, limit=10):
        from clinic_voice_receptionist.numbers.twilio import AvailableNumber

        self.calls.append(("search", kind, area_code, contains))
        prefix = "+1800555" if kind == "toll_free" else f"+1{area_code or '415'}555"
        # Random line numbers, because a number can belong to one clinic only and test databases keep their rows.
        lines = random.sample(range(10000), 3)
        return [AvailableNumber(f"{prefix}{line:04d}", "Sample City", "CA", kind) for line in lines]

    async def buy(self, *, number, friendly_name, voice_url):
        from clinic_voice_receptionist.numbers.twilio import PurchasedNumber, TwilioError

        self.calls.append(("buy", number, voice_url))
        if self.fail_next_buy:
            message, self.fail_next_buy = self.fail_next_buy, None
            raise TwilioError(message, 409)
        if self.recover_next_buy:
            self.recover_next_buy = False
            sid = next(sid for sid, owned in self.owned.items() if owned == number)
            return PurchasedNumber(sid, number, recovered=True)
        sid = f"PN{uuid.uuid4().hex}"
        self.owned[sid] = number
        self.urls[sid] = voice_url or ""
        return PurchasedNumber(sid, number)

    async def list_voice_urls(self):
        self.calls.append(("list_voice_urls",))
        return dict(self.urls)

    async def set_voice_url(self, sid, voice_url):
        self.calls.append(("set_voice_url", sid, voice_url))
        self.urls[sid] = voice_url
        if self.fail_next_buy:  # reused to simulate Twilio refusing any change
            message, self.fail_next_buy = self.fail_next_buy, None
            from clinic_voice_receptionist.numbers.twilio import TwilioError

            raise TwilioError(message, 409)

    async def release(self, sid):
        self.calls.append(("release", sid))
        self.owned.pop(sid, None)


async def scripted_voice_preview(settings, *, text: str, voice: str, language: str) -> bytes:
    """Test-only audio; browsers exercise the real route without any Vertex requests."""
    from clinic_voice_receptionist.voice_preview.service import wav_bytes

    return wav_bytes(tone(1))
