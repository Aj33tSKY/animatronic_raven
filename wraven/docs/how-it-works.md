# How it works

Raven is a voice agent on PolyAI's **Dialog-RSN-1**, with a physical body. This page
follows one conversation through the code.

```
                          ┌──────────── PolyAI ────────────┐
   mic ─► echo canceller ─┼─► Dialog-RSN-1 ─► reply text ───┼─► ElevenLabs ─► speaker ─► beak (lip sync)
          (audio/echo.py) │   hears you, decides when      │   (integrations/      (audio/speaker.py,
                          │   you've finished, calls tools │    elevenlabs.py)      audio/lipsync.py)
                          └──────────────┬─────────────────┘
                                         │ tool calls
                                         ▼
                              tools/  ──► head, eyes, crow calls (hardware/)
                                      └─► project work (integrations/wren.py, in the background)
```

## 1. The briefing

When Raven starts, `conversation_runtime/briefing.py` gathers what Dialog-RSN-1 is told,
and `integrations/dialog_rsn1.py` sends it in one `session.update`:

| What | From | Sent as |
|---|---|---|
| Instructions | `prompts/*.md` in filename order, then `prompts/tools/*.md` for the tools in use | `instructions` |
| Tools | every tool in `tools/` that's switched on | `tools` |
| Knowledge | `knowledge/*.md`, one topic per file | `poly_knowledge` (a PolyAI extension) |
| Audio format | 16-bit, 16 kHz mic audio | `audio.input.format` |
| Turn-taking | Dialog-RSN-1 decides when you've finished, then replies by itself | `turn_detection: server_vad`, `create_response: true` |

We ask for **text** replies (`output_modalities: ["text"]`), not audio, so Raven can
speak with its own ElevenLabs voice and move its beak to it.

## 2. Listening

`conversation_runtime/session.py` streams the mic to Dialog-RSN-1 continuously,
32 ms at a time (`input_audio_buffer.append`). There's no push-to-talk: the model
listens all the time and decides for itself when you've started and finished:

- `input_audio_buffer.speech_started`: Raven turns to face you and listens.
- `input_audio_buffer.speech_stopped`: it thinks. Pausing after a complete sentence
  usually counts as finished; trailing off with "so…" or "um…" doesn't.
- `conversation.item.input_audio_transcription.completed` carries what it heard
  (printed as `you: …`).

The crow's own voice would reach the mic too, so it's removed first by **echo
cancellation** (`audio/echo.py`, WebRTC's canceller, as in video calls): it's given a
copy of everything the speaker plays and subtracts it. That's what lets you talk over
Raven. (`ECHO_MODE = "mute"` mutes the mic while Raven talks instead.)

## 3. Replying

The reply arrives a few words at a time (`response.output_text.delta`):

- It often starts with an **emotion tag** like `[amused]`. That's stripped and shown in
  the terminal, never spoken.
- Each **finished sentence** goes straight to ElevenLabs, while the model is still writing
  the rest, and the next sentence's audio is made while the current one plays.
  `conversation_runtime/performer.py` plays them in order, with the beak following the
  loudness 40 times a second.
- `response.done` closes the reply. If the model answered from a knowledge topic, it
  names it in `poly_cited_topics` (printed as `[knowledge] used: …`).

## 4. Tools

When the model wants to act, it sends `response.function_call_arguments.done` with the
tool's name and arguments. `tools/__init__.py` runs the matching function, and the
result goes back as a `function_call_output`, followed by `response.create` so the
model can carry on talking.

- **Body** (`tools/body.py`): `caw`, `turn_head`, `shake_head` and `set_eyes` queue a move or
  sound with the Performer and reply `{"ok": true}` at once. The head turns while Raven
  keeps talking.
- **Project work** (`tools/project_work.py`): work on PolyAI projects, done in the
  background by Wren, PolyAI's agent builder (`integrations/wren.py`). Raven drafts the
  task, reads it back, and only starts once you've said yes (enforced in code). Results
  come back minutes later as a `[Background work]` system message, which is held until
  nobody is talking.

## 5. Interrupting

If you talk over Raven, Dialog-RSN-1 sends `speech_started` (and cancels the reply,
`response.done` with status `cancelled`). Raven stops mid-word and drops the rest of the
reply. Throughout, the Performer reports how much of each reply has actually played:

- `poly.output_audio.started` when a reply's first sound comes out
- `poly.output_audio.delta` every 250 ms: how many milliseconds and which words so far
- `poly.output_audio.stopped`: the total heard, how much was dropped, and the words heard

So after an interruption Dialog-RSN-1 knows exactly what you heard (for example,
*"Once upon a time there was a raven. It was"*), not just what it wrote.

## Where to change things

| To change | Edit |
|---|---|
| Who Raven is, how it talks, games, turn-taking | `app/prompts/` |
| What Raven knows | `app/knowledge/` |
| What Raven can do | `app/tools/` (copy `_example.py` for a new tool) |
| Voice, volume, echo mode, neck and eye behaviour, project-work account | `app/settings.py` |
| The Dialog-RSN-1 protocol itself | `app/integrations/dialog_rsn1.py` |
| What Raven does with each event | `app/conversation_runtime/session.py` |
