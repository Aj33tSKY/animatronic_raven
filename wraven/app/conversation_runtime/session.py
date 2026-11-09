"""
The live conversation: what Raven does with each Dialog-RSN-1 event.

  speech_started       face the person, listen (and stop talking if Raven was)
  speech_stopped       think
  output_text.delta    send each finished sentence to the voice straight away
  function call        run the tool (tools/), send its result back
  response.done        note any knowledge topics it used; interrupted? stop

Meanwhile the mic streams to Dialog-RSN-1 (with Raven's own voice removed by
echo cancellation, or muted), and news from background project work is passed
to Raven at the next quiet moment.
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


def speak(performer, text, reply_id):
    if text.strip(" .,!?;:-\n"):  # skip empty or punctuation-only bits
        performer.add("say", text.strip(), reply_id)


async def handle_events(dialog, body, performer, context, stop_after_turn=False):
    full_reply = ""     # the whole reply, for printing
    unspoken = ""       # text not yet sent to the voice
    emotion = None
    tag_checked = False
    called_tool = False
    reply_id = None     # Dialog-RSN-1's id for the reply being written now
    async for event in dialog.events():
        kind = event["type"]

        if kind == "input_audio_buffer.speech_started":
            performer.user_speaking = True
            if performer.busy.is_set():
                performer.interrupt()  # the person is talking over Raven: stop and listen
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
            await run_tool(dialog, event, performer, context, reply_id)
        elif kind == "error":
            print(f"[poly] error: {event['error'].get('message', event['error'])}")
        elif kind == "response.done":
            response = event["response"]
            status = response["status"]
            performer.reply_active = False
            if response.get("poly_cited_topics"):
                print(f"      [knowledge] used: {', '.join(response['poly_cited_topics'])}")
            if status == "cancelled":
                performer.interrupt()  # Dialog-RSN-1 cut this reply off because the person spoke
            if status == "failed":
                print(f"[poly] response failed: {response.get('status_details')}")
            if not performer.busy.is_set():
                body.set_state("rest")   # it decided not to answer (they hadn't finished)
            # After a tool call another response follows, so the turn isn't over yet
            if stop_after_turn and status != "in_progress" and not called_tool:
                return


async def run_tool(dialog, event, performer, context, reply_id):
    print(f"crow: <{event['name']} {event.get('arguments') or ''}>")
    try:
        args = json.loads(event.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    context.reply_id, context.user_turns = reply_id, performer.user_turns
    output = tools.run(event["name"], args, context)
    await dialog.tool_result(event["call_id"], output)


async def stream_mic(dialog, performer, echo):
    """Send the mic to Dialog-RSN-1, with Raven's own voice removed (echo) or muted."""
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


async def pass_on_news(dialog, performer, notes):
    """Give background-work news to Raven as soon as nobody is talking."""
    while True:
        note = await notes.get()
        waited = 0.0
        while (performer.busy.is_set() or performer.user_speaking or performer.reply_active) \
                and waited < 60:
            await asyncio.sleep(0.3)
            waited += 0.3
        await dialog.system_message(note)
        performer.reply_active = True


async def wait_for_background_work(dialog, body, performer, context, notes):
    """Typed turns only: stay connected until project work is done and Raven has said so."""
    print("(waiting for background work...)")
    tasks = [asyncio.create_task(handle_events(dialog, body, performer, context)),
             asyncio.create_task(pass_on_news(dialog, performer, notes))]
    quiet = 0.0
    while quiet < 2.0:
        await asyncio.sleep(0.25)
        working = any(job.status in ("queued", "working") for job in context.wren.jobs)
        talking = performer.busy.is_set() or performer.reply_active or not notes.empty()
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
    echo = None if typed_turns else start_echo_cancellation()
    notes = asyncio.Queue()
    context = tools.Context(performer=performer, body=body, wren=start_project_work(notes))
    instructions, tool_list, knowledge = briefing.build(context)
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
                print(f"you:  {typed}")
                performer.user_turns += 1
                performer.heard_at = time.monotonic()
                body.set_state("think")
                await dialog.say(typed)
                await handle_events(dialog, body, performer, context, stop_after_turn=True)
                while performer.busy.is_set():
                    await asyncio.sleep(0.1)
            if context.wren and context.wren.jobs:
                await wait_for_background_work(dialog, body, performer, context, notes)
            return

        print("\nTalk to the crow. Ctrl+C to quit.")
        body.set_state("rest")
        tasks = [asyncio.create_task(stream_mic(dialog, performer, echo)),
                 asyncio.create_task(handle_events(dialog, body, performer, context)),
                 asyncio.create_task(pass_on_news(dialog, performer, notes))]
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
