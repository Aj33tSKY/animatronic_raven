"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The speaker: interruptible playback with lip sync, and a missing output device."""
import threading
import time

import numpy as np

import audio.speaker
from audio.lipsync import play
from tests import fakes


def test_a_sound_plays_with_lip_sync_and_can_be_cut_off(silent_audio, nano):
    rate = audio.speaker.SPEAKER_RATE
    tone = (0.3 * np.sin(np.arange(rate) / rate * 2 * np.pi * 220)).astype(np.float32)  # 1 s
    clip = play(nano, tone, rate)
    assert not clip.stopped and clip.played_ms == clip.length_ms
    assert max(int(c[1:]) for c in nano.commands("B")) > 50 and nano.commands("B")[-1] == "B0"

    threading.Timer(0.4, audio.speaker.stop_sound).start()
    started = time.monotonic()
    clip = play(nano, np.tile(tone, 3), rate)
    assert clip.stopped and time.monotonic() - started < 0.7 and clip.played_ms < 700


def test_missing_output_device_falls_back_to_the_default(monkeypatch, capsys):
    def output_stream(device=None, **settings):
        if device is not None:
            raise ValueError(f"No output device matching {device!r}")
        return fakes.FakeOutputStream(device=device, **settings)
    monkeypatch.setattr(audio.speaker.sd, "OutputStream", output_stream)
    monkeypatch.setattr(audio.speaker.settings, "OUTPUT_DEVICE", "External Headphones")
    monkeypatch.setattr(audio.speaker, "_speaker", None)
    speaker = audio.speaker.speaker()
    assert "Using the default output instead" in capsys.readouterr().out
    speaker.stream.stop()
