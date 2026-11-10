"""
BOILERPLATE (crow): Raven's body and sound. No need to edit it to build an agent.

Raven's voice: text in, audio out. Tries, in order:

  1. ElevenLabs (integrations/elevenlabs.py): the best voice; needs credit
  2. Piper: a free voice that runs on this laptop, about 0.1 s per sentence
  3. the Mac's `say` voice: always there, but about 1.5 s per sentence

TTS_ENGINE in settings.py picks where to start. If ElevenLabs runs out of credit
mid-conversation, Raven switches to Piper for the rest of it, without retrying.
"""
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

import settings
from audio.speaker import resample
from integrations import elevenlabs

elevenlabs_off = None    # why ElevenLabs was switched off for this session, if it was
piper_voice = None
piper_lock = threading.Lock()


def synthesize(text, rate):
    """(samples, rate) for the text, at the speaker's sample rate."""
    global elevenlabs_off
    if settings.TTS_ENGINE == "elevenlabs" and not elevenlabs_off:
        try:
            return elevenlabs.synthesize(text, rate)
        except elevenlabs.OutOfService as error:
            elevenlabs_off = str(error)
            print(f"[voice] ElevenLabs is unavailable ({error}); using the "
                  f"{settings.PIPER_VOICE} voice for the rest of this conversation")
        except Exception as error:  # a one-off network problem: fall back just this once
            print(f"[voice] ElevenLabs failed ({error}); using the backup voice for this sentence")
    if settings.TTS_ENGINE in ("elevenlabs", "piper"):
        try:
            return piper(text, rate)
        except Exception as error:
            print(f"[voice] Piper failed ({error}); using the Mac voice")
    return mac_say(text, rate)


def load_piper():
    """Load the Piper voice (downloading it the first time, about 60 MB). Takes ~2 s,
    so the session calls this in the background at start-up."""
    global piper_voice
    with piper_lock:
        if piper_voice is None:
            from piper import PiperVoice
            from piper.download_voices import download_voice
            model = settings.PIPER_VOICES_DIR / f"{settings.PIPER_VOICE}.onnx"
            if not model.exists():
                print(f"[voice] downloading the {settings.PIPER_VOICE} voice (once, about 60 MB)")
                settings.PIPER_VOICES_DIR.mkdir(exist_ok=True)
                download_voice(settings.PIPER_VOICE, settings.PIPER_VOICES_DIR)
            piper_voice = PiperVoice.load(model)
    return piper_voice


def prepare():
    """Get the backup voice ready, so switching to it doesn't pause Raven."""
    if settings.TTS_ENGINE in ("elevenlabs", "piper"):
        try:
            load_piper()
        except Exception as error:
            print(f"[voice] the Piper voice isn't available ({error}); the backup is the Mac voice")


def piper(text, rate):
    from piper import SynthesisConfig
    voice = load_piper()
    config = SynthesisConfig(length_scale=1 / settings.PIPER_SPEED)
    chunks = list(voice.synthesize(text, syn_config=config))
    if not chunks:
        return np.zeros(0, dtype=np.float32), rate
    samples = np.concatenate([chunk.audio_float_array for chunk in chunks]).astype(np.float32)
    return resample(samples, chunks[0].sample_rate, rate), rate


def mac_say(text, rate):
    """The macOS `say` command (Mac only)."""
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "speech.txt"
        wav_file = Path(tmp) / "speech.wav"
        text_file.write_text(text)
        subprocess.run(["say", "-v", settings.MAC_VOICE, "-r", str(settings.MAC_VOICE_RATE),
                        "--file-format=WAVE", f"--data-format=LEI16@{rate}",
                        "-o", str(wav_file), "-f", str(text_file)], check=True)
        samples, sample_rate = sf.read(wav_file, dtype="float32")
    return samples, sample_rate
