"""BOILERPLATE: Dialog-RSN-1 plumbing, the same for any agent. No need to edit it to build one.

ElevenLabs text to speech. Which voice is used, and the fallbacks, are in audio/voice.py."""
import os

import httpx
import numpy as np

import settings

# One shared connection, so each sentence skips a fresh HTTPS handshake
client = httpx.Client(base_url="https://api.elevenlabs.io", timeout=30)


class OutOfService(RuntimeError):
    """ElevenLabs won't speak for us this session: no key, out of credit, or key refused."""


def synthesize(text, rate):
    """(samples, rate) for the text, at the given sample rate."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise OutOfService("ELEVENLABS_API_KEY isn't set")
    response = client.post(
        f"/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
        params={"output_format": f"pcm_{rate}"},  # raw PCM; 44.1 kHz needs a Pro plan
        headers={"xi-api-key": api_key},
        json={"text": text,
              "model_id": settings.ELEVENLABS_MODEL,
              "voice_settings": {"stability": settings.ELEVENLABS_STABILITY,
                                 "speed": settings.ELEVENLABS_SPEED}},
    )
    if response.status_code in (401, 402):  # out of credit, or the key/plan was refused
        raise OutOfService(f"HTTP {response.status_code}: {response.text[:160]}")
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:160]}")
    # 16-bit little-endian mono samples
    samples = np.frombuffer(response.content, dtype="<i2").astype(np.float32) / 32768
    return samples, rate
