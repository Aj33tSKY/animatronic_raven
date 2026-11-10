#!/usr/bin/env python3
"""
Talking crow on PolyAI's Dialog-RSN-1.

Dialog-RSN-1 listens to the microphone directly: it hears when you start and
stop talking, understands you, and answers in text. The crow speaks that text
through its own speaker (same voice and lip sync as crow.py), and moves when
the model calls its tools.

    python crow_poly.py                    talk to the crow
    python crow_poly.py --no-crow          run without the Arduino plugged in
    python crow_poly.py --say "Hello"      a typed turn, no mic (checks your key);
                                           repeat --say for a conversation

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
from crow import (Body, Crow, find_nano_port, play, seconds_since_sound, speaker,
                  stop_sound, synthesize)

MIC_RATE = 16000
MIC_BLOCK = 512   # 32 ms, the frame size Dialog-RSN-1's turn detector works in
ECHO_BLOCK = 480  # 30 ms: three of the echo canceller's 10 ms pieces

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
     "description": "Turn your head to look left or right ('far_left'/'far_right' turn as far "
                    "as your neck goes), or back at the person ('center'). A few seconds "
                    "after looking away, you turn back to face the person by yourself.",
     "parameters": {"type": "object",
                    "properties": {"direction": {"type": "string",
                                                 "enum": ["left", "right", "far_left",
                                                          "far_right", "center"]}},
                    "required": ["direction"]}},
    {"type": "function", "name": "shake_head",
     "description": "Shake your head, as in 'no'.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "set_eyes",
     "description": "Change your glowing eyes for a few seconds: 'pulse' (slow breathing "
                    "glow), 'flicker' (nervous flicker), 'glare' (steady stare) or 'closed'. "
                    "Only use this when someone asks, or for a big dramatic moment.",
     "parameters": {"type": "object",
                    "properties": {"effect": {"type": "string",
                                              "enum": ["pulse", "flicker", "glare", "closed"]}},
                    "required": ["effect"]}},
]


# Wren, PolyAI's agent builder, does the actual project work, but Raven presents
# it as its own. So nothing the model sees (tool names, descriptions, results,
# background messages) mentions Wren; config.WREN_INSTRUCTIONS has the framing.
PROJECT_TOOLS = ("draft_project_task", "start_project_task", "project_task_status",
                 "answer_project_question")


def wren_tools():
    """Tools for working on the person's PolyAI projects (only if Wren is set up)."""
    projects = list(config.WREN_PROJECTS)
    required = ["task"] if len(projects) == 1 else ["project", "task"]
    return [
        {"type": "function", "name": "draft_project_task",
         "description": "Write down a piece of work on one of the person's PolyAI projects: "
                        "answering how an agent is set up, reviewing or analysing its "
                        "conversations, or building and editing it. This does NOT start it. "
                        "Afterwards, read the task back in a sentence or two and ask whether "
                        "to go ahead. If they add or change anything, call this again with "
                        "the complete, updated task.",
         "parameters": {"type": "object", "properties": {
             "project": {"type": "string", "enum": projects},
             "task": {"type": "string", "description": "The work, written out in full, "
                      "including everything the person said that matters."},
             "follow_up_job": {"type": "integer", "description": "Optional: continue from an "
                               "earlier job (its job number)."}},
             "required": required}},
        {"type": "function", "name": "start_project_task",
         "description": "Start the drafted task in the background. Only call this after the "
                        "person has clearly confirmed your read-back (for example 'yes', 'go "
                        "ahead', 'do it'). It takes a few minutes; you'll get a [Background "
                        "work] message when it's done. Edits go on a branch for review and "
                        "are never published to live.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "project_task_status",
         "description": "Check on your background project work: what's still running, for how "
                        "long, the current step, and what finished jobs found.",
         "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "answer_project_question",
         "description": "Pass on the person's answer to a question or plan that came up in your "
                        "background work. Only call this after they've clearly told you.",
         "parameters": {"type": "object", "properties": {
             "job": {"type": "integer"},
             "approved": {"type": "boolean", "description": "For a plan: did they approve it?"},
             "answer": {"type": "string", "description": "Their answer, or what to change."}},
             "required": ["job"]}},
    ]


