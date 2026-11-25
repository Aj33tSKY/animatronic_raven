# Knowledge

Facts Raven can draw on. Each `.md` file here is one **topic**, sent to Dialog-RSN-1
as its `poly_knowledge` brief at the start of every conversation.

- The first line, `# Topic name`, is the topic's name. Everything after it is the content.
- Keep each topic about one thing. Plain sentences work best.
- When Raven answers from a topic, the terminal shows `[knowledge] used: <name>`.
- This README and files starting with `_` are skipped. Copy `_example.md` to start a topic.
- Everything Raven is given (prompts, tools, knowledge) shares the model's 32k-token
  context, so keep the total modest: aim for about 2,000 words of instructions plus
  the tool definitions.
