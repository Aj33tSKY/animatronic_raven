#!/usr/bin/env python3
"""
The earlier version of Raven: Whisper (on this laptop) turns your speech into
text, Claude answers, and Raven speaks it. Push-to-talk by default. Kept for
comparison; the main version (start.py) uses Dialog-RSN-1 instead.

Run from the app folder, after `pip install -r alt/requirements.txt`:

    python -m alt.claude_whisper                  push-to-talk: press Enter, then speak
    python -m alt.claude_whisper --hands-free     listens whenever Raven is quiet
    python -m alt.claude_whisper --type           type instead of speaking
    python -m alt.claude_whisper --no-crow        without the Arduino

Needs ANTHROPIC_API_KEY in .env. Shares settings.py, prompts/ (the character,
speaking style and games) and the crow's hardware and voice with start.py.
"""
import argparse
import re
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

import settings
from audio.lipsync import play
from audio.speaker import SPEAKER_RATE, stop_sound
from conversation_runtime.briefing import read_prompt
from conversation_runtime.performer import Performer
from hardware.body import Body
from hardware.nano import Nano, find_port
from integrations.elevenlabs import synthesize

# --- This version's own settings ---------------------------------------------
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "low"         # chat doesn't need deep thinking; "low" keeps answers quick
WHISPER_MODEL = "base.en"     # "tiny.en" is faster, "small.en" understands more
SPEECH_THRESHOLD_X = 3.0      # how much louder than the room counts as talking
SILENCE_TO_STOP_S = 1.0       # stop recording after this much quiet
MAX_LISTEN_S = 20             # never record longer than this
SPEECH_START_TIMEOUT_S = 6    # push-to-talk: give up if nobody speaks

MIC_RATE = 16000
MIC_BLOCK_S = 0.05
NOT_SPEECH = {"", "you", "thank you", "thanks for watching", "bye"}  # Whisper hears these in silence
TAG = re.compile(r"\[([a-z ]+)\]", re.IGNORECASE)


def persona():
    """The shared character, speaking style and games, plus this version's movement tags."""
    shared = [read_prompt(settings.PROMPTS_DIR / name) for name in
              ("1-character.md", "2-speaking-style.md", "3-games.md")]
    return "\n\n".join(shared + [read_prompt(Path(__file__).with_name("tags.md"))])


def split_reply(text):
    """'[squawk] Hello. [look left] Bye.' ->
    [('sound', 'squawk'), ('say', 'Hello.'), ('act', 'look left'), ('say', 'Bye.')]"""
    text = re.sub(r"[*_#`]", "", text)
    parts, position = [], 0
    for match in TAG.finditer(text):
        before = text[position:match.start()].strip()
        if before:
            parts.append(("say", before))
        tag = match.group(1).lower().strip()
        if tag == "scold":
            parts += [("act", "scold"), ("sound", "scold")]
        else:
            parts.append(("sound", "squawk") if tag == "squawk" else ("act", tag))
        position = match.end()
    rest = text[position:].strip()
    if rest:
        parts.append(("say", rest))
    return parts


