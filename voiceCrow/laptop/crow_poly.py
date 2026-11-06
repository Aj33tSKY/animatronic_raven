#!/usr/bin/env python3
"""
Talking crow on PolyAI's Dialog-RSN-1.

Dialog-RSN-1 listens to the microphone directly: it hears when you start and
stop talking, understands you, and answers in text. The crow speaks that text
through its own speaker (same voice and lip sync as crow.py), and moves when
the model calls its tools.

    python crow_poly.py                    talk to the crow
    python crow_poly.py --no-crow          run without the Arduino plugged in
    python crow_poly.py --say "Hello"      one typed turn, no mic (checks your key)

Needs POLY_API_KEY in the environment. Settings live in config.py.
"""
import argparse
import asyncio
import base64
import json
import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import sounddevice as sd
import websockets
from websockets.exceptions import InvalidStatus

import config
from crow import (EYES_AWAKE, EYES_LISTENING, EYES_TALKING, EYES_THINKING,
                  Body, Crow, find_nano_port, play, synthesize)

MIC_RATE = 16000
MIC_BLOCK = 512   # 32 ms, the frame size Dialog-RSN-1's turn detector works in

# Replies can start with an emotion tag, e.g. "[amused] Well, well."
EMOTION_TAG = re.compile(r"^\s*\[(\w+)\]\s*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

TOOLS = [
    {"type": "function", "name": "caw",
     "description": "Let out a crow call through your speaker. 'squawk' is a short caw; "
                    "'scold' is an angry, scolding cry with a jerk of the head.",
     "parameters": {"type": "object",
                    "properties": {"kind": {"type": "string", "enum": ["squawk", "scold"]}},
                    "required": ["kind"]}},
    {"type": "function", "name": "turn_head",
     "description": "Turn your head to look left, right, or back at the person (center).",
     "parameters": {"type": "object",
                    "properties": {"direction": {"type": "string",
                                                 "enum": ["left", "right", "center"]}},
                    "required": ["direction"]}},
    {"type": "function", "name": "shake_head",
     "description": "Shake your head, as in 'no'.",
     "parameters": {"type": "object", "properties": {}}},
]


def tool_to_move(name, args):
    """Map a tool call to one of Body.act's moves, or None if it isn't one."""
    if name == "caw" and args.get("kind") in ("squawk", "scold"):
        return args["kind"]
    if name == "turn_head":
        return {"left": "look left", "right": "look right",
                "center": "look at you"}.get(args.get("direction"))
    if name == "shake_head":
        return "shake"
    return None


# ============================================================================
# PERFORMER (speaks and moves, in order, on its own thread)
# ============================================================================

class Performer:
    """Queues speech and moves so the connection never waits on the crow.
    Each sentence's audio starts being made as soon as it's queued, so the
    next sentence is usually ready by the time the current one finishes."""

    def __init__(self, crow, body):
        self.crow = crow
        self.body = body
        self.jobs = queue.Queue()
        self.voice = ThreadPoolExecutor(max_workers=2)
        self.busy = threading.Event()   # set while the crow is speaking or moving
        self.quiet_since = 0.0
        self.heard_at = None            # when you stopped talking, for the timing printout
        self.first_text_s = None        # how long the model took to start answering
        threading.Thread(target=self._work, daemon=True).start()

    def add(self, kind, value):
        self.busy.set()
        if kind == "say":
            value = self.voice.submit(synthesize, value)
        self.jobs.put((kind, value))

    def mic_should_listen(self):
        # Mute the mic while the crow talks, plus a moment for the echo to die away,
        # so the model doesn't hear the crow and think you're talking
        return not self.busy.is_set() and time.monotonic() - self.quiet_since > config.ECHO_TAIL_S

    def _work(self):
        while True:
            kind, value = self.jobs.get()
            self.busy.set()
            try:
                if kind == "say":
                    samples, rate = value.result()
                    self._print_timing()
                    self.crow.eyes(EYES_TALKING)
                    play(self.crow, samples, rate)
                else:
                    self.body.act(value)
            except Exception as error:
                print(f"[crow] {error}")
            if self.jobs.empty():
                self.quiet_since = time.monotonic()
                self.busy.clear()
                self.crow.eyes(EYES_AWAKE)
                self.body.idle.set()

    def _print_timing(self):
        """After the first sound of each reply, show where the wait went."""
        if self.heard_at is None:
            return
        total = time.monotonic() - self.heard_at
        model = f"model {self.first_text_s:.2f}s, " if self.first_text_s is not None else ""
        print(f"      ({model}voice {total - (self.first_text_s or 0):.2f}s, "
              f"total {total:.2f}s after you stopped)")
        self.heard_at = self.first_text_s = None


# ============================================================================
# DIALOG-RSN-1 CONNECTION
# ============================================================================

async def send(ws, event):
    await ws.send(json.dumps(event))


async def answer_tool(ws, performer, event):
    try:
        args = json.loads(event.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    move = tool_to_move(event["name"], args)
    if move:
        performer.add("act", move)
        output = {"ok": True}
    else:
        output = {"error": f"unknown tool or arguments: {event['name']} {args}"}
    await send(ws, {"type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": event["call_id"],
                             "output": json.dumps(output)}})
    await send(ws, {"type": "response.create"})


def speak(performer, text):
    if text.strip(" .,!?;:-\n"):  # skip empty or punctuation-only bits
        performer.add("say", text.strip())


async def handle_events(ws, crow, body, performer, stop_after_turn=False):
    full_reply = ""     # the whole reply, for printing
    unspoken = ""       # text not yet sent to the voice
    emotion = None
    tag_checked = False
    called_tool = False
    async for raw in ws:
        event = json.loads(raw)
        kind = event["type"]

        if kind == "input_audio_buffer.speech_started":
            body.idle.clear()
            crow.neck(0)
            crow.eyes(EYES_LISTENING)
        elif kind == "input_audio_buffer.speech_stopped":
            performer.heard_at = time.monotonic()
            crow.eyes(EYES_THINKING)
        elif kind == "conversation.item.input_audio_transcription.completed":
            print(f"you:  {event.get('transcript', '').strip()}")
        elif kind == "response.created":
            called_tool = False
        elif kind == "response.output_text.delta":
            if performer.heard_at is not None and performer.first_text_s is None:
                performer.first_text_s = time.monotonic() - performer.heard_at
            full_reply += event["delta"]
            unspoken += event["delta"]
            if not tag_checked:
                start = unspoken.lstrip()
                if not start or (start.startswith("[") and "]" not in start and len(start) < 24):
                    continue  # might still be an emotion tag; wait for more
                match = EMOTION_TAG.match(unspoken)
                if match:
                    emotion, unspoken = match.group(1), unspoken[match.end():]
                tag_checked = True
            # Send each finished sentence to the voice straight away
            *sentences, unspoken = SENTENCE_END.split(unspoken)
            for sentence in sentences:
                speak(performer, sentence)
        elif kind == "response.output_text.done":
            speak(performer, unspoken)
            text = EMOTION_TAG.sub("", full_reply, count=1).strip()
            print(f"crow: {text}" + (f"  [{emotion}]" if emotion else ""))
            full_reply, unspoken, emotion, tag_checked = "", "", None, False
        elif kind == "response.function_call_arguments.done":
            called_tool = True
            print(f"crow: <{event['name']} {event.get('arguments') or ''}>")
            await answer_tool(ws, performer, event)
        elif kind == "error":
            print(f"[poly] error: {event['error'].get('message', event['error'])}")
        elif kind == "response.done":
            status = event["response"]["status"]
            if status == "failed":
                print(f"[poly] response failed: {event['response'].get('status_details')}")
            if not performer.busy.is_set():
                crow.eyes(EYES_AWAKE)   # it decided not to answer (you hadn't finished)
                body.idle.set()
            # After a tool call another response follows, so the turn isn't over yet
            if stop_after_turn and status != "in_progress" and not called_tool:
                return


async def stream_mic(ws, performer):
    loop = asyncio.get_running_loop()
    frames = asyncio.Queue()

    def callback(indata, frame_count, time_info, status):
        pcm16 = (np.clip(indata[:, 0], -1, 1) * 32767).astype(np.int16).tobytes()
        loop.call_soon_threadsafe(frames.put_nowait, pcm16)

    with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32",
                        blocksize=MIC_BLOCK, device=config.INPUT_DEVICE, callback=callback):
        while True:
            frame = await frames.get()
            if not performer.mic_should_listen():
                frame = bytes(len(frame))  # silence, so the crow doesn't hear itself
            await send(ws, {"type": "input_audio_buffer.append",
                            "audio": base64.b64encode(frame).decode()})


