"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The voice falls back from ElevenLabs to Piper to the Mac voice."""
import numpy as np

import settings
from audio import voice
from integrations import elevenlabs


def fakes(monkeypatch, eleven_error=None, piper_error=None):
    calls = []

    def fake_eleven(text, rate):
        calls.append("elevenlabs")
        if eleven_error:
            raise eleven_error
        return np.zeros(10, np.float32), rate

    def fake_piper(text, rate):
        calls.append("piper")
        if piper_error:
            raise piper_error
        return np.zeros(10, np.float32), rate

    monkeypatch.setattr(settings, "TTS_ENGINE", "elevenlabs")
    monkeypatch.setattr(voice, "elevenlabs_off", None)
    monkeypatch.setattr(elevenlabs, "synthesize", fake_eleven)
    monkeypatch.setattr(voice, "piper", fake_piper)
    monkeypatch.setattr(voice, "mac_say", lambda text, rate: (calls.append("say"), (np.zeros(10), rate))[1])
    return calls


def test_out_of_credit_switches_to_piper_for_the_rest_of_the_session(monkeypatch):
    calls = fakes(monkeypatch, eleven_error=elevenlabs.OutOfService("HTTP 401: quota_exceeded"))
    voice.synthesize("One.", 16000)
    voice.synthesize("Two.", 16000)
    assert calls == ["elevenlabs", "piper", "piper"]  # ElevenLabs isn't retried


def test_a_one_off_failure_falls_back_only_for_that_sentence(monkeypatch):
    calls = fakes(monkeypatch, eleven_error=RuntimeError("HTTP 500"))
    voice.synthesize("One.", 16000)
    voice.synthesize("Two.", 16000)
    assert calls == ["elevenlabs", "piper", "elevenlabs", "piper"]


def test_mac_voice_is_the_last_resort(monkeypatch):
    calls = fakes(monkeypatch, eleven_error=RuntimeError("down"), piper_error=RuntimeError("missing"))
    voice.synthesize("One.", 16000)
    assert calls == ["elevenlabs", "piper", "say"]
