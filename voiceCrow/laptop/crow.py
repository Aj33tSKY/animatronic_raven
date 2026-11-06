#!/usr/bin/env python3
"""
Talking crow: you speak into the mic, Claude answers, and the crow says it
through its own speaker while its beak, neck and eyes move to match.

    python crow.py                  push-to-talk: press Enter, then speak
    python crow.py --hands-free     listens by itself whenever the crow is quiet
    python crow.py --type           type instead of speaking (no mic needed)
    python crow.py --no-crow        run without the Arduino plugged in
    python crow.py --test-lipsync   say a line and a squawk with lip sync, no AI
    python crow.py --list-devices   show audio devices and serial ports

Settings live in config.py.
"""
import argparse
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import serial
import serial.tools.list_ports
import sounddevice as sd
import soundfile as sf

import config

# Eye modes, matching the E command in the Nano sketch
EYES_OFF, EYES_AWAKE, EYES_LISTENING, EYES_THINKING, EYES_TALKING = range(5)

MIC_RATE = 16000        # sample rate Whisper expects
MIC_BLOCK_S = 0.05      # analyse the mic in 50 ms chunks

# Things Whisper "hears" in silence or background noise
NOT_SPEECH = {"", "you", "thank you", "thanks for watching", "bye"}


# ============================================================================
# CROW HARDWARE (Arduino Nano over USB serial)
# ============================================================================

class Crow:
    """Sends movement commands to the Nano. Without a port it just pretends."""

    def __init__(self, port):
        self.serial = None
        self.lock = threading.Lock()
        if port is None:
            print("[crow] running without the Arduino")
            return

        print(f"[crow] connecting on {port} ...")
        self.serial = serial.Serial(port, 115200, timeout=0.5)
        # Opening the port restarts the Nano. It says READY once the neck is centered.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = self.serial.readline().decode(errors="replace").strip()
            if line == "READY":
                break
            if line:
                print(f"[nano] {line}")
        else:
            sys.exit("[crow] The Nano never said READY. Is voice-crow-nano uploaded?")
        threading.Thread(target=self._print_replies, daemon=True).start()
        print("[crow] connected")

    def _print_replies(self):
        try:
            while True:
                line = self.serial.readline().decode(errors="replace").strip()
                if line:
                    print(f"[nano] {line}")
        except serial.SerialException:
            print("[crow] lost the USB connection to the Nano")

    def send(self, command):
        if self.serial:
            with self.lock:
                self.serial.write((command + "\n").encode())

    def beak(self, percent):
        self.send(f"B{int(percent)}")

    def eyes(self, mode):
        self.send(f"E{mode}")

    def neck(self, position, fast=False):
        if config.NECK_FLIP:
            position = -position
        self.send(f"S{int(fast)}")
        self.send(f"N{int(position)}")


def find_nano_port():
    if config.SERIAL_PORT:
        return config.SERIAL_PORT
    for port in serial.tools.list_ports.comports():
        # CH340 (most clones), FTDI, or genuine Arduino USB chips
        if port.vid in (0x1A86, 0x0403, 0x2341) or "usbserial" in port.device:
            return port.device
    sys.exit("Couldn't find the Nano. Plug it in, or set SERIAL_PORT in config.py "
             "(see --list-devices), or use --no-crow.")


# ============================================================================
# MOUTH (text to speech + lip sync)
# ============================================================================

ELEVENLABS_RATE = 24000  # raw PCM; 44.1 kHz would need a Pro plan

# One shared connection, so each sentence skips a fresh HTTPS handshake
elevenlabs = httpx.Client(base_url="https://api.elevenlabs.io", timeout=30)


def synthesize(text):
    """Turn text into (samples, rate) with the engine chosen in config.TTS_ENGINE."""
    if config.TTS_ENGINE == "elevenlabs":
        try:
            return synthesize_elevenlabs(text)
        except (httpx.HTTPError, RuntimeError) as error:
            # Keep talking even if the service is down or out of credit
            print(f"[voice] ElevenLabs failed ({error}), using the Mac voice instead")
    return synthesize_say(text)


