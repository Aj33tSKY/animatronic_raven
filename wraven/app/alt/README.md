# alt: the Claude + Whisper version

The earlier version of Raven, kept for comparison. Whisper turns your speech
into text on this laptop, Claude writes the reply, and Raven speaks it with the
same voice, lip sync and body as the main version. It moves by writing tags
like `[look left]` into its reply (see `tags.md`) rather than calling tools.

Differences from the main version (`start.py`, on Dialog-RSN-1):
- push-to-talk by default, because Whisper needs to be told when you've finished
- no interrupting, no tools, no knowledge base, no project work

Run it from the `app` folder:

```bash
pip install -r alt/requirements.txt
python -m alt.claude_whisper           # press Enter, then speak
python -m alt.claude_whisper --type    # type instead
```

It needs `ANTHROPIC_API_KEY` in `.env`, and uses the character, speaking-style and
games prompts from `prompts/`.
