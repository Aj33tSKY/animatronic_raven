# Tuning

What to change when something feels off. Settings are in `app/settings.py` unless
noted; firmware settings are in `firmware/wraven-nano/settings.h` and need uploading
again from the Arduino IDE.

## Beak and lip sync

| Problem | Change |
|---|---|
| Beak moves after the sound | Raise `LIPSYNC_LEAD_S` (try 0.1) |
| Beak moves before the sound | Lower `LIPSYNC_LEAD_S` (try 0) |
| Beak chatters during quiet bits | Raise `BEAK_GATE` |
| Beak opens too wide | Lower `BEAK_MAX_OPEN` |
| Beak doesn't close fully, or strains | Recalibrate `SERVO_PWM_OPEN` / `SERVO_PWM_CLOSED` (firmware; see [hardware.md](hardware.md)) |
| Beak motion too jerky or too lazy | `BEAK_SMOOTHING` (firmware) |

## Neck and eyes

| Problem | Change |
|---|---|
| "Look left" turns right | `NECK_FLIP = True` |
| Head too restless, or not lively enough | `NECK_LIFE`: `every` is how often it moves in each state, `reach` how far. `NECK_LIVELY = False` turns it off |
| Dialog-RSN-1 hears the neck moving as you talking | Lower the `rest` row's `reach` and make its `every` slower |
| Head drifts off-centre over time | It's skipping steps: lower `NECK_SPEED_FAST_MAX` (firmware) and `NECK_FAST` to match. Type `C` in the Serial Monitor to re-centre |
| Want pulse/flicker/steady eyes while listening/thinking/talking | `EYES_SHOW_STATE = True` |
| Blinks too often or too rarely | `BLINK_MIN_INTERVAL_MS` / `BLINK_MAX_INTERVAL_MS` (firmware) |

## Voice

| Problem | Change |
|---|---|
| Too loud or too quiet | `SPEAKER_VOLUME` (0–1), or the amp's knob |
| Different voice | `ELEVENLABS_VOICE_ID`. On elevenlabs.io open **Voices** and copy a voice's ID (library voices need a paid plan) |
| Voice too flat, or too erratic | `ELEVENLABS_STABILITY`: lower is more expressive, higher is steadier |
| Too slow to start speaking | `ELEVENLABS_MODEL = "eleven_flash_v2_5"` is the fastest |
| `[voice] ElevenLabs is unavailable` | Out of credit, or the key was refused. Raven switches to the free Piper voice (on this laptop, just as quick) for the rest of the conversation |
| `[voice] ElevenLabs failed` | A one-off problem; just that sentence uses the Piper voice |
| A different backup voice | `PIPER_VOICE`: pick one at [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/); it downloads on first use. `TTS_ENGINE = "piper"` skips ElevenLabs altogether |

## Conversation

| Problem | Change |
|---|---|
| Raven cuts itself off, or answers its own voice | Lower the volume, move the mic away from the crow, or `ECHO_MODE = "mute"` (no interrupting, but rock solid) |
| It answers its own echo in mute mode | Raise `ECHO_TAIL_S` |
| It replies before you've finished | Dialog-RSN-1 decides; steer it in `prompts/4-turn-taking.md`. Pausing after a complete sentence reads as finished |
| Personality, style, games | Edit the files in `app/prompts/` |
| It gets a fact wrong | Add or fix a topic in `app/knowledge/` |
| Connection refused (401) | Check `POLY_API_KEY` in `.env`, and that no old key is `export`ed in the Terminal. Regional workspaces need `POLY_URL` set |
