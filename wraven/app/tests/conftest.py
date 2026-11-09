"""
Shared test setup. Run everything from the app folder with:   python -m pytest

Nothing here makes a sound, touches the Arduino, or calls PolyAI, Wren or
ElevenLabs: the speaker and mic are silent fakes, and the services are faked.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import fakes  # noqa: E402


@pytest.fixture
def silent_audio(monkeypatch):
    """A fake speaker and mic that run in real time without any sound."""
    import audio.microphone
    import audio.speaker
    monkeypatch.setattr(audio.speaker.sd, "OutputStream", fakes.FakeOutputStream)
    monkeypatch.setattr(audio.microphone.sd, "InputStream", fakes.FakeInputStream)
    monkeypatch.setattr(audio.speaker, "_speaker", None)
    fakes.FakeOutputStream.played.clear()
    yield
    if audio.speaker._speaker:
        audio.speaker._speaker.stream.stop()


@pytest.fixture
def fake_voice(monkeypatch):
    """Text to speech that returns `seconds` of quiet audio per sentence, instantly."""
    import conversation_runtime.performer as performer
    said = []

    def synthesize(text, rate, seconds=0.3):
        said.append(text)
        return np.full(int(rate * seconds), 0.05, np.float32), rate
    monkeypatch.setattr(performer, "synthesize", synthesize)
    return said


@pytest.fixture
def nano():
    return fakes.RecordingNano()
