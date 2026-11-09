"""
The crow's speaker: one continuous output stream that plays one sound at a time
and can be stopped part-way (when someone interrupts). Everything that comes out,
silence included, is also passed to `on_output`; that's the echo canceller's
reference copy.
"""
import threading
import time

import numpy as np
import sounddevice as sd

import settings

# Echo cancellation needs the speaker at the mic's rate: 16 kHz, phone-call
# quality, which is plenty for a 40mm speaker. Without it, play at 24 kHz.
SPEAKER_RATE = 16000 if settings.ECHO_MODE == "cancel" else 24000
SPEAKER_BLOCK = SPEAKER_RATE // 50  # 20 ms


class Clip:
    """One sound being played, such as a sentence or a squawk."""

    def __init__(self, samples):
        self.samples = samples
        self.position = 0                   # samples handed to the sound card so far
        self.started_at = None              # when its first sample went out
        self.started = threading.Event()
        self.finished = threading.Event()   # played to the end, or stopped
        self.stopped = False                # cut short by Speaker.stop()

    @property
    def played_ms(self):
        return self.position * 1000 // SPEAKER_RATE

    @property
    def length_ms(self):
        return len(self.samples) * 1000 // SPEAKER_RATE


class Speaker:
    def __init__(self):
        self.lock = threading.Lock()
        self.clip = None
        self.on_output = None
        self.quiet_since = 0.0
        def open_stream(device):
            return sd.OutputStream(samplerate=SPEAKER_RATE, channels=1, dtype="float32",
                                   blocksize=SPEAKER_BLOCK, device=device, callback=self._fill)
        try:
            self.stream = open_stream(settings.OUTPUT_DEVICE)
        except ValueError as error:  # e.g. the amp's cable isn't plugged in
            print(f"[speaker] {error}. Using the default output instead: plug in the amp, "
                  "or change OUTPUT_DEVICE in settings.py (see --list-devices)")
            self.stream = open_stream(None)
        self.stream.start()

    @property
    def latency(self):
        """Seconds between a sample being handed over and it leaving the speaker."""
        return self.stream.latency

    def start(self, samples):
        clip = Clip(samples)
        with self.lock:
            if self.clip:
                self._end(self.clip, stopped=True)
            self.clip = clip
        return clip

    def stop(self):
        """Cut off whatever is playing. Returns that clip, or None."""
        with self.lock:
            clip = self.clip
            if clip:
                self._end(clip, stopped=True)
        return clip

    def seconds_quiet(self):
        """How long nothing has been playing (0 while something is)."""
        with self.lock:
            return 0.0 if self.clip else time.monotonic() - self.quiet_since

    def _end(self, clip, stopped):  # call with the lock held
        clip.stopped = stopped
        self.clip = None
        self.quiet_since = time.monotonic()
        clip.started.set()  # wake anyone still waiting for it to begin
        clip.finished.set()

    def _fill(self, outdata, frames, time_info, status):
        out = np.zeros(frames, dtype=np.float32)
        with self.lock:
            clip = self.clip
            if clip:
                chunk = clip.samples[clip.position:clip.position + frames]
                out[:len(chunk)] = chunk
                if clip.position == 0:
                    clip.started_at = time.monotonic()
                    clip.started.set()
                clip.position += len(chunk)
                if clip.position >= len(clip.samples):
                    self._end(clip, stopped=False)
        outdata[:, 0] = out
        if self.on_output:
            self.on_output(out)


_speaker = None


def speaker():
    """The crow's speaker, opened the first time it's needed."""
    global _speaker
    if _speaker is None:
        _speaker = Speaker()
    return _speaker


def stop_sound():
    """Cut off anything the crow is playing (if the speaker was ever opened)."""
    if _speaker:
        _speaker.stop()


def seconds_since_sound():
    """How long the crow's speaker has been quiet (0 while it's playing)."""
    return speaker().seconds_quiet()


def resample(samples, rate, new_rate):
    """Change a whole sound's sample rate (e.g. a 44.1 kHz squawk to the speaker's rate)."""
    if rate == new_rate:
        return samples
    if new_rate < rate:  # smooth first, so high pitches don't fold back as noise
        width = int(np.ceil(rate / new_rate))
        samples = np.convolve(samples, np.ones(width) / width, mode="same")
    count = int(round(len(samples) * new_rate / rate))
    return np.interp(np.arange(count) * rate / new_rate, np.arange(len(samples)),
                     samples).astype(np.float32)
