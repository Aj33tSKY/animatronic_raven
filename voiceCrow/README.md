# Voice Crow

Talk to the crow. You speak into the laptop's mic, Claude answers, and the crow
says the answer through its own speaker while its beak, neck and eyes move.

```
 Laptop (crow.py)                                          Crow
 ─────────────────────────────────────────────             ─────────────────────────
 mic ─► Whisper (speech→text) ─► Claude ─► macOS say ─────► headphone jack ─► amp ─► 40mm speaker
                                             │
                          loudness of the speech, 40×/sec
                                             ▼
                          "B62" "N-300" "E4" ── USB ──────► Arduino Nano
                                                             ├─ D9      beak servo (SG90)
                                                             ├─ D4–D7   neck stepper (ULN2003)
                                                             └─ D3      eye LEDs
```

The 3D-printed parts, servo, stepper, LEDs and speaker are the same as in the
[crow build guide](../animatronicCrow/BUILD.md). What changes:

- An **Arduino Nano on a breadboard** replaces the Creature Control PCB.
- A **PAM8403 amplifier** replaces the DFPlayer Mini. The laptop plays all audio,
  including the original squawk MP3s.
- No motion sensor is needed.

| Folder | What it is |
|---|---|
| `firmware/voice-crow-nano/` | Arduino sketch. Moves the crow when the laptop tells it to |
| `laptop/` | Python program. Listens, talks to Claude, speaks, and drives the crow |

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

## 1. Upload the firmware

