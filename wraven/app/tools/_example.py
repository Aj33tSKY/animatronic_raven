"""
A template for new tools. To use it:

    1. cp tools/_example.py tools/dice.py      and edit the copy
    2. add its tools in tools/__init__.py:      from tools import body, dice, project_work
                                               TOOLS = body.TOOLS + dice.TOOLS + project_work.TOOLS
    3. optionally, say when to use them in a numbered prompt, e.g. prompts/7-dice.md

then restart. Each entry in TOOLS is exactly what Dialog-RSN-1 is told about the tool,
plus "run": the function to call. The description is what the model reads to decide
when to use the tool, so write it for the model: what it does and when to call it.
"""
import random


def roll_dice(context, sides=6):
    # Return a dict; it's sent back to the model as the tool's result. To make the
    # crow move as well: context.performer.add("act", "shake", context.reply_id)
    return {"rolled": random.randint(1, max(2, sides))}


TOOLS = [
    {"name": "roll_dice",
     "description": "Roll dice for a game, then say the result out loud.",
     "parameters": {"type": "object",
                    "properties": {"sides": {"type": "integer", "description": "How many sides (default 6)."}},
                    "required": []},
     "run": roll_dice},
]
