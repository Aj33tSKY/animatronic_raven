"""
The live conversation: what Raven does with each Dialog-RSN-1 event.

  speech_started       face the person, listen (and stop talking if Raven was)
  speech_stopped       think
  output_text.delta    send each finished sentence to the voice straight away
  function call        noted; run once the reply is done (see the rules below)
  response.done        run its tool calls and send the results; note knowledge used

Meanwhile the mic streams to Dialog-RSN-1 (with Raven's own voice removed by
echo cancellation, or muted), and news from background project work is passed
to Raven at the next quiet moment.

Protocol rules this follows (from PolyAI's own client; breaking one fails every
later response with `generation_failed`):
  1. Tool calls are answered only once their reply is done, and only if it
     completed. A cancelled or failed reply's calls are dropped, never answered.
  2. All of a reply's tool results go back together, then one response.create.
     Only one response.create is ever waiting at a time.
  3. While a tool call is in flight, nothing else goes into the conversation.
  4. Our own messages (background news, typed turns) wait while the person is
     talking, while a reply is open, and for a moment after the person stops,
     while the server starts its own reply.
"""
import asyncio
import json
import os
import re
import sys
import time

import settings
import tools
from audio.microphone import MIC_RATE, Microphone
from audio.speaker import speaker
from conversation_runtime import briefing
from conversation_runtime.performer import Performer
from integrations.dialog_rsn1 import DialogError, DialogRSN1

MIC_BLOCK = 512   # 32 ms, the frame size Dialog-RSN-1's turn detector works in
ECHO_BLOCK = 480  # 30 ms: three of the echo canceller's 10 ms pieces

