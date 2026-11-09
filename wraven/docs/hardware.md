# Hardware

The 3D-printed parts, servo, stepper, LEDs and speaker are the same as in the
[original crow build guide](../../animatronicCrow/BUILD.md). What changes:

- An **Arduino Nano on a breadboard** replaces the Creature Control PCB.
- A **small amplifier** replaces the DFPlayer Mini. The laptop plays all the audio,
  including the original crow calls.
- No motion sensor is needed.

```
 laptop ── USB ─────────► Arduino Nano ──► D9 beak servo (SG90)
   │                                    ├─► D4–D7 neck stepper (ULN2003 board)
   │                                    └─► D3 eye LEDs (via 1kΩ)
   └──── headphone jack ─► amplifier ───► 40mm speaker in the crow's body
```

The Nano keeps its firmware and calibration with the power off, so it works with any
laptop that runs `app/start.py`.

---

## Parts beyond the original list

| Qty | Part | Note |
|---|---|---|
| 1 | Arduino Nano (clone is fine) | |
| 1 | ULN2003 stepper driver board | Usually comes in the bag with the 28BYJ-48 |
| 1 | Small amplifier board | Any 1–3W board with a 3.5mm input works (PAM8403, TDA2822, LM386, 8002 …). One with its own 3.5mm jack, volume knob and power supply is easiest |
| 1 | 3.5mm audio cable | Laptop to amp. A plain male-to-male cable if the amp has a jack; otherwise cut one end |
| 1 | 5V power supply, 2A or more | Powers the servo, stepper and amp. A USB power brick plus a USB breakout works |
| 1 | 1kΩ resistor | For the eyes (2.2kΩ for dimmer eyes) |
| 1 | 470–1000µF capacitor, 10V or more | Across the 5V rail. Stops servo spikes from resetting things |
| | Jumper wires | |

---

## Wiring

> **Two rules that prevent most beginner problems:**
> 1. **Don't power the motors from the Nano.** The servo, stepper and amp get their
>    5V from the separate supply. The Nano is powered by USB from the laptop.
> 2. **Connect all the grounds together.** Supply GND, Nano GND, servo, ULN2003 and
>    amp all share the breadboard's − rail. Never connect the supply's +5V to the Nano.

Put the 5V supply on the breadboard power rails (+ and −), then:

| From | To |
|---|---|
| Nano **GND** | − rail |
| Capacitor | + leg (longer) to + rail, − leg (stripe) to − rail, close to the servo/stepper |
| Servo **brown** | − rail |
| Servo **red** | + rail |
| Servo **orange** | Nano **D9** |
| ULN2003 **IN1, IN2, IN3, IN4** | Nano **D4, D5, D6, D7** |
| ULN2003 **+** and **−** | + rail and − rail |
| Stepper plug | ULN2003 socket |
| Nano **D3** | 1kΩ resistor, then the eye LEDs' **+** wire (long legs) |
| Eye LEDs' **−** wire | − rail |
| PAM8403 **5V** and **GND** | + rail and − rail |
| Audio cable **tip** (left) and **sleeve** (ground) | PAM8403 **L** and **⏚** inputs |
| PAM8403 **L+** and **L−** outputs | The two speaker wires |

The amp's speaker outputs are *not* ground. Never connect **L−** to the − rail.
Expect to solder the audio cable and speaker wires to the amp board.

**Amp with its own 3.5mm jack and power supply:** skip the amp rows above. Plug the
laptop into its jack, power it from its own supply (not the breadboard), and connect
the speaker to one channel's output. Start with its volume knob low.

**Big amps (e.g. TDA7297, 2×15W)** can burn out the 3W speaker. Power one from the
lowest supply it runs cleanly on (6–9V caps it near the speaker's rating), keep the
knob low, and connect both speaker wires to one channel's outputs. Neither wire
may touch ground.

**If the speaker hums or buzzes**, you have a ground loop between the laptop and the
5V supply. Unplug the laptop's charger to confirm. Fixes: power just the amp from a
separate USB power bank, or add a $10 "ground loop isolator" to the audio cable.

---

## Upload the firmware

1. Install the [Arduino IDE](https://www.arduino.cc/en/software/).
2. **Library Manager:** install **AccelStepper** by Mike McCauley. (Servo is built in.)
3. Plug in the Nano. **Tools → Board → Arduino Nano**, and pick its port
   (`/dev/cu.usbserial-…` or `/dev/cu.wchusbserial-…`). If no port appears, install
   the WCH **CH340/CH34x** driver.
4. **Tools → Processor → ATmega328P (Old Bootloader)**. Most clones need this. If the
   upload fails, try the other ATmega328P option.
5. Open `firmware/wraven-nano/wraven-nano.ino` and click **Upload**.

## Calibrate (same idea as the original build guide)

Open **Tools → Serial Monitor**, set it to **115200 baud** and **Newline**. After a few
seconds of the neck centering, it prints `READY`. Type `?` to list the commands.

**Beak.** Follow the BUILD.md beak steps, but use this sketch's commands:
- Where the guide says `b 1000`, type `U1000` before you fit the servo arm.
- Find your fully open and fully closed values with `U<number>`: the lowest value that
  doesn't pull against the bottom, and the highest that doesn't press the beak shut.
  Small changes matter.
- Put them in `firmware/wraven-nano/settings.h` as `SERVO_PWM_OPEN` / `SERVO_PWM_CLOSED` and upload again.
- Check with `B0` (closed), `B50`, and `B100` (open).

**Neck.**
- `N-500` and `N500` turn the head each way, and `N0` brings it back to center.
- `S1` switches to fast moves and `S0` back to slow.
- `C` re-centers the head the way it does at startup.
- If fast moves sound grindy or the head ends up off-center, the stepper is skipping.
  Lower `NECK_SPEED_FAST_MAX` and `NECK_SPEED_FAST_ACCEL` in `firmware/wraven-nano/settings.h`,
  and set `NECK_FAST` in `app/settings.py` to match.

**Eyes.** `E1` gives blinking, `E2` a pulse, `E3` a flicker, `E4` steady and `E0` off.

Close the Serial Monitor when you're done. Only one program can use the port at a time.