def synthesize_elevenlabs(text):
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY isn't set")
    response = elevenlabs.post(
        f"/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
        params={"output_format": f"pcm_{ELEVENLABS_RATE}"},
        headers={"xi-api-key": api_key},
        json={"text": text,
              "model_id": config.ELEVENLABS_MODEL,
              "voice_settings": {"stability": config.ELEVENLABS_STABILITY,
                                 "speed": config.ELEVENLABS_SPEED}},
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    # 16-bit little-endian mono samples
    samples = np.frombuffer(response.content, dtype="<i2").astype(np.float32) / 32768
    return samples, ELEVENLABS_RATE


def synthesize_say(text):
    """Turn text into audio with the macOS `say` command."""
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "speech.txt"
        wav_file = Path(tmp) / "speech.wav"
        text_file.write_text(text)
        subprocess.run(["say", "-v", config.VOICE, "-r", str(config.VOICE_RATE),
                        "--file-format=WAVE", "--data-format=LEI16@22050",
                        "-o", str(wav_file), "-f", str(text_file)], check=True)
        samples, rate = sf.read(wav_file, dtype="float32")
    return samples, rate


def beak_envelope(samples, rate):
    """How loud the audio is, LIPSYNC_FPS times a second, as beak percent 0-100."""
    hop = rate // config.LIPSYNC_FPS
    frames = len(samples) // hop
    if frames == 0:
        return np.zeros(0)
    rms = np.sqrt(np.mean(samples[:frames * hop].reshape(frames, hop) ** 2, axis=1))
    loudest = np.percentile(rms, 95)
    if loudest <= 0:
        return np.zeros(frames)
    level = np.clip(rms / loudest, 0, 1)
    level[level < config.BEAK_GATE] = 0
    return level ** 0.7 * config.BEAK_MAX_OPEN


def play(crow, samples, rate):
    """Play audio through the crow's speaker while the beak follows its loudness."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float32)
    envelope = beak_envelope(samples, rate)
    frame_s = 1 / config.LIPSYNC_FPS

    sd.play(samples * config.SPEAKER_VOLUME, rate, device=config.OUTPUT_DEVICE)
    start = time.monotonic()
    latency = sd.get_stream().latency  # time for sound to actually leave the speaker
    last_value, last_sent = None, 0.0
    while True:
        now = time.monotonic()
        frame = int((now - start - latency + config.LIPSYNC_LEAD_S) / frame_s)
        if frame >= len(envelope):
            break
        if frame >= 0:
            value = int(envelope[frame])
            # Resend now and then: the Nano closes the beak if it hears nothing
            if value != last_value or now - last_sent > 0.2:
                crow.beak(value)
                last_value, last_sent = value, now
        time.sleep(frame_s / 2)
    sd.wait()
    crow.beak(0)


# ============================================================================
# BODY LANGUAGE (tags in Claude's reply, plus idle glances)
# ============================================================================

class Body:
    def __init__(self, crow):
        self.crow = crow
        self.idle = threading.Event()
        threading.Thread(target=self._glance_around, daemon=True).start()

    def act(self, tag):
        side = config.NECK_SIDE
        if tag == "squawk":
            self.play_track(random.choice(config.SQUAWK_TRACKS))
        elif tag == "scold":
            self.crow.neck(random.randint(-side // 5, side // 5), fast=True)
            self.play_track(random.choice(config.SCOLD_TRACKS))
        elif tag == "look left":
            self.crow.neck(-int(side * 0.6), fast=True)
        elif tag == "look right":
            self.crow.neck(int(side * 0.6), fast=True)
        elif tag in ("look at you", "look center"):
            self.crow.neck(0)
        elif tag == "shake":
            threading.Thread(target=self._shake, daemon=True).start()
        else:
            print(f"[body] unknown tag [{tag}], ignoring")

    def play_track(self, number):
        path = config.MP3_DIR / f"{number:04d}.mp3"
        samples, rate = sf.read(path, dtype="float32")
        self.crow.eyes(EYES_TALKING)
        play(self.crow, samples, rate)

    def _shake(self):
        for position in (-150, 150, -150, 0):
            self.crow.neck(position, fast=True)
            time.sleep(0.4)

    def _glance_around(self):
        while True:
            time.sleep(random.uniform(*config.IDLE_LOOK_EVERY_S))
            if self.idle.is_set():
                reach = int(config.NECK_SIDE * 0.5)
                self.crow.neck(random.randint(-reach, reach))


TAG = re.compile(r"\[([a-z ]+)\]", re.IGNORECASE)


def split_reply(text):
    """'[squawk] Hello. [look left] Bye.' ->
    [('act', 'squawk'), ('say', 'Hello.'), ('act', 'look left'), ('say', 'Bye.')]"""
    text = re.sub(r"[*_#`]", "", text)
    parts, position = [], 0
    for match in TAG.finditer(text):
        before = text[position:match.start()].strip()
        if before:
            parts.append(("say", before))
        parts.append(("act", match.group(1).lower().strip()))
        position = match.end()
    rest = text[position:].strip()
    if rest:
        parts.append(("say", rest))
    return parts


# ============================================================================
# EARS (microphone + Whisper speech to text)
# ============================================================================

class Ears:
    def __init__(self):
        from faster_whisper import WhisperModel  # slow import, so only when needed
        print(f"[ears] loading Whisper '{config.WHISPER_MODEL}' (the first run downloads it) ...")
        self.model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
        print("[ears] measuring room noise, stay quiet for a second ...")
        noise = sd.rec(int(MIC_RATE * 1.0), samplerate=MIC_RATE, channels=1,
                       dtype="float32", device=config.INPUT_DEVICE)
        sd.wait()
        floor = float(np.sqrt(np.mean(noise ** 2)))
        self.threshold = max(floor * config.SPEECH_THRESHOLD_X, 0.005)

    def listen(self, start_timeout=None):
        """Record until the speaker goes quiet. Returns audio, or None if nobody spoke."""
        block = int(MIC_RATE * MIC_BLOCK_S)
        quiet_to_stop = int(config.SILENCE_TO_STOP_S / MIC_BLOCK_S)
        max_blocks = int(config.MAX_LISTEN_S / MIC_BLOCK_S)
        give_up = time.monotonic() + start_timeout if start_timeout else None

        recent, speech = [], []   # recent keeps the start of the first word
        loud_run = quiet_run = 0
        with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32",
                            blocksize=block, device=config.INPUT_DEVICE) as stream:
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


# ============================================================================
# BRAIN (Claude)
# ============================================================================

class Brain:
    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.messages = []

    def reply(self, heard):
        anthropic = self.anthropic
        self.messages.append({"role": "user", "content": heard})
        try:
            response = self.client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=2048,
                system=config.PERSONA,
                messages=self.messages,
                output_config={"effort": config.CLAUDE_EFFORT},
                cache_control={"type": "ephemeral"},
                # If a request is declined, retry it on Anthropic's recommended fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            sys.exit("[brain] Claude rejected the API key. Set ANTHROPIC_API_KEY and try again.")
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


# ============================================================================
# CONVERSATION
# ============================================================================

def respond(crow, body, brain, heard):
    print(f"you:  {heard}")
    crow.eyes(EYES_THINKING)
    crow.neck(random.choice((-90, 90)))  # glance aside while thinking
    reply = brain.reply(heard)
    print(f"crow: {reply}")

    parts = split_reply(reply)
    # Make all the audio first so there are no gaps between sentences
    speech = {i: synthesize(text) for i, (kind, text) in enumerate(parts) if kind == "say"}
    crow.neck(0)
    for i, (kind, value) in enumerate(parts):
        if kind == "say":
            crow.eyes(EYES_TALKING)
            play(crow, *speech[i])
        else:
            body.act(value)


def converse(crow, body, hands_free, typed):
    ears = None if typed else Ears()
    brain = Brain()
    print("\nThe crow is listening. Ctrl+C to quit.")

    while True:
        crow.eyes(EYES_AWAKE)
        body.idle.set()
        if typed:
            heard = input("\nyou> ").strip()
            body.idle.clear()
        else:
            if hands_free:
                crow.eyes(EYES_LISTENING)
            else:
                input("\n[Press Enter, then speak]")
                body.idle.clear()
                crow.neck(0)
                crow.eyes(EYES_LISTENING)
            audio = ears.listen(None if hands_free else config.SPEECH_START_TIMEOUT_S)
            body.idle.clear()
            if audio is None:
                print("(didn't hear anything)")
                continue
            crow.eyes(EYES_THINKING)
            heard = ears.transcribe(audio)

        if re.sub(r"[^a-z ]", "", heard.lower()).strip() in NOT_SPEECH:
            continue
        respond(crow, body, brain, heard)


def test_lipsync(crow, body):
    print("Saying a test line, then two of the original crow sounds ...")
    crow.eyes(EYES_TALKING)
    play(crow, *synthesize("Nevermore. I said nevermore, and I meant every word of it."))
    time.sleep(0.5)
    body.act("squawk")
    time.sleep(0.5)
    body.act("scold")
    time.sleep(1)
    crow.neck(0)
    crow.eyes(EYES_AWAKE)


def list_devices():
    print("Audio devices (> default input, < default output):")
    print(sd.query_devices())
    print("\nSerial ports:")
    for port in serial.tools.list_ports.comports():
        print(f"  {port.device}  {port.description}")


def main():
    parser = argparse.ArgumentParser(description="Talk to the animatronic crow.")
    parser.add_argument("--hands-free", action="store_true", help="listen without pressing Enter")
    parser.add_argument("--type", action="store_true", help="type instead of speaking")
    parser.add_argument("--no-crow", action="store_true", help="run without the Arduino")
    parser.add_argument("--test-lipsync", action="store_true", help="lip sync test, no AI")
    parser.add_argument("--list-devices", action="store_true", help="show audio devices and serial ports")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    crow = Crow(None if args.no_crow else find_nano_port())
    body = Body(crow)
    try:
        if args.test_lipsync:
            test_lipsync(crow, body)
        else:
            converse(crow, body, args.hands_free, args.type)
    except (KeyboardInterrupt, EOFError):
        print("\nCaw. Goodbye.")
    finally:
        sd.stop()
        crow.beak(0)
        crow.neck(0)
        crow.eyes(EYES_AWAKE)
        time.sleep(0.2)  # let the last commands reach the Nano


if __name__ == "__main__":
    main()