async def run(crow, body, say_once):
    api_key = os.environ.get("POLY_API_KEY")
    if not api_key:
        sys.exit("Set your key first:  export POLY_API_KEY=...")
    performer = Performer(crow, body)

    try:
        ws = await websockets.connect(config.POLY_URL, additional_headers={"X-API-KEY": api_key})
    except InvalidStatus as error:
        sys.exit(f"[poly] connection refused (HTTP {error.response.status_code}). "
                 "Check POLY_API_KEY, and POLY_URL if your workspace is regional.")

    async with ws:
        await ws.recv()  # session.created
        await send(ws, {"type": "session.update", "session": {
            "instructions": config.POLY_INSTRUCTIONS,
            "output_modalities": ["text"],
            "tools": TOOLS,
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": MIC_RATE},
                "turn_detection": {"type": "server_vad", "create_response": True},
            }},
        }})
        updated = json.loads(await ws.recv())
        if updated["type"] != "session.updated":
            # A refused update applies nothing, so the session would run on defaults
            sys.exit(f"[poly] session setup refused: {updated.get('error', updated)}")
        print("[poly] connected")

        if say_once:
            print(f"you:  {say_once}")
            performer.heard_at = time.monotonic()
            await send(ws, {"type": "conversation.item.create", "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": say_once}]}})
            await send(ws, {"type": "response.create"})
            await handle_events(ws, crow, body, performer, stop_after_turn=True)
            while performer.busy.is_set():
                await asyncio.sleep(0.1)
            return

        print("\nTalk to the crow. Ctrl+C to quit.")
        crow.eyes(EYES_AWAKE)
        body.idle.set()
        tasks = [asyncio.create_task(stream_mic(ws, performer)),
                 asyncio.create_task(handle_events(ws, crow, body, performer))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()  # surface whatever ended the conversation
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description="Talk to the crow through PolyAI Dialog-RSN-1.")
    parser.add_argument("--no-crow", action="store_true", help="run without the Arduino")
    parser.add_argument("--say", metavar="TEXT", help="send one typed turn instead of using the mic")
    args = parser.parse_args()

    crow = Crow(None if args.no_crow else find_nano_port())
    body = Body(crow)
    try:
        asyncio.run(run(crow, body, args.say))
    except KeyboardInterrupt:
        print("\nCaw. Goodbye.")
    except websockets.ConnectionClosed as closed:
        print(f"[poly] connection closed: {closed}")
    finally:
        sd.stop()
        crow.beak(0)
        crow.neck(0)
        crow.eyes(EYES_AWAKE)
        time.sleep(0.2)  # let the last commands reach the Nano


if __name__ == "__main__":
    main()
