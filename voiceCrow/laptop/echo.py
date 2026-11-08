"""
Acoustic echo cancellation: removes the crow's own voice from the microphone,
the way video calls stop you hearing yourself.

Everything the crow plays is handed in as the "reference". WebRTC's echo
canceller (the one in Chrome and Google Meet) learns how that sound reaches
the mic, with its delay, loudness and room echo, and subtracts it. What's
left is mostly your voice.

The speaker and mic both run at 16 kHz, so the reference is an exact copy of
what was played.
"""
import queue
import threading

import numpy as np
from livekit import rtc

RATE = 16000
FRAME = 160  # 10 ms, the size WebRTC works in


class EchoCanceller:
    def __init__(self, noise_suppression=False):
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True,
                                             noise_suppression=noise_suppression)
        self.lock = threading.Lock()  # the speaker and mic threads both use it
        self.delay_ms = 50            # speaker + mic latency; updated once both are open
        self.reference = queue.SimpleQueue()
        threading.Thread(target=self._feed_reference, daemon=True).start()

    def add_reference(self, samples):
        """Everything the speaker plays (float32, 16 kHz), silence included.
        Called from the audio output callback, so it only queues."""
        self.reference.put(samples)

    def clean(self, pcm16):
        """Remove the crow's echo from mic audio: 16 kHz, 16-bit, a multiple of 10 ms."""
        cleaned = bytearray()
        for i in range(0, len(pcm16) - FRAME * 2 + 1, FRAME * 2):
            frame = rtc.AudioFrame(bytearray(pcm16[i:i + FRAME * 2]), RATE, 1, FRAME)
            with self.lock:
                self.apm.set_stream_delay_ms(self.delay_ms)
                self.apm.process_stream(frame)  # cleans the frame in place
            cleaned += frame.data.tobytes()
        return bytes(cleaned)

    def _feed_reference(self):
        pending = np.zeros(0, dtype=np.float32)
        while True:
            pending = np.concatenate([pending, self.reference.get()])
            while len(pending) >= FRAME:
                ten_ms, pending = pending[:FRAME], pending[FRAME:]
                pcm16 = (np.clip(ten_ms, -1, 1) * 32767).astype(np.int16).tobytes()
                with self.lock:
                    self.apm.process_reverse_stream(rtc.AudioFrame(bytearray(pcm16), RATE, 1, FRAME))