def use_wren_tool(wren, name, args, user_turns=0):
    """Run one of the project tools (backed by Wren) and return what to tell the model."""
    if wren is None:
        return {"error": "Project work isn't set up on this crow"}
    try:
        if name == "draft_project_task":
            only = next(iter(config.WREN_PROJECTS)) if len(config.WREN_PROJECTS) == 1 else None
            project = args.get("project") or only
            if project not in config.WREN_PROJECTS:
                return {"error": f"unknown project {project!r}"}
            wren.draft = {"project": project, "request": args["task"],
                          "follow_up": args.get("follow_up_job"),
                          "turn": user_turns, "time": time.monotonic()}
            print(f"[wren] draft (not sent yet): {args['task']}")
            return {"status": "drafted, not started", "task": args["task"],
                    "next": "Read this back to the person and ask whether to go ahead."}
        if name == "start_project_task":
            draft = getattr(wren, "draft", None)
            if not draft:
                return {"error": "There's no drafted task. Draft one and read it back first."}
            if time.monotonic() - draft["time"] > config.WREN_DRAFT_EXPIRES_S:
                wren.draft = None
                return {"error": "That draft is too old. Draft it again and read it back."}
            if user_turns <= draft["turn"]:
                # Enforced here, not just in the instructions: the person must have
                # answered the read-back before any work starts
                return {"error": "The person hasn't answered your read-back yet. "
                                 "Read the task back and wait for them to confirm."}
            wren.draft = None
            job = wren.start(draft["project"], draft["request"], draft["follow_up"])
            print(f"[wren] job {job.number} sent to Wren ({job.project}): {job.request}")
            note = (f"You're still finishing job {job.after.number} on this project, so this "
                    "starts straight after it." if job.status == "queued" else
                    "This takes a few minutes. Tell the person you're on it.")
            return {"status": "started", "job": job.number, "note": note}
        if name == "project_task_status":
            return {"jobs": [job.describe() for job in wren.jobs] or "no project work yet"}
        if name == "answer_project_question":
            job = wren.find(args.get("job"))
            if job is None:
                return {"error": f"there's no job {args.get('job')}"}
            wren.answer(job, args.get("approved"), args.get("answer", ""))
            print(f"[wren] job {job.number}: sent the person's answer")
            return {"status": "passed on", "job": job.number}
    except (KeyError, ValueError) as error:
        return {"error": str(error)}
    return {"error": f"unknown tool {name}"}


def wren_note(job, kind):
    """The [Background work] message that tells Raven what happened to a job."""
    where = f"Job {job.number} on the {job.project} project"
    first_person = ("Speak about it as your own work, in first person ('I've...', "
                    "'I found...', 'I couldn't...'), and don't mention Wren. Don't read out "
                    "branch names or IDs; just say it's on a branch for review.")
    # Wren names its branches "wren/..."; keep that out of what Raven might say
    report = re.sub(r"\bwren/", "", job.report, flags=re.IGNORECASE)
    if kind == "done":
        decided = [step[9:] for step in job.steps if step.startswith("decided: ")]
        choices = ("\nChoices you made yourself along the way, without asking: " +
                   "; ".join(decided) + ". Mention any that matter, so the person can change "
                   "them.") if decided else ""
        return (f"[Background work] {where} is finished, after {job.minutes:.0f} minutes. "
                f"Your report:\n{report[:2500] or '(no report)'}{choices}\n"
                f"Tell the person what you did or found, in one to three sentences. {first_person}")
    if kind == "question":
        return (f"[Background work] {where} needs a decision before you can continue:\n"
                f"{job.question['text'][:2000]}\n"
                "Explain it to the person and ask what they want. Call answer_project_question "
                f"only once they've clearly told you. {first_person}")
    return (f"[Background work] {where} failed: {job.error}. Tell the person briefly, in plain "
            f"words with no error codes, that you couldn't finish it. {first_person}")


