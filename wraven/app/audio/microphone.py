"""BOILERPLATE (crow): Raven's body and sound. No need to edit it to build an agent.

The microphone, as 16-bit, 16 kHz blocks you can await one at a time."""
import asyncio

import numpy as np
import sounddevice as sd

import settings

MIC_RATE = 16000  # what Dialog-RSN-1 is given


class Microphone:
    """Use as `with Microphone(block) as mic:` then `await mic.read()`."""

    def __init__(self, block):
        self.block = block
        self.frames = asyncio.Queue()
        self.stream = None

    def __enter__(self):
        loop = asyncio.get_running_loop()

        def callback(indata, frame_count, time_info, status):
            pcm16 = (np.clip(indata[:, 0], -1, 1) * 32767).astype(np.int16).tobytes()
            try:
                loop.call_soon_threadsafe(self.frames.put_nowait, pcm16)
            except RuntimeError:
                pass  # the conversation has just ended

        def open_stream(device):
            return sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32",
                                  blocksize=self.block, device=device, callback=callback)
        try:
            self.stream = open_stream(settings.INPUT_DEVICE)
        except ValueError as error:  # e.g. that mic isn't plugged in
            print(f"[mic] {error}. Using the default mic instead: change INPUT_DEVICE in "
                  "settings.py (see --list-devices)")
            self.stream = open_stream(None)
        self.stream.__enter__()
        return self

    def __exit__(self, *details):
        self.stream.__exit__(*details)

    @property
    def latency(self):
        return self.stream.latency

    async def read(self):
        return await self.frames.get()
