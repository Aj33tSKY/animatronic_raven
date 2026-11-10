"""
BOILERPLATE (crow): Raven's body and sound. No need to edit it to build an agent.

The Arduino Nano inside the crow, over USB serial (firmware/wraven-nano).

Sends one-line commands: B<0-100> beak, S<0|1> + N<pos> neck, E<0-4> eyes.
Without a port it just pretends, so everything runs without the crow plugged in.
"""
import sys
import threading
import time

import serial
import serial.tools.list_ports

import settings

# Eye modes, matching the E command in the firmware
EYES_OFF, EYES_AWAKE, EYES_LISTENING, EYES_THINKING, EYES_TALKING = range(5)


class Nano:
    def __init__(self, port):
        self.serial = None
        self.lock = threading.Lock()  # one command at a time down the cable
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
            sys.exit("[crow] The Nano never said READY. Is wraven-nano uploaded?")
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
        if settings.NECK_FLIP:
            position = -position
        self.send(f"S{int(fast)}")
        self.send(f"N{int(position)}")


def find_port():
    if settings.SERIAL_PORT:
        return settings.SERIAL_PORT
    for port in serial.tools.list_ports.comports():
        # CH340 (most clones), FTDI, or genuine Arduino USB chips
        if port.vid in (0x1A86, 0x0403, 0x2341) or "usbserial" in port.device:
            return port.device
    sys.exit("Couldn't find the Nano. Plug it in, or set SERIAL_PORT in settings.py "
             "(see --list-devices), or use --no-crow.")


def list_ports():
    return [f"  {port.device}  {port.description}" for port in serial.tools.list_ports.comports()]
