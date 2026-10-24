"""The audio of one call, kept in memory until the call ends, then written as a stereo WAV.

Caller on the left, agent on the right, both 16 kHz PCM16, laid out on the call's clock so the two sides line
up as they were heard. The agent's model produces audio faster than real time, so each chunk is placed where
it would have played: after the previous chunk, or now if the agent had gone quiet. When the caller interrupts,
what had not yet played is cut, because the caller never heard it.
"""

import io
import sys
import wave
from array import array

from clinic_voice_receptionist.inbound.live.events import INPUT_RATE, OUTPUT_RATE

RATE = INPUT_RATE  # the saved file's sample rate; caller audio already arrives at this rate
LAG_SAMPLES = RATE // 4  # a gap this long in the caller's audio is real silence, not jitter


def _samples(pcm: bytes) -> array:
    out = array("h")
    out.frombytes(pcm)
    if sys.byteorder == "big":
        out.byteswap()
    return out


def _resample_24k_to_16k(samples: array) -> array:
    """Three input samples become two: the first, and the midpoint of the other two. Speech-grade, cheap."""
    groups = len(samples) // 3
    first, second, third = samples[0 : groups * 3 : 3], samples[1 : groups * 3 : 3], samples[2 : groups * 3 : 3]
    out = array("h", bytes(4 * groups))
    out[0::2] = first
    out[1::2] = array("h", ((b + c) >> 1 for b, c in zip(second, third, strict=True)))
    return out


class CallAudio:
    def __init__(self, max_seconds: int):
        self._limit = max_seconds * RATE
        self._caller = array("h")
        self._agent = array("h")
        self._agent_carry = array("h")  # input samples left over from the last chunk (24 kHz groups of three)

    @property
    def seconds(self) -> float:
        return max(len(self._caller), len(self._agent)) / RATE

    def caller(self, pcm: bytes, elapsed: float) -> None:
        """Audio from the caller (16 kHz). ``elapsed`` is the call clock in seconds when it arrived."""
        samples = _samples(pcm)
        behind = int(elapsed * RATE) - len(samples) - len(self._caller)
        if behind > LAG_SAMPLES:
            self._caller.extend(array("h", bytes(2 * behind)))
        if len(self._caller) + len(samples) <= self._limit:
            self._caller.extend(samples)

    def agent(self, pcm: bytes, elapsed: float) -> None:
        """Audio from the agent (24 kHz), placed after what is still playing, or at ``elapsed`` if it was quiet."""
        samples = self._agent_carry + _samples(pcm)
        usable = len(samples) // 3 * 3
        self._agent_carry = samples[usable:]
        converted = _resample_24k_to_16k(samples[:usable])
        now = int(elapsed * RATE)
        if now > len(self._agent):
            self._agent.extend(array("h", bytes(2 * (now - len(self._agent)))))
        if len(self._agent) + len(converted) <= self._limit:
            self._agent.extend(converted)

    def interrupt(self, elapsed: float) -> None:
        """The caller spoke over the agent: drop agent audio that was queued but not yet played."""
        del self._agent[max(0, int(elapsed * RATE)) :]
        self._agent_carry = array("h")

    def to_wav(self) -> bytes:
        length = max(len(self._caller), len(self._agent))
        stereo = array("h", bytes(4 * length))
        stereo[0 : 2 * len(self._caller) : 2] = self._caller
        stereo[1 : 2 * len(self._agent) : 2] = self._agent
        if sys.byteorder == "big":
            stereo.byteswap()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(stereo.tobytes())
        return buffer.getvalue()


assert OUTPUT_RATE == 24_000 and INPUT_RATE == 16_000  # the 3:2 conversion above depends on these
