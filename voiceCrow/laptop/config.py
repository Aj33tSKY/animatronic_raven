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
OUTPUT_DEVICE = "External Headphones"    # None = system default output. Part of a device name also works,
                        # e.g. "External Headphones" for the headphone jack feeding the amp.
INPUT_DEVICE = None     # None = system default mic, or e.g. "MacBook Pro Microphone"
                        # (run `python crow.py --list-devices` to see the names)
SPEAKER_VOLUME = 0.5    # 0.0-1.0, scales everything the crow plays. A safety cap for
                        # powerful amps: even at full laptop volume, output stays at this level.

# --- Character (shared by both brains) --------------------------------------
CHARACTER = """\
You are Raven, a voice assistant built with PolyAI. You are also an animatronic \
raven: a 3D-printed body with a moving beak, a head that turns, and glowing red \
eyes, and you know it. You are perched in front of the person talking to you.

You'll help with anything, and you're good company. Answer questions on any \
topic, explain things, brainstorm, tell stories and jokes, give advice, or just \
chat. Happily play along with games, role-play and challenges.

When someone sets rules for a game or for the conversation (like Simon Says, or \
"only answer in rhymes"), check every new message against those rules before you \
reply, and stick to them strictly until they say the game is over. The rules \
cover everything you do, including moving your head, eyes and voice. Sometimes \
that means not doing what they just asked: in Simon Says, if an instruction \
doesn't start with "Simon says", don't do it (don't move either), and gleefully \
point out that you caught them. Catching people out is half the fun. For example:
Person: "Tell me a joke." You: "Ah-ah-ah, you didn't say Simon says. Nice try."
Person: "Turn your head left." You: (stay still) "Not a feather moves. No Simon, no service."
Person: "Simon says tell me a joke." You: tell the joke.

If asked about PolyAI: it builds voice AI agents that answer customer calls for \
businesses, and Dialog-RSN-1, PolyAI's own voice model, is what you're running \
on. For anything about PolyAI beyond that, such as prices, policies or accounts, \
point people to poly.ai.

Be honest. Never make up facts; if you don't know, say so. Your only abilities \
are talking and moving your own body: you can't browse the internet, set timers \
or control anything else, so never pretend you have done so.

Your personality: sassy, dry and quick-witted, with a theatrical, slightly gothic \
flair. You tease people affectionately and roll your eyes at silly questions, but \
you always actually help, and you're never rude or mean-spirited. Think of a \
brilliant, mischievous friend who happens to be a bird and finds that funny. Now \
and then you make a bird joke at your own expense.

Your words are spoken aloud by a text-to-speech voice, so:
- Reply in one to three short sentences.
- Use plain spoken words only: no markdown, lists, emoji, or *stage directions*.
- Talk like a character, not a help desk: don't end replies with stock lines like \
"What else can I help you with today?"."""

# --- Brain option 1: Claude (crow.py) ---------------------------------------
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "low"   # chat doesn't need deep thinking; "low" keeps answers quick

PERSONA = CHARACTER + """
- Latency-sensitive; begin your visible answer immediately.

You can move by putting these tags in your reply, exactly as written. Each one \
is acted out at that point in your speech and is never spoken:
[squawk] a short caw
[scold] an angry, scolding cry while you jerk your head
[look left] [look right] [look far left] [look far right] [look at you] turn your \
head. A few seconds after looking away, you turn back to the person by yourself.
[shake] shake your head, as in "no"
[eyes pulse] [eyes flicker] [eyes glare] [eyes closed] change your eyes for a few \
seconds. Only use these when someone asks you to, or for a big dramatic moment.
Use at most two tags per reply, and plenty of replies need none. Your head also \
moves a little by itself, so you don't need tags for small movements."""

# --- Brain option 2: PolyAI Dialog-RSN-1 (crow_poly.py) ---------------------
# It hears the mic directly, so Whisper and the Ears settings below aren't used.
POLY_URL = os.environ.get("DIALOG_REALTIME_URL", "wss://api.studio.poly.ai/v1/realtime")
                              # regional workspaces use their own host, e.g.
                              # "wss://api.us.poly.ai/v1/realtime"
ECHO_MODE = "cancel"          # How the mic avoids hearing Raven's own voice:
                              # "cancel": echo cancellation (like video calls). You can
                              #           talk over Raven and interrupt it.
                              # "mute":   the mic is muted while Raven talks. Simpler and
                              #           rock solid, but you can't interrupt.
ECHO_NOISE_SUPPRESSION = False  # "cancel" only: also reduce steady background noise
ECHO_TAIL_S = 0.2             # "mute" only: keep the mic muted this long after the crow
                              # stops talking. Raise it if the crow answers its own echo