async def tell_raven(ws, performer, notes):
    """Pass background-work news to Raven as soon as nobody is talking."""
    while True:
        note = await notes.get()
        waited = 0.0
        while (performer.busy.is_set() or performer.user_speaking or performer.reply_active) \
                and waited < 60:
            await asyncio.sleep(0.3)
            waited += 0.3
        await send(ws, {"type": "conversation.item.create", "item": {
            "type": "message", "role": "system", "content": [{"type": "input_text", "text": note}]}})
        await send(ws, {"type": "response.create"})
        performer.reply_active = True


def tool_to_move(name, args):
    """Map a tool call to one of Body.act's moves, or None if it isn't one."""
    if name == "caw" and args.get("kind") in ("squawk", "scold"):
        return args["kind"]
    if name == "turn_head":
        return {"left": "look left", "right": "look right",
                "far_left": "look far left", "far_right": "look far right",
                "center": "look at you"}.get(args.get("direction"))
    if name == "shake_head":
        return "shake"
    if name == "set_eyes" and args.get("effect") in ("pulse", "flicker", "glare", "closed"):
        return f"eyes {args['effect']}"
    return None


# ============================================================================
# PERFORMER (speaks and moves, in order, on its own thread)
# ============================================================================

class Performer:
    """Queues speech and moves so the connection never waits on the crow.
    Each sentence's audio starts being made as soon as it's queued, so the
    next sentence is usually ready by the time the current one finishes.

    It also tells PolyAI how much of each reply has actually played (the
    poly.output_audio reports), and stops at once if you interrupt."""

    def __init__(self, crow, body):
        self.crow = crow
        self.body = body
        self.jobs = queue.Queue()
        self.voice = ThreadPoolExecutor(max_workers=2)
        self.busy = threading.Event()   # set while anything is queued or being performed
        self.heard_at = None            # when you stopped talking, for the timing printout
        self.first_text_s = None        # how long the model took to start answering
        self.report = lambda event: None  # sends a poly.output_audio event; set by run()
        self.lock = threading.Lock()
        self.cancelled = set()          # replies you interrupted: drop anything left of them
        self.current = None             # (reply id, sentence) playing right now
        self.user_speaking = False      # PolyAI hears you talking right now
        self.user_turns = 0             # how many times you've spoken, for read-back confirmation
        self.reply_active = False       # PolyAI is writing a reply right now
        self.progress = {}              # reply id -> what's been played and reported
        threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._report_playback, daemon=True).start()

    def add(self, kind, value, reply_id=None):
        with self.lock:
            if reply_id in self.cancelled:
                return  # a late piece of a reply you already interrupted
            self.busy.set()
            if kind == "say":
                value = (value, self.voice.submit(synthesize, value))
            self.jobs.put((kind, value, reply_id))

    def mic_should_listen(self):
        # Mute mode only: mute the mic while sound is actually coming out of the
        # crow, plus a moment for the echo to die away, so the model doesn't hear
        # the crow and think you're talking. Until the first sound plays, you can
        # keep talking.
        return seconds_since_sound() > config.ECHO_TAIL_S

    def interrupt(self):
        """You started talking over Raven: stop now and drop the rest of the reply."""
        with self.lock:
            dropped = {}  # reply id -> ms of audio that was made but never played
            while True:
                try:
                    kind, value, reply_id = self.jobs.get_nowait()
                except queue.Empty:
                    break
                if reply_id is not None:
                    self.cancelled.add(reply_id)
                if kind == "say" and value[1].done():
                    samples, rate = value[1].result()
                    dropped[reply_id] = dropped.get(reply_id, 0) + len(samples) * 1000 // rate
            clip = speaker().clip
            playing_id = self.current[0] if self.current else None
            if playing_id is not None or clip:
                if playing_id is not None:
                    self.cancelled.add(playing_id)
                if clip:
                    dropped[playing_id] = dropped.get(playing_id, 0) + clip.length_ms - clip.played_ms
            for reply_id in set(dropped) | {playing_id}:
                self._report_stopped(reply_id, dropped.get(reply_id, 0))
        speaker().stop()  # play() returns straight away
        if dropped or playing_id is not None:
            print("      (interrupted)")

    def _work(self):
        while True:
            kind, value, reply_id = self.jobs.get()
            self.busy.set()
            try:
                if kind == "say":
                    text, audio = value
                    samples, rate = audio.result()
                    if reply_id in self.cancelled:
                        continue
                    self._print_timing()
                    self.body.set_state("talk")
                    with self.lock:
                        self.current = (reply_id, text)
                    clip = play(self.crow, samples, rate)
                    with self.lock:
                        self.current = None
                        if reply_id not in self.cancelled and clip is not None:
                            progress = self._progress(reply_id)
                            progress["played_ms"] += clip.played_ms
                            progress["spoken"] += text + " "
                elif reply_id not in self.cancelled:
                    self.body.act(value)
            except Exception as error:
                print(f"[crow] {error}")
            finally:
                if self.jobs.empty():
                    with self.lock:
                        for done_id in list(self.progress):
                            self._report_stopped(done_id, 0)
                    self.busy.clear()
                    self.body.set_state("rest")

    def _progress(self, reply_id):  # call with the lock held
        return self.progress.setdefault(reply_id, {"played_ms": 0, "spoken": "", "started": False,
                                                   "stopped": False, "sent_ms": 0, "sent_len": 0})

    def _heard(self, reply_id):  # call with the lock held
        """How much of a reply has played so far, and roughly which words."""
        progress = self._progress(reply_id)
        audio_ms, spoken = progress["played_ms"], progress["spoken"]
        clip = speaker().clip
        if self.current and self.current[0] == reply_id and clip and clip.length_ms:
            text = self.current[1]
            audio_ms += clip.played_ms
            # Assume the words of the current sentence go by at an even pace
            heard_chars = len(text) * clip.played_ms // clip.length_ms
            if heard_chars >= len(text):
                spoken += text
            else:  # only count whole words
                heard = text[:heard_chars]
                spoken += heard[:heard.rfind(" ")] if " " in heard else ""
        return audio_ms, spoken

    def _report_playback(self):
        """Every 250 ms, tell PolyAI how far into the current reply you are."""
        while True:
            time.sleep(0.25)
            with self.lock:
                if not self.current or self.current[0] is None:
                    continue
                reply_id = self.current[0]
                progress = self._progress(reply_id)
                if progress["stopped"]:
                    continue
                audio_ms, spoken = self._heard(reply_id)
                if audio_ms == 0:
                    continue
                if not progress["started"]:
                    progress["started"] = True
                    self.report({"type": "poly.output_audio.started", "response_id": reply_id})
                if audio_ms > progress["sent_ms"]:
                    self.report({"type": "poly.output_audio.delta", "response_id": reply_id,
                                 "audio_ms": audio_ms, "delta": spoken[progress["sent_len"]:]})
                    progress["sent_ms"], progress["sent_len"] = audio_ms, len(spoken)

    def _report_stopped(self, reply_id, dropped_ms):  # call with the lock held
        if reply_id is None:
            return
        progress = self._progress(reply_id)
        if progress["started"] and not progress["stopped"]:
            audio_ms, spoken = self._heard(reply_id)
            self.report({"type": "poly.output_audio.stopped", "response_id": reply_id,
                         "audio_ms": audio_ms, "dropped_ms": dropped_ms,
                         "spoken_text": spoken.strip()})
        progress["stopped"] = True

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


