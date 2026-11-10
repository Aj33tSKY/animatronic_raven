"""
Text to speech: ElevenLabs, with the Mac's built-in `say` voice as a backup
(used if ElevenLabs fails, or if TTS_ENGINE = "say").
"""
import os
import subprocess
import tempfile
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

import settings

# One shared connection, so each sentence skips a fresh HTTPS handshake
client = httpx.Client(base_url="https://api.elevenlabs.io", timeout=30)


def synthesize(text, rate):
    """Turn text into (samples, rate) audio, at the speaker's sample rate."""
    if settings.TTS_ENGINE == "elevenlabs":
        try:
            return elevenlabs(text, rate)
        except (httpx.HTTPError, RuntimeError) as error:
            # Keep talking even if the service is down or out of credit
            print(f"[voice] ElevenLabs failed ({error}), using the Mac voice instead")
    return mac_say(text, rate)


def elevenlabs(text, rate):
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY isn't set")
    response = client.post(
        f"/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
        params={"output_format": f"pcm_{rate}"},  # raw PCM; 44.1 kHz needs a Pro plan
        headers={"xi-api-key": api_key},
        json={"text": text,
              "model_id": settings.ELEVENLABS_MODEL,
              "voice_settings": {"stability": settings.ELEVENLABS_STABILITY,
                                 "speed": settings.ELEVENLABS_SPEED}},
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    # 16-bit little-endian mono samples
    samples = np.frombuffer(response.content, dtype="<i2").astype(np.float32) / 32768
    return samples, rate


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
