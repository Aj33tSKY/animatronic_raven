"""Echo cancellation removes a delayed, quieter copy of what was played."""
import numpy as np
import pytest

pytest.importorskip("livekit")
from livekit import rtc  # noqa: E402

RATE, FRAME = 16000, 160


def speech_like(seconds, seed):
    """Noise shaped into syllables: close enough to speech for the canceller."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(RATE * seconds)) / RATE
    envelope = (np.sin(2 * np.pi * 3 * t) > 0) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
    return (np.convolve(rng.normal(0, 0.3, len(t)), np.ones(8) / 8, "same") * envelope).astype(np.float32)


def test_echo_is_removed():
    played = speech_like(6, seed=1)
    delay = int(0.07 * RATE)
    mic = 0.5 * np.concatenate([np.zeros(delay), played])[:len(played)]
    apm = rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True)
    pcm = lambda x: bytearray((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    out = []
    for i in range(0, len(played) - FRAME + 1, FRAME):
        apm.process_reverse_stream(rtc.AudioFrame(pcm(played[i:i + FRAME]), RATE, 1, FRAME))
        frame = rtc.AudioFrame(pcm(mic[i:i + FRAME]), RATE, 1, FRAME)
        apm.set_stream_delay_ms(70)
        apm.process_stream(frame)
        out.append(np.frombuffer(frame.data, np.int16).astype(np.float32) / 32767)
    out = np.concatenate(out)
    level = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
    later = slice(2 * RATE, 6 * RATE)  # after it has learned the room
    assert level(mic[later]) - level(out[later]) > 15
