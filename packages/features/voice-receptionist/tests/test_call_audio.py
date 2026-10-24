"""How a call's audio is laid out in the saved WAV. Pure functions: no database, no network."""

import io
import wave
from array import array

from clinic_voice_receptionist.inbound.live.audio import RATE, CallAudio


def pcm(values):
    return array("h", values).tobytes()


def read(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        frames = array("h")
        frames.frombytes(wav.readframes(wav.getnframes()))
        return wav.getnchannels(), wav.getframerate(), wav.getsampwidth(), frames[0::2], frames[1::2]


def test_caller_is_the_left_channel_and_agent_the_right_at_16_khz():
    audio = CallAudio(60)
    audio.caller(pcm([100] * RATE), elapsed=1.0)  # one second of caller audio, arriving at the one second mark
    audio.agent(pcm([200] * 24_000), elapsed=0.0)  # one second of agent audio at 24 kHz
    channels, rate, width, left, right = read(audio.to_wav())
    assert (channels, rate, width) == (2, 16_000, 2)
    assert len(left) == len(right) == 16_000
    assert set(left) == {100} and set(right) == {200}  # constant audio stays constant through resampling


def test_agent_audio_arriving_in_a_burst_is_laid_out_one_chunk_after_another():
    audio = CallAudio(60)
    audio.agent(pcm([1] * 24_000), elapsed=0.0)  # one second
    audio.agent(pcm([2] * 24_000), elapsed=0.1)  # arrives early: plays after the first, not on top of it
    _, _, _, _, right = read(audio.to_wav())
    assert len(right) == 32_000
    assert set(right[:16_000]) == {1} and set(right[16_000:]) == {2}


def test_quiet_gaps_become_silence():
    audio = CallAudio(60)
    audio.agent(pcm([5] * 2_400), elapsed=0.0)
    audio.agent(pcm([6] * 2_400), elapsed=2.0)  # the agent had been quiet for most of two seconds
    _, _, _, _, right = read(audio.to_wav())
    assert right[2_000] == 0 and right[2 * RATE] == 6


def test_an_interruption_cuts_audio_that_had_not_played_yet():
    audio = CallAudio(60)
    audio.agent(pcm([7] * 72_000), elapsed=0.0)  # three seconds queued at once
    audio.interrupt(elapsed=1.0)  # the caller spoke after one second
    _, _, _, _, right = read(audio.to_wav())
    assert len(right) == RATE


def test_chunks_that_do_not_divide_evenly_lose_no_audio():
    whole = CallAudio(60)
    whole.agent(pcm(range(3_000)), elapsed=0.0)
    pieces = CallAudio(60)
    for start, stop in ((0, 1_000), (1_000, 1_001), (1_001, 3_000)):  # splits fall inside groups of three
        pieces.agent(pcm(range(start, stop)), elapsed=0.0)
    assert read(whole.to_wav())[4] == read(pieces.to_wav())[4]


def test_a_gap_in_the_callers_audio_is_kept_but_small_jitter_is_not():
    audio = CallAudio(60)
    audio.caller(pcm([3] * 1_600), elapsed=0.1)
    audio.caller(pcm([3] * 1_600), elapsed=0.21)  # normal spacing, no padding
    audio.caller(pcm([4] * 1_600), elapsed=3.0)  # three seconds in: the caller's audio went missing for a while
    _, _, _, left, _ = read(audio.to_wav())
    assert len(left) == 3 * RATE
    assert left[3_200] == 0 and left[-1] == 4


def test_audio_beyond_the_call_limit_is_not_kept():
    audio = CallAudio(1)
    audio.caller(pcm([1] * RATE), elapsed=1.0)
    audio.caller(pcm([1] * RATE), elapsed=2.0)
    audio.agent(pcm([1] * 48_000), elapsed=0.0)
    assert audio.seconds == 1.0
