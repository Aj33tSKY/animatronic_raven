"""
What Raven can do. Each file in this folder is a group of tools, and each
tool's definition (name, description, parameters) sits right above the code
that runs it.

To add a tool, copy _example.py to a new name (no leading underscore) and edit
it. It's picked up automatically. A group can:
  - set PROMPT = "file.md" to add prompts/tools/file.md to Raven's instructions
  - define enabled(context) to switch itself off (e.g. project work without a token)
  - define prompt_extra(context) to add text worked out at start-up

A tool function receives `context` first, then its arguments. It returns a dict,
which is sent back to Dialog-RSN-1 as the tool's result. context has:
  context.performer   queue speech, moves and sounds: performer.add("act", "shake", context.reply_id)
  context.body        the crow's body (hardware/body.py)
  context.wren        the project-work client, or None
  context.reply_id    the reply this tool call belongs to
  context.user_turns  how many times the person has spoken so far
"""
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

import settings


@dataclass
class Tool:
    name: str
    description: str
    parameters: object      # a JSON schema dict, or a function returning one
    run: Callable
    group: str


@dataclass
class Context:
    performer: object = None
    body: object = None
    wren: object = None
    reply_id: str = None
    user_turns: int = 0
    extra: dict = field(default_factory=dict)


_registry = {}


def tool(name, description, parameters=None):
    """Register the function below as a tool Raven can call."""
    def register(function):
        _registry[name] = Tool(name, description,
                               parameters or {"type": "object", "properties": {}},
                               function, function.__module__)
        return function
    return register


def groups(context):
    """Load every tool file, and return the groups that are switched on."""
    loaded = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        enabled = getattr(module, "enabled", lambda context: True)
        if enabled(context):
            loaded.append(module)
    return loaded


def definitions(active_groups):
    """The tool list for Dialog-RSN-1's session.update."""
    names = {module.__name__ for module in active_groups}
    found = []
    for item in _registry.values():
        if item.group in names:
            parameters = item.parameters() if callable(item.parameters) else item.parameters
            found.append({"type": "function", "name": item.name,
                          "description": item.description, "parameters": parameters})
    return found


def prompts(active_groups, context):
    """Instructions that come with the tool groups (prompts/tools/*.md, plus extras)."""
    from conversation_runtime.briefing import read_prompt
    texts = []
    for module in active_groups:
        if getattr(module, "PROMPT", None):
            texts.append(read_prompt(settings.PROMPTS_DIR / "tools" / module.PROMPT))
        if hasattr(module, "prompt_extra"):
            texts.append(module.prompt_extra(context))
    return [text for text in texts if text]


def run(name, args, context):
    """Run a tool by name. Problems come back as {"error": ...} for the model to see."""
    item = _registry.get(name)
    if item is None:
        return {"error": f"unknown tool {name}"}
    try:
        return item.run(context, **args)
    except TypeError as error:  # missing or unexpected arguments
        return {"error": f"bad arguments for {name}: {error}"}
    except (KeyError, ValueError) as error:
        return {"error": str(error)}
