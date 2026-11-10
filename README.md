# Wraven

Raven is an animatronic raven you can talk to, powered by PolyAI's
[Dialog-RSN-1](https://poly.ai/dialog-rsn-1). You speak to it; it listens, works out when
you've finished, answers in its own voice through a speaker in its body, and moves its
beak, head and eyes as it talks. You can interrupt it, play games with it, and have it
work on your PolyAI projects in the background.

![Raven](wraven/docs/images/AniCrow022.jpg)

## Where everything lives

```
README.md                    ← you are here
LICENSE
wraven/
├── docs/
│   ├── how-it-works.md      ← one conversation through the code, and the Dialog-RSN-1 API
│   ├── hardware.md          ← parts, wiring, firmware upload, calibration
│   ├── assembly.md          ← putting the printed crow together
│   └── tuning.md            ← what to change when something feels off
├── model/                   ← the 3D-print files, and how to print them
├── firmware/wraven-nano/    ← Arduino sketch: beak, neck and eyes over USB
└── app/
    ├── start.py             ← run this
    ├── settings.py          ← knobs: audio devices, voice, echo mode, neck, eyes, project work
    ├── .env.example         ← copy to .env and add your API keys (.env stays out of git)
    │
    ├── prompts/             ← WHAT RAVEN IS TOLD (plain text, joined in filename order)
    │   └── 1-character.md … 7-project-work.md
    ├── knowledge/           ← WHAT RAVEN KNOWS (one topic per file → poly_knowledge)
    ├── tools/               ← WHAT RAVEN CAN DO (each file's TOOLS, joined in tools/__init__.py)
    ├── sounds/              ← the crow calls Raven can make
    │
    ├── integrations/        ← outside services: dialog_rsn1.py, wren.py, elevenlabs.py
    ├── audio/               ← sound on this laptop: speaker, lip sync, microphone, echo
    ├── hardware/            ← the physical crow: nano.py (USB), body.py (behaviour)
    ├── conversation_runtime/  ← ties it together: briefing, performer, session
    │
    ├── tests/               ← python -m pytest (no sound, no crow, no API calls)
    └── alt/                 ← the earlier Claude + Whisper version, for comparison
```

The three folders at the top of `wraven/app/`, **prompts**, **knowledge** and **tools**, are
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

Building the crow itself: print the parts ([wraven/model/](wraven/model/README.md)), assemble
them ([assembly.md](wraven/docs/assembly.md)), and wire it up ([hardware.md](wraven/docs/hardware.md)).

## Making changes

**Raven's personality or rules.** Edit a file in `wraven/app/prompts/`. Add a new file to add a
section; the number at the front sets where it goes. Text inside `<!-- -->` is a note for
editors and isn't sent to the model.

**What Raven knows.** Add a `.md` file to `wraven/app/knowledge/`: a `# Topic name` line, then
the facts. It's sent as a Dialog-RSN-1 `poly_knowledge` topic, and when Raven answers from
it, the terminal shows `[knowledge] used: Topic name`. See `knowledge/README.md`.

**A new tool.** Copy `wraven/app/tools/_example.py` to a new name, edit it, and add its
`TOOLS` to the list in `tools/__init__.py`. Each file ends with a `TOOLS` list: every entry is
exactly what Dialog-RSN-1 is told about the tool (name, description, parameters), plus
`"run"`, the function that runs it. To tell Raven when to use it, add a numbered file to
`prompts/` (e.g. `7-dice.md`).

**Knobs.** Voice, volume, echo mode, neck liveliness, eyes and the project-work account
are in `wraven/app/settings.py`, grouped and commented.

After changing code, run `python -m pytest` in `wraven/app/` to check interrupts, tools,
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
Raw events are saved in `wraven/app/logs/` (git ignores it).

## Credits

Raven's body is Ken Goudey's (swaziloo) [Animatronic Crow](https://github.com/swaziloo/halloween),
which this repository was forked from: the 3D model, the mechanical design and the
original assembly guide, used under the MIT licence in [LICENSE](LICENSE). The model is
itself a remix of designs by andymcculloch, Doctor_JohnSmith, danman and YahooJAPAN on
Thingiverse; see [wraven/model/README.md](wraven/model/README.md) for the details. The
original project's circuit board, firmware and sound board aren't used here; they're in
the [upstream repository](https://github.com/swaziloo/halloween).
