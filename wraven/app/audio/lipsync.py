"""BOILERPLATE (crow): Raven's body and sound. No need to edit it to build an agent.

Plays a sound through the crow's speaker while the beak follows its loudness."""
import time

import numpy as np

import settings
from audio.speaker import SPEAKER_RATE, resample, speaker


def beak_envelope(samples, rate):
    """How loud the audio is, LIPSYNC_FPS times a second, as beak percent 0-100."""
    hop = rate // settings.LIPSYNC_FPS
    frames = len(samples) // hop
    if frames == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(samples[:frames * hop].reshape(frames, hop) ** 2, axis=1))
    loudest = np.percentile(rms, 95)
    if loudest <= 0:
        return np.zeros(frames)
    level = np.clip(rms / loudest, 0, 1)
    level[level < settings.BEAK_GATE] = 0
    return level ** 0.7 * settings.BEAK_MAX_OPEN


def play(nano, samples, rate):
    """Play audio with lip sync. `nano` is anything with a beak(percent) method.
    Returns the Clip; it ends early (clip.stopped) if someone interrupts."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = resample(samples.astype(np.float32), rate, SPEAKER_RATE)
    envelope = beak_envelope(samples, SPEAKER_RATE)
    frame_s = 1 / settings.LIPSYNC_FPS

    out = speaker()
    clip = out.start(samples * settings.SPEAKER_VOLUME)
    clip.started.wait(timeout=2)
    last_value, last_sent = None, 0.0
    while not clip.stopped and clip.started_at is not None:
        now = time.monotonic()
        frame = int((now - clip.started_at - out.latency + settings.LIPSYNC_LEAD_S) / frame_s)
        if frame >= len(envelope):
            break
        if frame >= 0:
            value = int(envelope[frame])
            # Resend now and then: the Nano closes the beak if it hears nothing
            if value != last_value or now - last_sent > 0.2:
                nano.beak(value)
                last_value, last_sent = value, now
        time.sleep(frame_s / 2)
    clip.finished.wait(timeout=2)
    nano.beak(0)
    return clip
