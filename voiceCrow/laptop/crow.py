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
        self.eye_mode = None
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
        if mode != self.eye_mode:  # resending would interrupt a blink
            self.eye_mode = mode
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
# MOUTH (text to speech, the speaker, and lip sync)
# ============================================================================

# Echo cancellation needs the speaker at the mic's rate: 16 kHz, phone-call
# quality, which is plenty for a 40mm speaker. Without it, play at 24 kHz.
SPEAKER_RATE = 16000 if config.ECHO_MODE == "cancel" else 24000
SPEAKER_BLOCK = SPEAKER_RATE // 50  # 20 ms

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
        params={"output_format": f"pcm_{SPEAKER_RATE}"},  # raw PCM; 44.1 kHz needs a Pro plan
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
    return samples, SPEAKER_RATE


def synthesize_say(text):
    """Turn text into audio with the macOS `say` command."""
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "speech.txt"
        wav_file = Path(tmp) / "speech.wav"
        text_file.write_text(text)
        subprocess.run(["say", "-v", config.VOICE, "-r", str(config.VOICE_RATE),
                        "--file-format=WAVE", f"--data-format=LEI16@{SPEAKER_RATE}",
                        "-o", str(wav_file), "-f", str(text_file)], check=True)
        samples, rate = sf.read(wav_file, dtype="float32")
    return samples, rate


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
    """Keeps one output stream to the crow's speaker open. Sounds play through it
    one at a time and can be stopped part-way. Everything that comes out, silence
    included, is also passed to `on_output`: that's the echo canceller's reference."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clip = None
        self.on_output = None
        self.quiet_since = 0.0
        self.stream = sd.OutputStream(samplerate=SPEAKER_RATE, channels=1, dtype="float32",
                                      blocksize=SPEAKER_BLOCK, device=config.OUTPUT_DEVICE,
                                      callback=self._fill)
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


def play(crow, samples, rate):
    """Play audio through the crow's speaker while the beak follows its loudness.
    Returns the Clip; it ends early (clip.stopped) if someone interrupts."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = resample(samples.astype(np.float32), rate, SPEAKER_RATE)
    envelope = beak_envelope(samples, SPEAKER_RATE)
    frame_s = 1 / config.LIPSYNC_FPS

    out = speaker()
    clip = out.start(samples * config.SPEAKER_VOLUME)
    clip.started.wait(timeout=2)
    last_value, last_sent = None, 0.0
    while not clip.stopped and clip.started_at is not None:
        now = time.monotonic()
        frame = int((now - clip.started_at - out.latency + config.LIPSYNC_LEAD_S) / frame_s)
        if frame >= len(envelope):
            break
        if frame >= 0:
            value = int(envelope[frame])
            # Resend now and then: the Nano closes the beak if it hears nothing
            if value != last_value or now - last_sent > 0.2:
                crow.beak(value)
                last_value, last_sent = value, now
        time.sleep(frame_s / 2)
    clip.finished.wait(timeout=2)
    crow.beak(0)
    return clip


# ============================================================================
# BODY LANGUAGE (moves from tags or tools, plus a "living" neck and eyes)
# ============================================================================

# Eyes for each state, used when config.EYES_SHOW_STATE is True
STATE_EYES = {"rest": EYES_AWAKE, "listen": EYES_LISTENING, "think": EYES_THINKING,
              "talk": EYES_TALKING, "still": EYES_AWAKE}
# Head positions for a "no" shake, ending facing the person
SHAKE = (-100, 100, -100, 0)
# Eye effects Raven can ask for with a tag or tool
EYE_EFFECTS = {"eyes pulse": EYES_LISTENING, "eyes flicker": EYES_THINKING,
               "eyes glare": EYES_TALKING, "eyes closed": EYES_OFF}


