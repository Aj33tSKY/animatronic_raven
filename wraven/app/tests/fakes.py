"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

Stand-ins for the sound card, the Arduino, Dialog-RSN-1 and Wren."""
import asyncio
import contextlib
import json
import threading
import time

import httpx
import numpy as np
import websockets

from hardware.nano import Nano


class FakeOutputStream:
    """Runs the speaker's callback in real time, silently. `played` keeps every block."""
    played = []

    def __init__(self, samplerate, channels, dtype, blocksize, device, callback):
        self.rate, self.block, self.callback, self.latency = samplerate, blocksize, callback, 0.02
        self.running = False

    def start(self):
        self.running = True

        def loop():
            next_at = time.monotonic()
            while self.running:
                out = np.zeros((self.block, 1), np.float32)
                self.callback(out, self.block, None, None)
                FakeOutputStream.played.append(out[:, 0].copy())
                next_at += self.block / self.rate
                time.sleep(max(0, next_at - time.monotonic()))
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.running = False

    close = stop


class FakeInputStream:
    """A mic that delivers a quiet 440 Hz tone in real time."""

    def __init__(self, samplerate, channels, dtype, blocksize, device, callback):
        self.rate, self.block, self.callback, self.latency, self.on = samplerate, blocksize, callback, 0.01, True

    def __enter__(self):
        def loop():
            next_at, n = time.monotonic(), 0
            while self.on:
                next_at += self.block / self.rate
                time.sleep(max(0, next_at - time.monotonic()))
                if not self.on:
                    break
                t = (np.arange(self.block) + n) / self.rate
                n += self.block
                self.callback((0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)[:, None],
                              self.block, None, None)
        threading.Thread(target=loop, daemon=True).start()
        return self

    def __exit__(self, *details):
        self.on = False


class RecordingNano(Nano):
    """A Nano with nothing plugged in that remembers every command sent."""

    def __init__(self):
        super().__init__(None)
        self.sent = []

    def send(self, command):
        self.sent.append((time.monotonic(), command))

    def commands(self, prefix):
        return [command for _, command in self.sent if command.startswith(prefix)]


@contextlib.asynccontextmanager
async def fake_dialog(script, port=8790):
    """A fake Dialog-RSN-1 server. `script(ws, received)` plays the server's side;
    `received` collects every event the client sends. Yields (url, received)."""
    received = []

    async def handler(ws):
        await ws.send(json.dumps({"type": "session.created"}))
        started = False
        async for raw in ws:
            event = json.loads(raw)
            received.append(event)
            if event["type"] == "session.update" and not started:
                started = True
                await ws.send(json.dumps({"type": "session.updated"}))
                asyncio.create_task(script(ws, received))
    async with websockets.serve(handler, "127.0.0.1", port):
        yield f"ws://127.0.0.1:{port}", received


async def server_reply(ws, reply_id, text, tool=None):
    """The server side of one reply: optional text, optional tool call, then done."""
    async def send(**event):
        await ws.send(json.dumps(event))
    await send(type="response.created", response={"id": reply_id})
    if text:
        await send(type="response.output_text.delta", delta=text)
        await send(type="response.output_text.done")
    if tool:
        name, arguments = tool
        await send(type="response.function_call_arguments.done", name=name,
                   call_id=f"call-{reply_id}", arguments=json.dumps(arguments))
    await send(type="response.done", response={"status": "completed"})


def wren_events(report, session="chat-1", gap=0.0, extra=()):
    """Wren's stream for a run, in its real event format, ending in a report."""
    events = list(extra) + [
        {"type": "message_end", "depth": 0, "sessionId": session, "message": {"content": [
            {"type": "toolCall", "name": "submit_report", "arguments": {"title": "Done", "report": report}}]}},
        {"type": "complete", "depth": 0, "suspended": False, "sessionId": session}]

    async def body():
        for event in events:
            if gap:
                await asyncio.sleep(gap)
            yield ("data: " + json.dumps(event) + "\n\n").encode()
    return httpx.Response(200, content=body())


def wren_client(handler):
    return httpx.AsyncClient(base_url="https://wren.test", transport=httpx.MockTransport(handler))
