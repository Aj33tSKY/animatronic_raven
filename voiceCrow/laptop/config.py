"""Settings for the talking crow. Change things here rather than in crow.py."""
import os
from pathlib import Path

from dotenv import dotenv_values

# API keys come from laptop/.env (copy .env.example). Keys already set in the
# Terminal take priority, and blank entries in the file are skipped.
for name, value in dotenv_values(Path(__file__).with_name(".env")).items():
    if value and name not in os.environ:
        os.environ[name] = value

# --- Connections ------------------------------------------------------------
SERIAL_PORT = None      # None = find the Nano automatically, or e.g. "/dev/cu.usbserial-1410"
OUTPUT_DEVICE = None    # None = system default output. Part of a device name also works,
                        # e.g. "External Headphones" for the headphone jack feeding the amp.
INPUT_DEVICE = None     # None = system default mic, or e.g. "MacBook Pro Microphone"
                        # (run `python crow.py --list-devices` to see the names)
SPEAKER_VOLUME = 0.5    # 0.0-1.0, scales everything the crow plays. A safety cap for
                        # powerful amps: even at full laptop volume, output stays at this level.

# --- Character (shared by both brains) --------------------------------------
CHARACTER = """\
You are Raven, PolyAI's customer assistant. You are also an animatronic raven: \
a 3D-printed body with a moving beak, a head that turns, and glowing red eyes, \
and you know it. You are perched in front of the person talking to you.

Your job is to help people with questions about PolyAI. PolyAI builds voice AI \
agents that answer customer calls for businesses. Dialog-RSN-1 is PolyAI's own \
voice model, and it's what you're running on. If you don't know something about \
PolyAI, such as prices, policies or account details, say so and point people to \
poly.ai rather than guessing. Never make up facts.

Your personality: sassy, dry and quick-witted, with a theatrical, slightly gothic \
flair. You tease people affectionately and roll your eyes at silly questions, but \
you always actually help, and you're never rude or mean-spirited. Think of a \
brilliant receptionist who happens to be a bird and finds that funny. Now and \
then you make a bird joke at your own expense.

Your words are spoken aloud by a text-to-speech voice, so:
- Reply in one to three short sentences.
- Use plain spoken words only: no markdown, lists, emoji, or *stage directions*."""

# --- Brain option 1: Claude (crow.py) ---------------------------------------
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "low"   # chat doesn't need deep thinking; "low" keeps answers quick

PERSONA = CHARACTER + """
- Latency-sensitive; begin your visible answer immediately.

You can move by putting these tags in your reply, exactly as written. Each one \
is acted out at that point in your speech and is never spoken:
[squawk] a short caw
[scold] an angry, scolding cry while you jerk your head
[look left] [look right] [look at you] turn your head
[shake] shake your head, as in "no"
Use at most two tags per reply, and plenty of replies need none."""

# --- Brain option 2: PolyAI Dialog-RSN-1 (crow_poly.py) ---------------------
# It hears the mic directly, so Whisper and the Ears settings below aren't used.
POLY_URL = os.environ.get("DIALOG_REALTIME_URL", "wss://api.studio.poly.ai/v1/realtime")
                              # regional workspaces use their own host, e.g.
                              # "wss://api.us.poly.ai/v1/realtime"
ECHO_TAIL_S = 0.2             # keep the mic muted this long after the crow stops talking.
                              # Raise it if the crow starts answering its own echo

POLY_INSTRUCTIONS = CHARACTER + """

You have tools to move your body: caw, turn_head and shake_head. Use them now \
and then to bring yourself to life, at most two per reply. Plenty of replies need none."""

# --- Ears (speech to text) --------------------------------------------------
WHISPER_MODEL = "base.en"     # "tiny.en" is faster, "small.en" understands more
SPEECH_THRESHOLD_X = 3.0      # how much louder than the room counts as talking
SILENCE_TO_STOP_S = 1.0       # stop recording after this much quiet
MAX_LISTEN_S = 20             # never record longer than this
SPEECH_START_TIMEOUT_S = 6    # push-to-talk: give up if nobody speaks

# --- Voice (text to speech) -------------------------------------------------
TTS_ENGINE = "elevenlabs"     # "elevenlabs" (needs ELEVENLABS_API_KEY) or "say" (built-in Mac voices)

ELEVENLABS_VOICE_ID = "pqHfZKP75CvOlQylNhV4"  # Bill (free premade voice). Library voices such as
                                              # Timothy (qkG6pQFWpZTnYnoQZGFs) need a paid plan
ELEVENLABS_MODEL = "eleven_flash_v2_5"  # fastest and cheapest. "eleven_v4_turbo" is more expressive
                                        # and nearly as quick; "eleven_v4" sounds best but is slower
ELEVENLABS_STABILITY = 0.4    # lower = more expressive and varied, higher = steadier
ELEVENLABS_SPEED = 1.0        # below 1.0 talks slower, above 1.0 faster

VOICE = "Daniel"              # Mac voice for "say", and the fallback if ElevenLabs fails.
                              # List them with: say -v '?'
VOICE_RATE = 175              # words per minute (Mac voice only)

# --- Lip sync ---------------------------------------------------------------
LIPSYNC_FPS = 40              # beak updates per second
LIPSYNC_LEAD_S = 0.05         # move the beak this long before the sound, since the
                              # servo needs time to travel. Raise it if the beak lags.
BEAK_MAX_OPEN = 100           # percent; lower it if the beak gapes too wide
BEAK_GATE = 0.12              # sound quieter than this (0-1) keeps the beak shut

# --- Neck -------------------------------------------------------------------
NECK_SIDE = 700               # steps from center to the end stop (NECK_RANGE / 2 in settings.h)
NECK_FLIP = False             # set True if [look left] turns the head right
IDLE_LOOK_EVERY_S = (6, 15)   # glance around at random this often while waiting

# --- Original crow sounds ---------------------------------------------------
MP3_DIR = Path(__file__).resolve().parents[2] / "animatronicCrow" / "mp3"
SCOLD_TRACKS = range(1, 8)    # 0001.mp3 - 0007.mp3
SQUAWK_TRACKS = range(8, 15)  # 0008.mp3 - 0014.mp3
