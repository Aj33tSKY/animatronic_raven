"""
What Raven is told at the start of a conversation:
  - instructions: prompts/*.md, joined in filename order
  - tools: the TOOLS list in tools/__init__.py
  - knowledge: knowledge/*.md, one topic per file, sent as Dialog-RSN-1's poly_knowledge
"""
import re

import settings
import tools

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)  # notes for editors, never sent


def read_prompt(path):
    return COMMENT.sub("", path.read_text()).strip()


def instructions():
    """prompts/*.md, joined in filename order."""
    parts = [read_prompt(path) for path in sorted(settings.PROMPTS_DIR.glob("*.md"))]
    return "\n\n".join(part for part in parts if part)


def knowledge():
    """[{"name": ..., "content": ...}] from knowledge/*.md (README and _files skipped)."""
    topics = []
    for path in sorted(settings.KNOWLEDGE_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name.lower() == "readme.md":
            continue
        text = read_prompt(path)
        first, _, rest = text.partition("\n")
        if first.startswith("#"):
            name, content = first.lstrip("#").strip(), rest.strip()
        else:
            name, content = path.stem.replace("-", " ").replace("_", " "), text
        if content:
            topics.append({"name": name, "content": content})
    return topics


def build():
    """Everything for the session: (instructions, tool definitions, knowledge topics)."""
    return instructions(), tools.definitions(tools.TOOLS), knowledge()