# Replies can start with an emotion tag, e.g. "[amused] Well, well."
EMOTION_TAG = re.compile(r"^\s*\[(\w+)\]\s*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class Turns:
    """Who has the floor, so our own messages only go in when it's safe (rules 2-4)."""
    AUTO_REPLY_WAIT_S = 1.0   # after the person stops, how long the server may take to start replying
    CREATE_WAIT_S = 5.0       # a response.create with no reply by then is given up on

    def __init__(self):
        self.user_speaking = False
        self.open_reply = None        # id of the reply being written, if any
        self.create_sent_at = None    # when our response.create went out, until its reply starts
        self.auto_reply_until = 0.0   # the server may be about to reply on its own until then
        self.tool_calls = {}          # reply id -> [calls], from appearing until answered or dropped

    @property
    def tools_in_flight(self):
        return sum(len(calls) for calls in self.tool_calls.values())

    def waiting_for_create(self):
        if self.create_sent_at and time.monotonic() - self.create_sent_at > self.CREATE_WAIT_S:
            self.create_sent_at = None
        return self.create_sent_at is not None

    def can_send(self):
        return not (self.user_speaking or self.open_reply or self.tools_in_flight
                    or self.waiting_for_create() or time.monotonic() < self.auto_reply_until)

    def sent_create(self):
        self.create_sent_at = time.monotonic()

    async def until_clear(self, also_wait=lambda: False, poll_s=0.1):
        while not self.can_send() or also_wait():
            await asyncio.sleep(poll_s)


def speak(performer, text, reply_id):
    if text.strip(" .,!?;:-\n"):  # skip empty or punctuation-only bits
        performer.add("say", text.strip(), reply_id)


async def handle_events(dialog, body, performer, context, turns, stop_after_turn=False):
    full_reply = ""     # the whole reply, for printing
    unspoken = ""       # text not yet sent to the voice
    emotion = None
    tag_checked = False
    reply_id = None     # Dialog-RSN-1's id for the reply being written now
    async for event in dialog.events():
        kind = event["type"]

        if kind == "input_audio_buffer.speech_started":
            turns.user_speaking = True
            if performer.busy.is_set():
                performer.interrupt()  # the person is talking over Raven: stop and listen
            body.face_person()
            body.set_state("listen")
        elif kind == "input_audio_buffer.speech_stopped":
            turns.user_speaking = False
            turns.auto_reply_until = time.monotonic() + Turns.AUTO_REPLY_WAIT_S
            performer.user_turns += 1
            performer.heard_at = time.monotonic()
            body.set_state("think")
        elif kind in ("input_audio_buffer.committed", "input_audio_buffer.cleared"):
            turns.user_speaking = False
        elif kind == "conversation.item.input_audio_transcription.completed":
            print(f"you:  {event.get('transcript', '').strip()}")
        elif kind == "response.created":
            reply_id = (event.get("response") or {}).get("id")
            turns.open_reply = reply_id or "reply"
            turns.create_sent_at = None
            turns.auto_reply_until = 0.0
        elif kind == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                # Rule 3: the call is in the conversation now; nothing may come between it and its result
                note_call(turns, event.get("response_id") or reply_id, item.get("id"),
                          item.get("call_id"), item.get("name"))
        elif kind == "response.function_call_arguments.done":
            call = note_call(turns, event.get("response_id") or reply_id, event.get("item_id"),
                             event.get("call_id"), event.get("name"))
            call["arguments"] = event.get("arguments") or ""
            print(f"crow: <{call['name']} {call['arguments']}>")
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
        elif kind == "error":
            print(f"[poly] error: {event['error'].get('message', event['error'])}")
            if turns.waiting_for_create() and "response" in str(event["error"].get("message", "")).lower():
                turns.create_sent_at = None  # a refused response.create leaves nothing to wait for
        elif kind == "response.done":
            response = event["response"]
            status = response["status"]
            done_id = response.get("id") or reply_id
            if turns.open_reply in (done_id, "reply"):
                turns.open_reply = None
            if response.get("poly_cited_topics"):
                print(f"      [knowledge] used: {', '.join(response['poly_cited_topics'])}")
            if response.get("poly_out_of_domain"):
                print("      [out of domain] Dialog-RSN-1 judged this outside what Raven is for")
            if status == "cancelled":
                performer.interrupt()  # Dialog-RSN-1 cut this reply off because the person spoke
            if status == "failed":
                print(f"[poly] response failed: {response.get('status_details')}")
            had_calls = await answer_tool_calls(dialog, turns, done_id, status, performer, context)
            if not performer.busy.is_set() and not had_calls:
                body.set_state("rest")   # it decided not to answer (they hadn't finished)
            # After tool calls another reply follows, so the turn isn't over yet
            if stop_after_turn and status != "in_progress" and not had_calls:
                return


def note_call(turns, reply_id, item_id, call_id, name):
    """Remember a tool call until its reply is done. Returns its record."""
    calls = turns.tool_calls.setdefault(reply_id, [])
    for call in calls:
        if (item_id and call["item_id"] == item_id) or (call_id and call["call_id"] == call_id):
            call["call_id"] = call["call_id"] or call_id
            call["name"] = call["name"] or name
            return call
    call = {"item_id": item_id, "call_id": call_id, "name": name, "arguments": ""}
    calls.append(call)
    return call


async def answer_tool_calls(dialog, turns, reply_id, status, performer, context):
    """Rules 1 and 2: once a reply is done, answer all its calls, then one response.create.
    Returns whether the reply had any tool calls."""
    calls = turns.tool_calls.get(reply_id) or []
    if not calls:
        turns.tool_calls.pop(reply_id, None)
        return False
    try:
        if status != "completed":
            # The server dropped these calls with the reply; answering one would break the history
            for call in calls:
                print(f"      (dropped {call['name']}: the reply was {status})")
            return True
        context.reply_id, context.user_turns = reply_id, performer.user_turns
        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = None
            output = (tools.run(call["name"], args, context) if isinstance(args, dict)
                      else {"error": "the arguments weren't valid JSON"})
            await dialog.tool_output(call["call_id"], output)  # call_id exactly as it came
        await dialog.create_response()
        turns.sent_create()
        return True
    finally:
        turns.tool_calls.pop(reply_id, None)


async def stream_mic(dialog, performer, echo):
    """Send the mic to Dialog-RSN-1, with Raven's own voice removed (echo) or muted.
    Audio keeps flowing all the time (silence when muted): a reply waits for it."""
    with Microphone(ECHO_BLOCK if echo else MIC_BLOCK) as mic:
        if echo:
            # How long sound takes to go out of the speaker and back into the mic
            echo.delay_ms = int((speaker().latency + mic.latency) * 1000)
        pending = b""
        while True:
            frame = await mic.read()
            if echo:
                frame = echo.clean(frame)
            elif not performer.mic_should_listen():
                frame = bytes(len(frame))  # silence, so the crow doesn't hear itself
            pending += frame
            while len(pending) >= MIC_BLOCK * 2:  # send in the 32 ms pieces Dialog-RSN-1 expects
                chunk, pending = pending[:MIC_BLOCK * 2], pending[MIC_BLOCK * 2:]
                await dialog.send_audio(chunk)


async def pass_on_news(dialog, performer, turns, notes):
    """Give background-work news to Raven at the next quiet moment (rules 3 and 4)."""
    while True:
        note = await notes.get()
        await turns.until_clear(also_wait=performer.busy.is_set)
        await dialog.system_message(note)
        turns.sent_create()


async def wait_for_background_work(dialog, body, performer, context, turns, notes):
    """Typed turns only: stay connected until project work is done and Raven has said so."""
    print("(waiting for background work...)")
    tasks = [asyncio.create_task(handle_events(dialog, body, performer, context, turns)),
             asyncio.create_task(pass_on_news(dialog, performer, turns, notes))]
    quiet = 0.0
    while quiet < 2.0:
        await asyncio.sleep(0.25)
        working = any(job.status in ("queued", "working") for job in context.wren.jobs)
        talking = performer.busy.is_set() or not turns.can_send() or not notes.empty()
        quiet = 0.0 if (working or talking) else quiet + 0.25
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def start_project_work(notes):
    """Wren, for the project-work tools, if it's set up. Returns the client or None."""
    from integrations.wren import Wren
    from tools.project_work import background_note

    def on_update(job, kind):
        print(f"[wren] job {job.number} {kind} after {job.minutes:.1f} min")
        if job.report:
            print(f"[wren] report: {job.report[:1500]}")
        notes.put_nowait(background_note(job, kind))
    wren = Wren(on_update)
    if not wren.ready:
        return None
    print(f"[wren] project work ready for: {', '.join(settings.WREN_PROJECTS)}")
    return wren


def start_echo_cancellation():
    """The echo canceller for ECHO_MODE = "cancel", or None to mute instead."""
    if settings.ECHO_MODE != "cancel":
        print("[echo] mic muted while Raven talks (ECHO_MODE = \"mute\")")
        return None
    try:
        from audio.echo import EchoCanceller
        echo = EchoCanceller(noise_suppression=settings.ECHO_NOISE_SUPPRESSION)
    except Exception as error:  # e.g. livekit not installed
        print(f"[echo] echo cancellation unavailable ({error}); muting the mic while Raven talks")
        return None
    speaker().on_output = echo.add_reference  # everything played becomes its reference
    print("[echo] echo cancellation on: you can talk over Raven to interrupt")
    return echo


async def run(nano, body, typed_turns=None):
    """A whole conversation. With typed_turns, send those instead of using the mic."""
    api_key = os.environ.get("POLY_API_KEY")
    if not api_key:
        sys.exit("Set your key first: put POLY_API_KEY in .env")
    performer = Performer(nano, body)
    turns = Turns()
    echo = None if typed_turns else start_echo_cancellation()
    notes = asyncio.Queue()
    context = tools.Context(performer=performer, body=body, wren=start_project_work(notes))
    instructions, tool_list, knowledge = briefing.build()
    print(f"[brief] {len(instructions)} characters of instructions, {len(tool_list)} tools, "
          f"{len(knowledge)} knowledge topics")

    dialog = DialogRSN1(settings.POLY_URL, api_key)
    try:
        await dialog.connect(instructions, tool_list, knowledge, MIC_RATE)
    except DialogError as error:
        sys.exit(f"[poly] {error}")
    print("[poly] connected")
    performer.report = dialog.report_playback

    try:
        if typed_turns:
            for typed in typed_turns:
                await turns.until_clear()
                print(f"you:  {typed}")
                performer.user_turns += 1
                performer.heard_at = time.monotonic()
                body.set_state("think")
                await dialog.say(typed)
                turns.sent_create()
                await handle_events(dialog, body, performer, context, turns, stop_after_turn=True)
                while performer.busy.is_set():
                    await asyncio.sleep(0.1)
            if context.wren and context.wren.jobs:
                await wait_for_background_work(dialog, body, performer, context, turns, notes)
            return

        print("\nTalk to the crow. Ctrl+C to quit.")
        body.set_state("rest")
        tasks = [asyncio.create_task(stream_mic(dialog, performer, echo)),
                 asyncio.create_task(handle_events(dialog, body, performer, context, turns)),
                 asyncio.create_task(pass_on_news(dialog, performer, turns, notes))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()  # surface whatever ended the conversation
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await dialog.close()