class Ears:
    """The microphone and Whisper speech to text."""

    def __init__(self):
        from faster_whisper import WhisperModel  # slow import, so only when needed
        print(f"[ears] loading Whisper '{WHISPER_MODEL}' (the first run downloads it) ...")
        self.model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        print("[ears] measuring room noise, stay quiet for a second ...")
        noise = sd.rec(int(MIC_RATE * 1.0), samplerate=MIC_RATE, channels=1,
                       dtype="float32", device=settings.INPUT_DEVICE)
        sd.wait()
        floor = float(np.sqrt(np.mean(noise ** 2)))
        self.threshold = max(floor * SPEECH_THRESHOLD_X, 0.005)

    def listen(self, start_timeout=None):
        """Record until the speaker goes quiet. Returns audio, or None if nobody spoke."""
        block = int(MIC_RATE * MIC_BLOCK_S)
        quiet_to_stop = int(SILENCE_TO_STOP_S / MIC_BLOCK_S)
        max_blocks = int(MAX_LISTEN_S / MIC_BLOCK_S)
        give_up = time.monotonic() + start_timeout if start_timeout else None
        recent, speech = [], []   # recent keeps the start of the first word
        loud_run = quiet_run = 0
        with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32",
                            blocksize=block, device=settings.INPUT_DEVICE) as stream:
            while True:
                chunk, _ = stream.read(block)
                chunk = chunk[:, 0].copy()
                loud = np.sqrt(np.mean(chunk ** 2)) > self.threshold
                if not speech:
                    recent = (recent + [chunk])[-8:]
                    loud_run = loud_run + 1 if loud else 0
                    if loud_run >= 2:  # 100 ms of sound, not just a click
                        speech = list(recent)
                    elif give_up and time.monotonic() > give_up:
                        return None
                    continue
                speech.append(chunk)
                quiet_run = 0 if loud else quiet_run + 1
                if quiet_run >= quiet_to_stop or len(speech) >= max_blocks:
                    return np.concatenate(speech)

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1)
        return " ".join(segment.text.strip() for segment in segments).strip()


class Brain:
    """Claude, keeping the conversation so far."""

    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.messages = []
        self.system = persona()

    def reply(self, heard):
        anthropic = self.anthropic
        self.messages.append({"role": "user", "content": heard})
        try:
            response = self.client.beta.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=self.system,
                messages=self.messages,
                output_config={"effort": CLAUDE_EFFORT},
                cache_control={"type": "ephemeral"},
                # If a request is declined, retry it on Anthropic's recommended fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            sys.exit("[brain] Claude rejected the API key. Set ANTHROPIC_API_KEY in .env.")
        except anthropic.RateLimitError:
            self.messages.pop()
            return "[shake] Caw. Too many questions, give me a moment."
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as error:
            print(f"[brain] {error}")
            self.messages.pop()
            return "[squawk] My head has gone all fuzzy. Try again."
        if response.stop_reason == "refusal":
            self.messages.pop()
            return "[shake] Caw. I'd rather not talk about that."
        # Keep the whole reply (including hidden thinking) so the next turn has context
        self.messages.append({"role": "assistant", "content": response.content})
        return "".join(block.text for block in response.content if block.type == "text").strip()


def respond(nano, body, performer, brain, heard):
    print(f"you:  {heard}")
    body.set_state("think")
    reply = brain.reply(heard)
    print(f"crow: {reply}")
    for kind, value in split_reply(reply):
        performer.add(kind, value)
    while performer.busy.is_set():
        time.sleep(0.05)


def converse(nano, body, hands_free, typed):
    ears = None if typed else Ears()
    brain = Brain()
    performer = Performer(nano, body)
    print("\nRaven is listening. Ctrl+C to quit.")
    while True:
        body.set_state("rest")
        if typed:
            heard = input("\nyou> ").strip()
        else:
            if not hands_free:
                input("\n[Press Enter, then speak]")
                body.face_person()
                body.set_state("listen")
            audio = ears.listen(None if hands_free else SPEECH_START_TIMEOUT_S)
            if audio is None:
                print("(didn't hear anything)")
                continue
            body.set_state("think")
            heard = ears.transcribe(audio)
        if re.sub(r"[^a-z ]", "", heard.lower()).strip() in NOT_SPEECH:
            continue
        respond(nano, body, performer, brain, heard)


def main():
    parser = argparse.ArgumentParser(description="Talk to Raven with Whisper and Claude.")
    parser.add_argument("--hands-free", action="store_true", help="listen without pressing Enter")
    parser.add_argument("--type", action="store_true", help="type instead of speaking")
    parser.add_argument("--no-crow", action="store_true", help="run without the Arduino")
    args = parser.parse_args()
    nano = Nano(None if args.no_crow else find_port())
    body = Body(nano)
    try:
        converse(nano, body, args.hands_free, args.type)
    except (KeyboardInterrupt, EOFError):
        print("\nCaw. Goodbye.")
    finally:
        body.set_state("still")
        stop_sound()
        nano.beak(0)
        nano.neck(0)
        time.sleep(0.2)


if __name__ == "__main__":
    main()
