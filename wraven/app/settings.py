"""
Wraven's settings: the knobs you might turn. Prompts are in prompts/, knowledge in
knowledge/, tools in tools/. API keys go in .env (copy .env.example).
"""
import os
from pathlib import Path

from dotenv import dotenv_values

APP_DIR = Path(__file__).resolve().parent

# API keys come from .env. Keys already set in the Terminal take priority, and
# blank entries in the file are skipped.
for name, value in dotenv_values(APP_DIR / ".env").items():
    if value and name not in os.environ:
        os.environ[name] = value


# --- Where things live -------------------------------------------------------
PROMPTS_DIR = APP_DIR / "prompts"       # what Raven is told
KNOWLEDGE_DIR = APP_DIR / "knowledge"   # what Raven knows
LOGS_DIR = APP_DIR / "logs"             # raw project-work events (git ignores it)
SOUNDS_DIR = APP_DIR.parents[1] / "animatronicCrow" / "mp3"   # the original crow calls
SCOLD_SOUNDS = range(1, 8)              # 0001.mp3 - 0007.mp3
SQUAWK_SOUNDS = range(8, 15)            # 0008.mp3 - 0014.mp3


# --- Dialog-RSN-1 (PolyAI) ---------------------------------------------------
POLY_URL = os.environ.get("DIALOG_REALTIME_URL", "wss://api.studio.poly.ai/v1/realtime")
                              # regional workspaces use their own host, e.g.
                              # "wss://api.us.poly.ai/v1/realtime"


# --- Audio devices -----------------------------------------------------------
OUTPUT_DEVICE = "External Headphones"   # None = system default output; part of a device
                                        # name also works. "External Headphones" is the
                                        # Mac's headphone jack feeding the amp
INPUT_DEVICE = None           # None = system default mic, or e.g. "MacBook Pro Microphone"
                              # (python start.py --list-devices shows the names)
SPEAKER_VOLUME = 0.5          # 0.0-1.0, scales everything the crow plays. A safety cap for
                              # powerful amps: even at full laptop volume, output stays here


# --- Hearing itself ------------------------------------------------------------
ECHO_MODE = "cancel"          # How the mic avoids hearing Raven's own voice:
                              # "cancel": echo cancellation (like video calls). You can
                              #           talk over Raven and interrupt it.
                              # "mute":   the mic is muted while Raven talks. Simpler and
                              #           rock solid, but you can't interrupt.
ECHO_NOISE_SUPPRESSION = False  # "cancel" only: also reduce steady background noise
ECHO_TAIL_S = 0.2             # "mute" only: keep the mic muted this long after the crow
                              # stops talking. Raise it if the crow answers its own echo


# --- Voice (text to speech) --------------------------------------------------
TTS_ENGINE = "elevenlabs"     # "elevenlabs" (needs ELEVENLABS_API_KEY) or "say" (Mac voices)
ELEVENLABS_VOICE_ID = "pqHfZKP75CvOlQylNhV4"  # Bill (free premade voice). Library voices such as
                                              # Timothy (qkG6pQFWpZTnYnoQZGFs) need a paid plan
ELEVENLABS_MODEL = "eleven_flash_v2_5"  # fastest and cheapest. "eleven_v4_turbo" is more expressive
                                        # and nearly as quick; "eleven_v4" sounds best but is slower
ELEVENLABS_STABILITY = 0.4    # lower = more expressive and varied, higher = steadier
ELEVENLABS_SPEED = 1.0        # below 1.0 talks slower, above 1.0 faster
MAC_VOICE = "Daniel"          # Mac voice for "say", and the fallback if ElevenLabs fails.
                              # List them with: say -v '?'
MAC_VOICE_RATE = 175          # words per minute (Mac voice only)


# --- Lip sync ----------------------------------------------------------------
LIPSYNC_FPS = 40              # beak updates per second
LIPSYNC_LEAD_S = 0.05         # move the beak this long before the sound, since the
                              # servo needs time to travel. Raise it if the beak lags
BEAK_MAX_OPEN = 100           # percent; lower it if the beak gapes too wide
BEAK_GATE = 0.12              # sound quieter than this (0-1) keeps the beak shut


# --- The Nano (USB) ------------------------------------------------------------
SERIAL_PORT = None            # None = find the Nano automatically, or e.g.
                              # "/dev/cu.usbserial-1410" (Mac), "COM3" (Windows)


# --- Neck --------------------------------------------------------------------
NECK_SIDE = 700               # steps from center to the end stop (NECK_RANGE / 2 in settings.h)
NECK_FLIP = False             # set True if "look left" turns the head right
NECK_LIVELY = True            # small movements by itself, so Raven looks alive
# For each state: how often the head moves by itself (seconds, random between
# the two), how far (steps from facing you), and how soon after entering the state.
NECK_LIFE = {
    "rest":   {"every": (2.5, 6.0), "reach": 350, "first": 2.0},  # waiting: drifts, the odd look around
    "listen": {"every": (3.0, 6.0), "reach": 60,  "first": 2.0},  # you're talking: little attentive tilts
    "think":  {"every": (1.0, 2.5), "reach": 220, "first": 0.3},  # deciding: glances away
    "talk":   {"every": (1.5, 3.5), "reach": 120, "first": 0.5},  # speaking: emphasis, facing you
}
NECK_HOLD_AFTER_LOOK_S = 4    # after a deliberate look (a tool), stay put this long
# Neck speed (max steps/s, acceleration). Must match the firmware's settings.h;
# used to wait for one deliberate look to finish before starting the next.
NECK_FAST = (1000, 2000)      # NECK_SPEED_FAST_MAX, NECK_SPEED_FAST_ACCEL
NECK_SLOW = (3250, 500)       # NECK_SPEED_SLOW_MAX, NECK_SPEED_SLOW_ACCEL


# --- Eyes --------------------------------------------------------------------
EYES_SHOW_STATE = False       # False: always blink. True: pulse while listening,
                              # flicker while thinking, steady while talking
EYE_EFFECT_S = 3.0            # how long a requested eye effect (pulse, flicker...) lasts


# --- Project work (PolyAI's Wren, behind the scenes) ------------------------
# Raven works on your PolyAI projects in the background and presents it as its
# own (prompts/tools/project-work.md). Off until POLYAI_PAT (a personal access
# token, not a workspace API key) is in .env and WREN_PROJECTS is filled in.
WREN_BASE_URL = "https://api.studio.poly.ai"  # your region's platform API host; see
                                              # docs.poly.ai/api-reference ("pick your region")
WREN_ACCOUNT_ID = "ajeet-prabu-ws"  # your account ID
WREN_PROJECTS = {             # each project's name -> its project ID. With just one,
                              # Raven uses it without you having to say which
    "Demo restaurant": "AGENT-0BJTY1NS",
}
WREN_MODE = "auto"            # "auto": works through to a report, only stopping for the few
                              # actions that always need a person. "interactive": also
                              # stops at every plan and question. "headless": never stops
WREN_READ_TIMEOUT_S = 1200    # runs can take many minutes
WREN_DRAFT_EXPIRES_S = 120    # a read-back that isn't confirmed within this long has to be redone