class Body:
    """Raven's body language. Call set_state() as Raven rests, listens, thinks and
    talks: the eyes follow it, and the head makes small movements of its own."""

    def __init__(self, crow):
        self.crow = crow
        self.state = "still"            # "still" = no movements of its own
        self.state_changed = threading.Event()
        self.neck_free_at = 0.0         # living neck pauses until then after a deliberate look
        self.return_home = False        # after that pause, turn back to face the person
        self.neck_target = 0            # where the head was last sent
        self.look_arrives_at = 0.0      # when the last deliberate look reaches its target
        self.eyes_free_at = 0.0         # state eyes pause until then during an eye effect
        threading.Thread(target=self._live, daemon=True).start()

    def set_state(self, state):
        """'rest', 'listen', 'think', 'talk', or 'still'."""
        if state != self.state:
            self.state = state
            self.state_changed.set()
        self._show_state_eyes()

    def face_person(self):
        """Look straight at whoever is talking, and stay that way for a moment.
        Never waits, because the PolyAI event loop calls it."""
        self.neck_free_at = time.monotonic() + 1.5
        self.return_home = False
        self._neck(0)

    def act(self, tag):
        side = config.NECK_SIDE
        if tag == "squawk":
            self.play_track(random.choice(config.SQUAWK_TRACKS))
        elif tag == "scold":
            self._look(random.randint(-side // 5, side // 5))
            self.play_track(random.choice(config.SCOLD_TRACKS))
        elif tag == "look left":
            self._look(-int(side * 0.6))
        elif tag == "look right":
            self._look(int(side * 0.6))
        elif tag == "look far left":
            self._look(-int(side * 0.9))
        elif tag == "look far right":
            self._look(int(side * 0.9))
        elif tag in ("look at you", "look center"):
            self._look(0, fast=False)
        elif tag == "shake":
            self.neck_free_at = time.monotonic() + 2.5 + config.NECK_HOLD_AFTER_LOOK_S
            self.return_home = False  # a shake already ends facing the person
            threading.Thread(target=self._shake, daemon=True).start()
        elif tag in EYE_EFFECTS:
            self.eyes_free_at = time.monotonic() + config.EYE_EFFECT_S
            self.crow.eyes(EYE_EFFECTS[tag])
            threading.Timer(config.EYE_EFFECT_S + 0.05, self._show_state_eyes).start()
        else:
            print(f"[body] unknown tag [{tag}], ignoring")

    def play_track(self, number):
        path = config.MP3_DIR / f"{number:04d}.mp3"
        samples, rate = sf.read(path, dtype="float32")
        self.set_state("talk")
        play(self.crow, samples, rate)

    def _look(self, position, fast=True, hold=None):
        # Let a previous deliberate look arrive first, so "left, then right"
        # really goes all the way left before turning right
        time.sleep(max(0.0, self.look_arrives_at - time.monotonic()))
        travel = self._travel_time(abs(position - self.neck_target), fast)
        self.look_arrives_at = time.monotonic() + travel
        self.neck_free_at = self.look_arrives_at + (config.NECK_HOLD_AFTER_LOOK_S if hold is None else hold)
        self.return_home = position != 0  # turn back to face the person once the hold is over
        self._neck(position, fast)

    def _neck(self, position, fast=False):
        self.neck_target = position
        self.crow.neck(position, fast=fast)

    @staticmethod
    def _travel_time(steps, fast):
        """Roughly how long the Nano takes to move this far (accelerate, cruise, slow down)."""
        top_speed, accel = config.NECK_FAST if fast else config.NECK_SLOW
        ramp = top_speed ** 2 / accel  # steps spent speeding up plus slowing down
        if steps < ramp:
            return 2 * (steps / accel) ** 0.5
        return 2 * top_speed / accel + (steps - ramp) / top_speed

    def _shake(self):
        for position in SHAKE:
            travel = self._travel_time(abs(position - self.neck_target), fast=True)
            self._neck(position, fast=True)
            time.sleep(travel)  # let each swing finish before reversing

    def _show_state_eyes(self):
        if time.monotonic() < self.eyes_free_at:
            return  # an eye effect is still playing; its timer calls this again
        self.crow.eyes(STATE_EYES[self.state] if config.EYES_SHOW_STATE else EYES_AWAKE)

    def _live(self):
        """Small head movements of its own, different for each state."""
        next_move = 0.0
        while True:
            if self.state_changed.wait(timeout=0.1):
                self.state_changed.clear()
                if self.state in config.NECK_LIFE:
                    next_move = time.monotonic() + config.NECK_LIFE[self.state]["first"]
            now = time.monotonic()
            if self.state == "still" or now < self.neck_free_at:
                continue
            if self.return_home:
                # A deliberate look is over: turn back to face the person
                self.return_home = False
                self._neck(0)
                if self.state in config.NECK_LIFE:
                    next_move = now + random.uniform(*config.NECK_LIFE[self.state]["every"])
                continue
            if not config.NECK_LIVELY or self.state not in config.NECK_LIFE or now < next_move:
                continue
            life = config.NECK_LIFE[self.state]
            reach = life["reach"]
            if self.state == "think":
                # Look away to one side, as if deciding what to say
                target = random.choice((-1, 1)) * random.uniform(0.5, 1.0) * reach
            else:
                # Mostly small moves near the middle, now and then a bigger one
                target = random.gauss(0, reach / 2)
            self._neck(int(max(-reach, min(reach, target))))
            next_move = now + random.uniform(*life["every"])


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
    body.set_state("think")
    reply = brain.reply(heard)
    print(f"crow: {reply}")

    parts = split_reply(reply)
    # Make all the audio first so there are no gaps between sentences
    speech = {i: synthesize(text) for i, (kind, text) in enumerate(parts) if kind == "say"}
    body.set_state("talk")
    for i, (kind, value) in enumerate(parts):
        if kind == "say":
            body.set_state("talk")
            play(crow, *speech[i])
        else:
            body.act(value)


def converse(crow, body, hands_free, typed):
    ears = None if typed else Ears()
    brain = Brain()
    print("\nThe crow is listening. Ctrl+C to quit.")

    while True:
        body.set_state("rest")
        if typed:
            heard = input("\nyou> ").strip()
        else:
            if not hands_free:
                input("\n[Press Enter, then speak]")
                body.face_person()
                body.set_state("listen")
            audio = ears.listen(None if hands_free else config.SPEECH_START_TIMEOUT_S)
            if audio is None:
                print("(didn't hear anything)")
                continue
            body.set_state("think")
            heard = ears.transcribe(audio)

        if re.sub(r"[^a-z ]", "", heard.lower()).strip() in NOT_SPEECH:
            continue
        respond(crow, body, brain, heard)


def test_lipsync(crow, body):
    print("Saying a test line, then two of the original crow sounds ...")
    body.set_state("talk")
    play(crow, *synthesize("Nevermore. I said nevermore, and I meant every word of it."))
    time.sleep(0.5)
    body.act("squawk")
    time.sleep(0.5)
    body.act("scold")
    time.sleep(1)
    body.set_state("still")
    crow.neck(0)


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
        body.set_state("still")
        stop_sound()
        crow.beak(0)
        crow.neck(0)
        time.sleep(0.2)  # let the last commands reach the Nano


if __name__ == "__main__":
    main()
