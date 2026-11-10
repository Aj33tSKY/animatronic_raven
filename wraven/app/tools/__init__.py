"""
What Raven can do: every tool, in one list.

Each tool file ends with a TOOLS list. Each entry is exactly what Dialog-RSN-1
receives in session.update, plus the function that runs it:

    {"name": "shake_head",
     "description": "Shake your head, as in 'no'.",
     "parameters": {"type": "object", "properties": {}},
     "run": shake_head}

Every tool in TOOLS is offered to Raven. To add tools, copy _example.py to a new file,
edit it, and add its TOOLS below; how Raven should use them goes in a numbered file in
prompts/. To take tools away, remove them from TOOLS.

A tool's function receives `context` first, then its arguments, and returns a dict
that's sent back to Dialog-RSN-1 as the result ({"error": ...} if it didn't work).
context has:
  context.performer   queue speech, moves and sounds: performer.add("act", "shake", context.reply_id)
  context.body        the crow's body (hardware/body.py)
  context.wren        the project-work client, or None
  context.reply_id    the reply this tool call belongs to
  context.user_turns  how many times the person has spoken so far
"""
from dataclasses import dataclass

from tools import body, project_work

# Every tool Raven can use
TOOLS = body.TOOLS + project_work.TOOLS


@dataclass
class Context:
    performer: object = None
    body: object = None
    wren: object = None
    reply_id: str = None
    user_turns: int = 0


def definitions(tool_list):
    """The tool list for Dialog-RSN-1's session.update."""
    found = []
    for entry in tool_list:
        parameters = entry.get("parameters", {"type": "object", "properties": {}})
        if callable(parameters):  # worked out at start-up (e.g. from settings)
            parameters = parameters()
        found.append({"type": "function", "name": entry["name"],
                      "description": entry["description"], "parameters": parameters})
    return found


def run(name, args, context):
    """Run a tool by name. Problems come back as {"error": ...} for the model to see,
    rather than stopping the conversation."""
    entry = next((entry for entry in TOOLS if entry["name"] == name), None)
    if entry is None:
        return {"error": f"unknown tool {name}"}
    try:
        return entry["run"](context, **args)
    except TypeError as error:  # missing or unexpected arguments
        return {"error": f"bad arguments for {name}: {error}"}
    except (KeyError, ValueError) as error:
        return {"error": str(error)}
