#!/usr/bin/env python3
"""
Wraven: talk to the animatronic raven, powered by PolyAI's Dialog-RSN-1.

    python start.py                       talk to Raven
    python start.py --no-crow             without the Arduino plugged in
    python start.py --say "Hello"         a typed turn instead of the mic;
                                          repeat --say for a whole conversation
    python start.py --test-sound          a test line and two crow calls with lip sync, no AI
    python start.py --list-devices        audio devices and serial ports

Settings: settings.py   Prompts: prompts/   Knowledge: knowledge/   Tools: tools/
"""
import argparse
import asyncio
import time

import sounddevice as sd
import websockets

from audio.speaker import stop_sound
from hardware.body import Body
from hardware.nano import Nano, find_port, list_ports


def test_sound(nano, body):
    from audio.lipsync import play
    from audio.speaker import SPEAKER_RATE
    from conversation_runtime.performer import Performer
    from integrations.elevenlabs import synthesize
    print("Saying a test line, then two of the original crow calls ...")
    body.set_state("talk")
    play(nano, *synthesize("Nevermore. I said nevermore, and I meant every word of it.", SPEAKER_RATE))
    performer = Performer(nano, body)
    for kind in ("squawk", "scold"):
        time.sleep(0.5)
        if kind == "scold":
            performer.add("act", "scold")
        performer.add("sound", kind)
        while performer.busy.is_set():
            time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Talk to Raven, powered by Dialog-RSN-1.")
    parser.add_argument("--no-crow", action="store_true", help="run without the Arduino")
    parser.add_argument("--say", metavar="TEXT", action="append",
                        help="a typed turn instead of the mic; repeat for several turns")
    parser.add_argument("--test-sound", action="store_true", help="lip sync and crow calls, no AI")
    parser.add_argument("--list-devices", action="store_true", help="show audio devices and serial ports")
    args = parser.parse_args()

    if args.list_devices:
        print("Audio devices (> default input, < default output):")
        print(sd.query_devices())
        print("\nSerial ports:")
        print("\n".join(list_ports()) or "  (none)")
        return

    nano = Nano(None if args.no_crow else find_port())
    body = Body(nano)
    try:
        if args.test_sound:
            test_sound(nano, body)
        else:
            from conversation_runtime.session import run
            asyncio.run(run(nano, body, args.say))
    except KeyboardInterrupt:
        print("\nCaw. Goodbye.")
    except websockets.ConnectionClosed as closed:
        print(f"[poly] connection closed: {closed}")
    finally:
        body.set_state("still")
        stop_sound()
        nano.beak(0)
        nano.neck(0)
        time.sleep(0.2)  # let the last commands reach the Nano


if __name__ == "__main__":
    main()
