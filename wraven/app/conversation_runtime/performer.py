"""
The Performer speaks and moves, in order, on its own thread, so the
conversation never waits on the crow.

Jobs are queued with add(kind, value, reply_id):
  "say"    a sentence: its audio starts being made straight away, so the next
           sentence is usually ready by the time the current one finishes
  "act"    a move for hardware/body.py ("look left", "shake", "eyes pulse"...)
  "sound"  one of the original crow calls ("squawk" or "scold")

It also tells Dialog-RSN-1 how much of each reply has actually been heard (the
poly.output_audio reports), and stops at once if the person interrupts.
"""
import queue
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import soundfile as sf

import settings
from audio.lipsync import play
from audio.speaker import SPEAKER_RATE, seconds_since_sound, speaker
from integrations.elevenlabs import synthesize


class Performer:
    def __init__(self, nano, body):
        self.nano = nano
        self.body = body
        self.jobs = queue.Queue()
        self.voice = ThreadPoolExecutor(max_workers=2)
        self.busy = threading.Event()   # set while anything is queued or being performed
        self.heard_at = None            # when the person stopped talking, for the timing printout
        self.first_text_s = None        # how long the model took to start answering
        self.report = lambda event: None  # sends a poly.output_audio event; set by the session
        self.lock = threading.Lock()
        self.cancelled = set()          # replies the person interrupted: drop what's left of them
        self.current = None             # (reply id, sentence) playing right now
        self.user_speaking = False      # Dialog-RSN-1 hears the person talking right now
        self.user_turns = 0             # how many times they've spoken (for read-back confirmation)
        self.reply_active = False       # Dialog-RSN-1 is writing a reply right now
        self.progress = {}              # reply id -> what's been played and reported
        threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._report_playback, daemon=True).start()

    def add(self, kind, value, reply_id=None):
        with self.lock:
            if reply_id in self.cancelled:
                return  # a late piece of a reply that was interrupted
            self.busy.set()
            if kind == "say":
                value = (value, self.voice.submit(synthesize, value, SPEAKER_RATE))
            self.jobs.put((kind, value, reply_id))

    def mic_should_listen(self):
        # Mute mode only: mute the mic while sound is actually coming out of the
        # crow, plus a moment for the echo to die away, so the model doesn't hear
        # the crow and think the person is talking.
        return seconds_since_sound() > settings.ECHO_TAIL_S

    def interrupt(self):
        """The person started talking over Raven: stop now and drop the rest of the reply."""
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
                if reply_id in self.cancelled:
                    continue
                if kind == "say":
                    self._say(*value, reply_id)
                elif kind == "sound":
                    self._sound(value)
                else:
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

    def _say(self, text, audio, reply_id):
        samples, rate = audio.result()
        if reply_id in self.cancelled:
            return
        self._print_timing()
        self.body.set_state("talk")
        with self.lock:
            self.current = (reply_id, text)
        clip = play(self.nano, samples, rate)
        with self.lock:
            self.current = None
            if reply_id not in self.cancelled and clip is not None:
                progress = self._progress(reply_id)
                progress["played_ms"] += clip.played_ms
                progress["spoken"] += text + " "

    def _sound(self, kind):
        """One of the original crow calls, with the beak moving to it."""
        choices = settings.SCOLD_SOUNDS if kind == "scold" else settings.SQUAWK_SOUNDS
        samples, rate = sf.read(settings.SOUNDS_DIR / f"{random.choice(choices):04d}.mp3",
                                dtype="float32")
        self.body.set_state("talk")
        play(self.nano, samples, rate)

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
        """Every 250 ms, tell Dialog-RSN-1 how far into the current reply the person is."""
        while True:
            time.sleep(0.25)
            try:
                self._report_once()
            except Exception as error:  # reporting must never stop the conversation
                print(f"[report] {error}")

    def _report_once(self):
        with self.lock:
            if not self.current or self.current[0] is None:
                return
            reply_id = self.current[0]
            progress = self._progress(reply_id)
            if progress["stopped"]:
                return
            audio_ms, spoken = self._heard(reply_id)
            if audio_ms == 0:
                return
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