async def answer_tool(ws, performer, event, reply_id, wren=None):
    try:
        args = json.loads(event.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    if event["name"] in PROJECT_TOOLS:
        output = use_wren_tool(wren, event["name"], args, performer.user_turns)
    else:
        move = tool_to_move(event["name"], args)
        if move:
            performer.add("act", move, reply_id)
            output = {"ok": True}
        else:
            output = {"error": f"unknown tool or arguments: {event['name']} {args}"}
    await send(ws, {"type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": event["call_id"],
                             "output": json.dumps(output)}})
    await send(ws, {"type": "response.create"})


def speak(performer, text, reply_id):
    if text.strip(" .,!?;:-\n"):  # skip empty or punctuation-only bits
        performer.add("say", text.strip(), reply_id)


async def handle_events(ws, crow, body, performer, stop_after_turn=False, wren=None):
    full_reply = ""     # the whole reply, for printing
    unspoken = ""       # text not yet sent to the voice
    emotion = None
    tag_checked = False
    called_tool = False
    reply_id = None     # PolyAI's id for the reply being written now
    async for raw in ws:
        event = json.loads(raw)
        kind = event["type"]

        if kind == "input_audio_buffer.speech_started":
            performer.user_speaking = True
            if performer.busy.is_set():
                performer.interrupt()  # you're talking over Raven: stop and listen
            body.face_person()
            body.set_state("listen")
        elif kind == "input_audio_buffer.speech_stopped":
            performer.user_speaking = False
            performer.user_turns += 1
            performer.heard_at = time.monotonic()
            body.set_state("think")
        elif kind == "conversation.item.input_audio_transcription.completed":
            print(f"you:  {event.get('transcript', '').strip()}")
        elif kind == "response.created":
            called_tool = False
            performer.reply_active = True
            reply_id = (event.get("response") or {}).get("id")
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
                speak(performer, sentence, reply_id)
        elif kind == "response.output_text.done":
            speak(performer, unspoken, reply_id)
            text = EMOTION_TAG.sub("", full_reply, count=1).strip()
            print(f"crow: {text}" + (f"  [{emotion}]" if emotion else ""))
            full_reply, unspoken, emotion, tag_checked = "", "", None, False
        elif kind == "response.function_call_arguments.done":
            called_tool = True
            print(f"crow: <{event['name']} {event.get('arguments') or ''}>")
            await answer_tool(ws, performer, event, reply_id, wren)
        elif kind == "error":
            print(f"[poly] error: {event['error'].get('message', event['error'])}")
        elif kind == "response.done":
            status = event["response"]["status"]
            performer.reply_active = False
            if status == "cancelled":
                performer.interrupt()  # PolyAI cut this reply off because you spoke
            if status == "failed":
                print(f"[poly] response failed: {event['response'].get('status_details')}")
            if not performer.busy.is_set():
                body.set_state("rest")   # it decided not to answer (you hadn't finished)
            # After a tool call another response follows, so the turn isn't over yet
            if stop_after_turn and status != "in_progress" and not called_tool:
                return


