"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The body: living neck per state, deliberate looks, and eye effects."""
import time

import settings
from hardware.body import Body


def fast(monkeypatch, hold=0.4):
    """Speed the living neck up 10x so the test takes seconds."""
    life = {state: {**value, "every": (value["every"][0] / 10, value["every"][1] / 10),
                    "first": value["first"] / 10} for state, value in settings.NECK_LIFE.items()}
    monkeypatch.setattr(settings, "NECK_LIFE", life)
    monkeypatch.setattr(settings, "NECK_HOLD_AFTER_LOOK_S", hold)
    monkeypatch.setattr(settings, "EYE_EFFECT_S", 0.4)


def neck_positions(nano, since):
    return [int(command[1:]) for at, command in nano.sent if at >= since and command.startswith("N")]


def test_living_neck_stays_within_each_states_reach(nano, monkeypatch):
    fast(monkeypatch)
    body = Body(nano)
    for state in ("rest", "listen", "think", "talk"):
        start = time.monotonic()
        body.set_state(state)
        time.sleep(1.2)
        moves = neck_positions(nano, start)
        assert moves and all(abs(n) <= settings.NECK_LIFE[state]["reach"] for n in moves), state
    start = time.monotonic()
    body.set_state("still")
    time.sleep(0.6)
    assert not neck_positions(nano, start + 0.1)


def test_a_look_far_left_then_right_waits_then_turns_back(nano, monkeypatch):
    fast(monkeypatch)
    monkeypatch.setattr(settings, "NECK_LIFE", {})  # no living moves, to see only the looks
    body = Body(nano)
    body.set_state("rest")
    start = time.monotonic()
    body.act("look far left")
    body.act("look far right")
    time.sleep(2.6)
    sent = [(round(at - start, 1), int(c[1:])) for at, c in nano.sent if at >= start and c.startswith("N")]
    assert [n for _, n in sent] == [-630, 630, 0]
    assert sent[1][0] >= 1.0  # far right waited for far left to arrive


def test_eyes_blink_by_default_and_effects_wear_off(nano, monkeypatch):
    fast(monkeypatch)
    body = Body(nano)
    for state in ("listen", "think", "talk", "rest"):
        body.set_state(state)
    assert nano.commands("E") == ["E1"]  # always blinking, sent once
    body.act("eyes flicker")
    time.sleep(0.6)
    assert nano.commands("E") == ["E1", "E3", "E1"]