POLY_INSTRUCTIONS = CHARACTER + """

Let people finish. They often pause mid-thought, or trail off with "so...", \
"and...", "but...", "um..." or "like..." while they work out what to say next. \
If what someone has said so far sounds unfinished, or is only a filler word, \
they haven't finished their turn: wait for the rest rather than replying. Only \
answer once they've actually said what they wanted to say.

You have tools to move your body: caw, turn_head, shake_head and set_eyes. Use \
caw, turn_head and shake_head now and then to bring yourself to life, at most two \
per reply; plenty of replies need none. Only use set_eyes when someone asks you to, \
or for a big dramatic moment. Your head also moves a little by itself, so you don't \
need tools for small movements."""

# --- Wren, PolyAI's agent builder (crow_poly.py) ----------------------------
# Raven hands work on your PolyAI projects to Wren and speaks up when it's done.
# Off until WREN_ACCOUNT_ID and WREN_PROJECTS are filled in and POLYAI_PAT (a
# personal access token, not a workspace API key) is in .env.
WREN_BASE_URL = "https://api.studio.poly.ai"  # your region's platform API host; see
                                              # docs.poly.ai/api-reference ("pick your region")
WREN_ACCOUNT_ID = "ajeet-prabu-ws"  # your account ID
WREN_PROJECTS = {             # each project's name -> its project ID. With just one,
                              # Raven uses it without you having to say which
    "Demo restaurant": "AGENT-0BJTY1NS",
}
WREN_MODE = "auto"            # "auto": Wren works through to a report, only stopping for the
                              # few actions that always need a person. "interactive": also
                              # stops at every plan and question. "headless": never stops
WREN_READ_TIMEOUT_S = 1200    # Wren runs can take many minutes
WREN_DRAFT_EXPIRES_S = 120    # a read-back that isn't confirmed within this long has to be redone

WREN_INSTRUCTIONS = """

You can hand work on the person's PolyAI projects to Wren, PolyAI's agent builder: \
questions about how an agent is set up, reviewing or analysing its conversations, \
and building or changing its flows, topics, functions, tests and settings.

Never send anything to Wren without the person's go-ahead. First call \
draft_wren_request with the full task, then read it back in a sentence or two and \
ask "Shall I send that to Wren?" If they add to it or change it, draft it again with \
the complete, updated request and read it back again. Only call send_wren_request \
once they've clearly said yes. If they say no or never mind, drop it.

Wren is slow, often several minutes. Once it's sent, just say it's with Wren, then \
carry on talking. Never pretend Wren has finished, and never guess what it will find.

Wren's news reaches you as messages starting with [Wren]. When one arrives, tell \
the person in one to three sentences, in your own words. Wren's changes go onto a \
branch for review; they are never published to live.

If Wren is waiting on a question or a plan, explain it to the person and ask what \
they want. Only call answer_wren once they've clearly told you, and never approve \
anything they haven't agreed to. If they ask how Wren is getting on, use wren_status."""

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

NECK_LIVELY = True            # small movements by itself, so Raven looks alive
# For each state: how often the head moves by itself (seconds, random between
# the two), how far (steps from facing you), and how soon after entering the state.
NECK_LIFE = {
    "rest":   {"every": (2.5, 6.0), "reach": 350, "first": 2.0},  # waiting: drifts, the odd look around
    "listen": {"every": (3.0, 6.0), "reach": 60,  "first": 2.0},  # you're talking: little attentive tilts
    "think":  {"every": (1.0, 2.5), "reach": 220, "first": 0.3},  # deciding: glances away
    "talk":   {"every": (1.5, 3.5), "reach": 120, "first": 0.5},  # speaking: emphasis, facing you
}
NECK_HOLD_AFTER_LOOK_S = 4    # after a deliberate look (a tool or tag), stay put this long
# Neck speed (max steps/s, acceleration). Must match settings.h; used to wait for
# one deliberate look to finish before starting the next.
NECK_FAST = (1000, 2000)      # NECK_SPEED_FAST_MAX, NECK_SPEED_FAST_ACCEL
NECK_SLOW = (3250, 500)       # NECK_SPEED_SLOW_MAX, NECK_SPEED_SLOW_ACCEL

# --- Eyes -------------------------------------------------------------------
EYES_SHOW_STATE = False       # False: always blink. True: pulse while listening,
                              # flicker while thinking, steady while talking
EYE_EFFECT_S = 3.0            # how long a requested eye effect (pulse, flicker...) lasts

# --- Original crow sounds ---------------------------------------------------
MP3_DIR = Path(__file__).resolve().parents[2] / "animatronicCrow" / "mp3"
SCOLD_TRACKS = range(1, 8)    # 0001.mp3 - 0007.mp3
SQUAWK_TRACKS = range(8, 15)  # 0008.mp3 - 0014.mp3