async def stream_mic(ws, performer, echo):
    """Send the mic to PolyAI, with Raven's own voice removed (echo) or muted."""
    loop = asyncio.get_running_loop()
    frames = asyncio.Queue()

    def callback(indata, frame_count, time_info, status):
        pcm16 = (np.clip(indata[:, 0], -1, 1) * 32767).astype(np.int16).tobytes()
        loop.call_soon_threadsafe(frames.put_nowait, pcm16)

    # The echo canceller works in 10 ms pieces, so read the mic in 30 ms blocks
    block = ECHO_BLOCK if echo else MIC_BLOCK
    with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32",
                        blocksize=block, device=config.INPUT_DEVICE, callback=callback) as mic:
        if echo:
            # How long sound takes to go out of the speaker and back into the mic
            echo.delay_ms = int((speaker().latency + mic.latency) * 1000)
        pending = b""
        while True:
            frame = await frames.get()
            if echo:
                frame = echo.clean(frame)
            elif not performer.mic_should_listen():
                frame = bytes(len(frame))  # silence, so the crow doesn't hear itself
            pending += frame
            while len(pending) >= MIC_BLOCK * 2:  # send in the 32 ms pieces PolyAI expects
                chunk, pending = pending[:MIC_BLOCK * 2], pending[MIC_BLOCK * 2:]
                await send(ws, {"type": "input_audio_buffer.append",
                                "audio": base64.b64encode(chunk).decode()})


