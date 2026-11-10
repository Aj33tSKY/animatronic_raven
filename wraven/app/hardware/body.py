"""
BOILERPLATE (crow): Raven's body and sound. No need to edit it to build an agent.

How Raven's body behaves: deliberate moves (from tools), a "living" neck that
moves by itself, and eyes that blink (or follow what Raven is doing).

Call set_state() as Raven rests, listens, thinks and talks. Sounds (crow calls,
speech) are played elsewhere; this file only moves the head and eyes.
"""
import random
import threading
import time

import settings
from hardware.nano import (EYES_AWAKE, EYES_LISTENING, EYES_OFF, EYES_TALKING,
                           EYES_THINKING)

# Eyes for each state, used when settings.EYES_SHOW_STATE is True
STATE_EYES = {"rest": EYES_AWAKE, "listen": EYES_LISTENING, "think": EYES_THINKING,
              "talk": EYES_TALKING, "still": EYES_AWAKE}
# Eye effects a tool can ask for
EYE_EFFECTS = {"eyes pulse": EYES_LISTENING, "eyes flicker": EYES_THINKING,
               "eyes glare": EYES_TALKING, "eyes closed": EYES_OFF}
# Head positions for a "no" shake, ending facing the person
SHAKE = (-100, 100, -100, 0)


class Body:
    def __init__(self, nano):
        self.nano = nano
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
        Never waits, because the conversation's event loop calls it."""
        self.neck_free_at = time.monotonic() + 1.5
        self.return_home = False
        self._neck(0)

    def act(self, move):
        """A deliberate move: 'look left', 'look far right', 'look at you', 'scold'
        (a jerk of the head), 'shake', or an eye effect like 'eyes pulse'."""
        side = settings.NECK_SIDE
        if move == "scold":
            self._look(random.randint(-side // 5, side // 5))
        elif move == "look left":
            self._look(-int(side * 0.6))
        elif move == "look right":
            self._look(int(side * 0.6))
        elif move == "look far left":
            self._look(-int(side * 0.9))
        elif move == "look far right":
            self._look(int(side * 0.9))
        elif move in ("look at you", "look center"):
            self._look(0, fast=False)
        elif move == "shake":
            self.neck_free_at = time.monotonic() + 2.5 + settings.NECK_HOLD_AFTER_LOOK_S
            self.return_home = False  # a shake already ends facing the person
            threading.Thread(target=self._shake, daemon=True).start()
        elif move in EYE_EFFECTS:
            self.eyes_free_at = time.monotonic() + settings.EYE_EFFECT_S
            self.nano.eyes(EYE_EFFECTS[move])
            threading.Timer(settings.EYE_EFFECT_S + 0.05, self._show_state_eyes).start()
        else:
            print(f"[body] unknown move {move!r}, ignoring")

    def _look(self, position, fast=True, hold=None):
        # Let a previous deliberate look arrive first, so "left, then right"
        # really goes all the way left before turning right
        time.sleep(max(0.0, self.look_arrives_at - time.monotonic()))
        travel = self._travel_time(abs(position - self.neck_target), fast)
        self.look_arrives_at = time.monotonic() + travel
        self.neck_free_at = self.look_arrives_at + (settings.NECK_HOLD_AFTER_LOOK_S if hold is None else hold)
        self.return_home = position != 0  # turn back to face the person once the hold is over
        self._neck(position, fast)

    def _neck(self, position, fast=False):
        self.neck_target = position
        self.nano.neck(position, fast=fast)

    @staticmethod
    def _travel_time(steps, fast):
        """Roughly how long the Nano takes to move this far (accelerate, cruise, slow down)."""
        top_speed, accel = settings.NECK_FAST if fast else settings.NECK_SLOW
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
        self.nano.eyes(STATE_EYES[self.state] if settings.EYES_SHOW_STATE else EYES_AWAKE)

    def _live(self):
        """Small head movements of its own, different for each state."""
        next_move = 0.0
        while True:
            if self.state_changed.wait(timeout=0.1):
                self.state_changed.clear()
                if self.state in settings.NECK_LIFE:
                    next_move = time.monotonic() + settings.NECK_LIFE[self.state]["first"]
            now = time.monotonic()
            if self.state == "still" or now < self.neck_free_at:
                continue
            if self.return_home:
                # A deliberate look is over: turn back to face the person
                self.return_home = False
                self._neck(0)
                if self.state in settings.NECK_LIFE:
                    next_move = now + random.uniform(*settings.NECK_LIFE[self.state]["every"])
                continue
            if not settings.NECK_LIVELY or self.state not in settings.NECK_LIFE or now < next_move:
                continue
            life = settings.NECK_LIFE[self.state]
            reach = life["reach"]
            if self.state == "think":
                # Look away to one side, as if deciding what to say
                target = random.choice((-1, 1)) * random.uniform(0.5, 1.0) * reach
            else:
                # Mostly small moves near the middle, now and then a bigger one
                target = random.gauss(0, reach / 2)
            self._neck(int(max(-reach, min(reach, target))))
            next_move = now + random.uniform(*life["every"])