1. Install the [Arduino IDE](https://www.arduino.cc/en/software/).
2. **Library Manager:** install **AccelStepper** by Mike McCauley. (Servo is built in.)
3. Plug in the Nano. **Tools → Board → Arduino Nano**, and pick its port
   (`/dev/cu.usbserial-…` or `/dev/cu.wchusbserial-…`). If no port appears, install
   the WCH **CH340/CH34x** driver.
4. **Tools → Processor → ATmega328P (Old Bootloader)**. Most clones need this. If the
   upload fails, try the other ATmega328P option.
5. Open `firmware/voice-crow-nano/voice-crow-nano.ino` and click **Upload**.

## 2. Calibrate (same idea as the original build guide)

Open **Tools → Serial Monitor**, set it to **115200 baud** and **Newline**. After a few
seconds of the neck centering, it prints `READY`. Type `?` to list the commands.

**Beak.** Follow the BUILD.md beak steps, but use this sketch's commands:
- Where the guide says `b 1000`, type `U1000` before you fit the servo arm.
- Find your fully open and fully closed values with `U<number>`: the lowest value that
  doesn't pull against the bottom, and the highest that doesn't press the beak shut.
  Small changes matter.
- Put them in `settings.h` as `SERVO_PWM_OPEN` / `SERVO_PWM_CLOSED` and upload again.
- Check with `B0` (closed), `B50`, and `B100` (open).

**Neck.**
- `N-500` and `N500` turn the head each way, and `N0` brings it back to center.
- `S1` switches to fast moves and `S0` back to slow.
- `C` re-centers the head the way it does at startup.
- If fast moves sound grindy or the head ends up off-center, the stepper is skipping.
  Lower `NECK_SPEED_FAST_MAX` and `NECK_SPEED_FAST_ACCEL` in `settings.h`.

**Eyes.** `E1` gives blinking, `E2` a pulse, `E3` a flicker, `E4` steady and `E0` off.

Close the Serial Monitor when you're done. Only one program can use the port at a time.

## 3. Set up the laptop program

In Terminal:

```bash
cd voiceCrow/laptop
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then open .env and paste in your API keys
```

The programs read API keys from `laptop/.env`. Git ignores that file, so the keys
stay on your computer. Fill in only the ones you use; keys set in the Terminal with
`export` take priority over the file.

Each conversation turn costs well under a cent.

Plug the amp's audio cable into the laptop's headphone jack. It shows up as
**External Headphones**: set `OUTPUT_DEVICE = "External Headphones"` in `config.py`
so the crow's voice always goes there. `python crow.py --list-devices` shows all names.

## 4. Try it, one piece at a time

```bash
python crow.py --no-crow --type   # 1. Claude + voice only, no mic and no Arduino needed
python crow.py --test-lipsync     # 2. crow lip-syncs a test line and two squawks, no AI
python crow.py                    # 3. the real thing: press Enter, speak, and it answers
python crow.py --hands-free       # 4. no Enter key; it listens whenever it's quiet
```

The first time you use the mic, macOS asks whether Terminal may use it. Click **Allow**.

### Option: PolyAI Dialog-RSN-1 instead of Claude

`crow_poly.py` uses PolyAI's [Dialog-RSN-1](https://poly.ai/dialog-rsn-1), which listens to
the mic directly. It hears when you start and stop talking and answers in text, so there's
no Enter key and no Whisper. The crow still speaks with the same voice and lip sync. Its
moves are tools the model calls: `caw`, `turn_head` and `shake_head`.

Get a key from the **API Keys** tab at [studio.poly.ai](https://studio.poly.ai), put it
in `.env` as `POLY_API_KEY`, then:

```bash
python crow_poly.py --no-crow --say "Hello crow"   # 1. one typed turn: checks the key
python crow_poly.py --no-crow                       # 2. talk, without the Arduino
python crow_poly.py                                 # 3. the real thing
```

**Talking over Raven.** By default (`ECHO_MODE = "cancel"` in `config.py`) the program
uses echo cancellation, like a video call: everything the crow plays is subtracted from
the mic, so Dialog-RSN-1 hears you but not Raven. You can keep talking while Raven
replies, or interrupt it mid-sentence; it stops at once and listens. It also reports
back to PolyAI how much of each reply you actually heard. In this mode the speaker
plays at 16 kHz, phone-call quality, so the echo canceller gets an exact copy.

If Raven keeps cutting itself off, or answers its own voice, keep the speaker volume
moderate and the laptop's mic away from the crow. Or set `ECHO_MODE = "mute"`: the mic
is then muted while the crow talks (plus `ECHO_TAIL_S`), which is rock solid, but you
can't interrupt. Echo cancellation needs the `livekit` package; without it the program
falls back to muting by itself.

### Option: Wren, PolyAI's agent builder

With Wren set up, Raven becomes a voice interface for
[Wren](https://docs.poly.ai/agent-builder/introduction): ask it to look into a project's
calls, explain how an agent works, or build and edit flows, topics, functions and tests.
Wren stays hidden: Raven presents the work as its own ("I'll change the greeting…",
"I've added two topics", "I couldn't get into that project"), and if asked about Wren,
calls it its best friend and practically its twin.

Before starting anything, Raven reads the task back and asks "Shall I go ahead?"; add or
change things and it reads back the new version. Nothing starts until you clearly say
yes (this is enforced in the code, not just asked of the model). The work takes a few
minutes, so Raven keeps talking with you and reports back at a natural pause. Ask "how's
it going?" at any time. Decisions that come up mid-task are put to you. Edits always go
onto a branch for review; nothing is published to live.

To set it up:
1. In Dialog Studio, create a **personal access token** (Account > Personal access
   tokens). A workspace API key won't work. Put it in `.env` as `POLYAI_PAT`.
2. In `config.py`, fill in `WREN_ACCOUNT_ID` and `WREN_PROJECTS` (a name you'd say
   for each project, mapped to its project ID), and set `WREN_BASE_URL` to your
   region's host if it isn't the default.
3. Check it works without Raven, which also shows Wren's raw events:
   ```bash
   python wren.py --project pizza "What topics does this project have?"
   ```
4. Run `python crow_poly.py` and ask Raven to get Wren to do something.

Every raw Wren event is saved in `laptop/logs/wren-<date>.jsonl` (git ignores it).

If your workspace is regional and the
connection is refused, set `POLY_URL` in `config.py` (or the `DIALOG_REALTIME_URL`
environment variable) to its host. The character is `CHARACTER` in `config.py`,
shared by both programs.

## Tuning

Everything is in `laptop/config.py`:

| Problem | Change |
|---|---|
| Beak moves after the sound | Raise `LIPSYNC_LEAD_S` (try 0.1) |
| Beak moves before the sound | Lower `LIPSYNC_LEAD_S` (try 0) |
| Beak chatters during quiet bits | Raise `BEAK_GATE` |
| Beak opens too wide | Lower `BEAK_MAX_OPEN` |
| Beak motion too jerky or too lazy | `BEAK_SMOOTHING` in `settings.h` (re-upload) |
| `[look left]` turns right | `NECK_FLIP = True` |
| Head too restless, or not lively enough | `NECK_LIFE`: `every` is how often it moves in each state, `reach` how far. `NECK_LIVELY = False` turns it off |
| PolyAI hears the neck moving as you talking | Lower the `rest` row's `reach` and make its `every` slower |
| Want the old pulse/flicker/steady eyes while listening/thinking/talking | `EYES_SHOW_STATE = True` |
| Blinks too often or too rarely | `BLINK_MIN_INTERVAL_MS` / `BLINK_MAX_INTERVAL_MS` in `settings.h` (re-upload) |
| It cuts you off mid-sentence | Raise `SILENCE_TO_STOP_S` |
| It starts listening to background noise | Raise `SPEECH_THRESHOLD_X` |
| Mishears you | `WHISPER_MODEL = "small.en"` (slower, more accurate) |
| Different personality or name | Edit `PERSONA` |
| Different voice | `ELEVENLABS_VOICE_ID` (see below), or `TTS_ENGINE = "say"` and `VOICE` for a Mac voice |
| Voice too flat, or too erratic | `ELEVENLABS_STABILITY`: lower is more expressive, higher is steadier |

Hands-free mode stops listening while the crow talks, so it doesn't hear itself.
If it keeps answering its own echo or the room, use push-to-talk.

### The crow's voice (ElevenLabs)

The crow speaks with [ElevenLabs](https://elevenlabs.io). Put your key in `.env` as
`ELEVENLABS_API_KEY`. If the key is missing, or ElevenLabs fails or runs
out of credit, the crow uses the Mac voice for that line and prints why.

To give it its own voice, open **Voices** on elevenlabs.io and either:
- browse the **Voice Library** for an old, gravelly or theatrical voice, and add it, or
- use **Voice Design** to describe one, e.g. *"an old, raspy, sardonic man with a
  theatrical, gothic delivery"*.

Copy the voice's **Voice ID** into `ELEVENLABS_VOICE_ID` in `config.py`.

**Using Windows or Linux:** the only macOS-specific part is `synthesize_say()` in
`crow.py`, the Mac voice fallback. With `TTS_ENGINE = "elevenlabs"`, the rest
works anywhere.