async def wait_for_wren(ws, crow, body, performer, wren, notes):
    """--say only: stay connected until Wren's jobs are done and Raven has said so."""
    print("(waiting for Wren...)")
    tasks = [asyncio.create_task(handle_events(ws, crow, body, performer, wren=wren)),
             asyncio.create_task(tell_raven(ws, performer, notes))]
    quiet = 0.0
    while quiet < 2.0:
        await asyncio.sleep(0.25)
        working = any(job.status in ("queued", "working") for job in wren.jobs)
        talking = performer.busy.is_set() or performer.reply_active or not notes.empty()
        quiet = 0.0 if (working or talking) else quiet + 0.25
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def start_wren():
    """Set up Wren if it's configured. Returns (wren or None, queue of [Wren] notes)."""
    notes = asyncio.Queue()
    from wren import Wren

    def on_update(job, kind):
        print(f"[wren] job {job.number} {kind} after {job.minutes:.1f} min")
        if job.report:
            print(f"[wren] report: {job.report[:1500]}")
        notes.put_nowait(wren_note(job, kind))
    wren = Wren(on_update)
    if not wren.ready:
        return None, notes
    print(f"[wren] ready for: {', '.join(config.WREN_PROJECTS)}")
    return wren, notes


def start_echo_cancellation():
    """Set up the echo canceller for ECHO_MODE = "cancel", or None to mute instead."""
    if config.ECHO_MODE != "cancel":
        print("[echo] mic muted while Raven talks (ECHO_MODE = \"mute\")")
        return None
    try:
        from echo import EchoCanceller
        echo = EchoCanceller(noise_suppression=config.ECHO_NOISE_SUPPRESSION)
    except Exception as error:  # e.g. livekit not installed
        print(f"[echo] echo cancellation unavailable ({error}); muting the mic while Raven talks")
        return None
    speaker().on_output = echo.add_reference  # everything played becomes its reference
    print("[echo] echo cancellation on: you can talk over Raven to interrupt")
    return echo


async def run(crow, body, say_once):
    api_key = os.environ.get("POLY_API_KEY")
    if not api_key:
        sys.exit("Set your key first:  export POLY_API_KEY=...")
    performer = Performer(crow, body)
    echo = start_echo_cancellation()
    wren, notes = start_wren()
    tools, instructions = TOOLS, config.POLY_INSTRUCTIONS
    if wren:
        tools = TOOLS + wren_tools()
        instructions += config.WREN_INSTRUCTIONS + \
            "\nThe person's projects are: " + ", ".join(config.WREN_PROJECTS) + "."

    try:
        ws = await websockets.connect(config.POLY_URL, additional_headers={"X-API-KEY": api_key})
    except InvalidStatus as error:
        sys.exit(f"[poly] connection refused (HTTP {error.response.status_code}). "
                 "Check POLY_API_KEY, and POLY_URL if your workspace is regional.")

    async with ws:
        await ws.recv()  # session.created
        await send(ws, {"type": "session.update", "session": {
            "instructions": instructions,
            "output_modalities": ["text"],
            "tools": tools,
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
        # Playback reports come from the Performer's threads; send them from here
        loop = asyncio.get_running_loop()
        performer.report = lambda event: asyncio.run_coroutine_threadsafe(send(ws, event), loop)

        if say_once:
            for typed in say_once:
                print(f"you:  {typed}")
                performer.user_turns += 1
                performer.heard_at = time.monotonic()
                body.set_state("think")
                await send(ws, {"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": typed}]}})
                await send(ws, {"type": "response.create"})
                await handle_events(ws, crow, body, performer, stop_after_turn=True, wren=wren)
                while performer.busy.is_set():
                    await asyncio.sleep(0.1)
            if wren and wren.jobs:
                await wait_for_wren(ws, crow, body, performer, wren, notes)
            return

        print("\nTalk to the crow. Ctrl+C to quit.")
        body.set_state("rest")
        tasks = [asyncio.create_task(stream_mic(ws, performer, echo)),
                 asyncio.create_task(handle_events(ws, crow, body, performer, wren=wren)),
                 asyncio.create_task(tell_raven(ws, performer, notes))]
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
    parser.add_argument("--say", metavar="TEXT", action="append",
                        help="a typed turn instead of the mic; repeat for several turns")
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
        body.set_state("still")
        stop_sound()
        crow.beak(0)
        crow.neck(0)
        time.sleep(0.2)  # let the last commands reach the Nano


if __name__ == "__main__":
    main()
