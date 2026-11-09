# Wraven

Raven is an animatronic raven you can talk to, powered by PolyAI's
[Dialog-RSN-1](https://poly.ai/dialog-rsn-1). You speak to it; it listens, works out when
you've finished, answers in its own voice through a speaker in its body, and moves its
beak, head and eyes as it talks. You can interrupt it, play games with it, and have it
work on your PolyAI projects in the background.

## Where everything lives

```
wraven/
├── README.md                ← you are here
├── docs/
│   ├── how-it-works.md      ← one conversation through the code, and the Dialog-RSN-1 API
│   ├── hardware.md          ← parts, wiring, firmware upload, calibration
│   └── tuning.md            ← what to change when something feels off
├── firmware/wraven-nano/    ← Arduino sketch: beak, neck and eyes over USB
└── app/
    ├── start.py             ← run this
    ├── settings.py          ← knobs: audio devices, voice, echo mode, neck, eyes, project work
    ├── .env.example         ← copy to .env and add your API keys (.env stays out of git)
    │
    ├── prompts/             ← WHAT RAVEN IS TOLD (plain text, joined in filename order)
    │   ├── 1-character.md, 2-speaking-style.md, 3-games.md, 4-turn-taking.md
    │   └── tools/           ← instructions that come with each group of tools
    ├── knowledge/           ← WHAT RAVEN KNOWS (one topic per file → poly_knowledge)
    ├── tools/               ← WHAT RAVEN CAN DO (one file per group; copy _example.py)
    │
    ├── integrations/        ← outside services: dialog_rsn1.py, wren.py, elevenlabs.py
    ├── audio/               ← sound on this laptop: speaker, lip sync, microphone, echo
    ├── hardware/            ← the physical crow: nano.py (USB), body.py (behaviour)
    ├── conversation_runtime/  ← ties it together: briefing, performer, session
    │
    ├── tests/               ← python -m pytest (no sound, no crow, no API calls)
    └── alt/                 ← the earlier Claude + Whisper version, for comparison
```

The three folders at the top of `app/`, **prompts**, **knowledge** and **tools**, are
the ones you'll edit most. The rest is the engine, and rarely needs touching.

## Quick start

```bash
cd wraven/app
python3 -m venv .venv && source .venv/bin/activate     # Python 3.10 or newer
pip install -r requirements.txt
cp .env.example .env                                    # then add your keys
python start.py --list-devices                          # set OUTPUT_DEVICE in settings.py
python start.py --no-crow --say "Hello Raven"           # a typed turn, no Arduino needed
python start.py                                         # talk to Raven
```

Keys in `.env`: `POLY_API_KEY` (studio.poly.ai > API Keys), `ELEVENLABS_API_KEY`, and,
for project work, `POLYAI_PAT` (a personal access token). Keys set in the Terminal with
`export` take priority over the file.

Other commands: `python start.py --test-sound` (lip sync and crow calls, no AI), and
`python start.py --say "…" --say "yes"` for a typed, multi-turn conversation.

Building the crow itself: see [docs/hardware.md](docs/hardware.md).

## Making changes

**Raven's personality or rules.** Edit a file in `app/prompts/`. Add a new file to add a
section; the number at the front sets where it goes. Text inside `<!-- -->` is a note for
editors and isn't sent to the model.

**What Raven knows.** Add a `.md` file to `app/knowledge/`: a `# Topic name` line, then
the facts. It's sent as a Dialog-RSN-1 `poly_knowledge` topic, and when Raven answers from
it, the terminal shows `[knowledge] used: Topic name`. See `knowledge/README.md`.

**A new tool.** Copy `app/tools/_example.py` to a new name and edit it. The definition
(name, description, parameters) sits right above the function that runs it, and it's
picked up automatically. To give Raven instructions about when to use it, add a file in
`prompts/tools/` and set `PROMPT` in the tool file.

**Knobs.** Voice, volume, echo mode, neck liveliness, eyes and the project-work account
are in `app/settings.py`, grouped and commented.

After changing code, run `python -m pytest` in `app/` to check interrupts, tools,
knowledge and project work still behave.

## Project work (PolyAI's Wren, behind the scenes)

Raven can work on your PolyAI projects: review how an agent is set up, look into its
calls, or build and edit flows, topics, functions and tests. It presents the work as
its own ("I'll change the greeting…", "I've added two topics"); if asked about Wren, it's
Raven's best friend and practically its twin. Before starting anything, Raven reads the
task back and asks "Shall I go ahead?", and nothing starts until you say yes. Edits go
on a branch for review; nothing is published to live.

To turn it on: put `POLYAI_PAT` in `.env`, and fill in `WREN_ACCOUNT_ID` and
`WREN_PROJECTS` in `settings.py`. To try Wren on its own and see its raw events:
`python -m integrations.wren --project "Demo restaurant" "What topics does it have?"`.
Raw events are saved in `app/logs/` (git ignores it).
