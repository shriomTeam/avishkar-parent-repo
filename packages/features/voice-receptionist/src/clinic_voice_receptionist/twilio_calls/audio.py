"""Phone audio. Twilio carries 8 kHz mu-law; the call engine takes 16 kHz PCM16 in and gives 24 kHz PCM16 out.

Written without ``audioop`` (removed in Python 3.13). Each conversion is a table lookup or a short average, cheap
enough for 20 ms frames. The resampling is deliberately simple (a phone line only carries up to 4 kHz anyway).
"""

from array import array


def _decode_one(byte: int) -> int:
    byte = ~byte & 0xFF
    t = (((byte & 0x0F) << 3) + 0x84) << ((byte & 0x70) >> 4)
    return (0x84 - t) if byte & 0x80 else (t - 0x84)


def _encode_one(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    sample = min(abs(sample), 32635) + 0x84
    exponent, mask = 7, 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


_DECODE = array("h", (_decode_one(b) for b in range(256)))
_ENCODE = bytes(_encode_one(s) for s in range(-32768, 32768))
SILENCE = 0xFF  # mu-law zero


def _pcm(data: bytes) -> array:
    samples = array("h")
    samples.frombytes(data[: len(data) - len(data) % 2])
    return samples


def mulaw_to_pcm(data: bytes) -> array:
    return array("h", (_DECODE[b] for b in data))


def pcm_to_mulaw(samples) -> bytes:
    return bytes(_ENCODE[s + 32768] for s in samples)


def upsample_8k_to_16k(samples: array) -> array:
    """Each sample is followed by the midpoint to the next one."""
    out = array("h", bytes(len(samples) * 4))
    last = len(samples) - 1
    for i, s in enumerate(samples):
        out[2 * i] = s
        out[2 * i + 1] = (s + samples[i + 1]) // 2 if i < last else s
    return out


def phone_to_model(mulaw: bytes) -> bytes:
    """One Twilio media payload (8 kHz mu-law) as PCM16 16 kHz, little-endian, for the model."""
    return upsample_8k_to_16k(mulaw_to_pcm(mulaw)).tobytes()


class ModelToPhone:
    """Turns the model's 24 kHz PCM16 into 8 kHz mu-law, three samples to one.

    Chunks from the model do not always hold a multiple of three samples, so the few left over wait for the next chunk.
    """

    def __init__(self) -> None:
        self._rest = array("h")

    def convert(self, pcm24k: bytes) -> bytes:
        samples = self._rest + _pcm(pcm24k)
        usable = len(samples) - len(samples) % 3
        self._rest = samples[usable:]
        averaged = array("h", ((samples[i] + samples[i + 1] + samples[i + 2]) // 3 for i in range(0, usable, 3)))
        return pcm_to_mulaw(averaged)

    def reset(self) -> None:
        self._rest = array("h")
