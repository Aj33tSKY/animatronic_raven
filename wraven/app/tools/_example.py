"""
A template for a new tool. Files starting with "_" aren't loaded, so this one
does nothing until you copy it:

    cp tools/_example.py tools/dice.py

then edit the copy and restart. The tool appears in Dialog-RSN-1's tool list
automatically. The description is what the model reads to decide when to use
the tool, so write it for the model: what it does and when to call it.
"""
import random

from tools import tool

# Optional: a prompt file in prompts/tools/ that tells Raven when to use these tools.
# PROMPT = "dice.md"


@tool("roll_dice",
      "Roll dice for a game, then say the result out loud.",
      {"type": "object",
       "properties": {"sides": {"type": "integer", "description": "How many sides (default 6)."}},
       "required": []})
def roll_dice(context, sides=6):
    # Return a dict; it's sent back to the model as the tool's result.
    # To make the crow move as well: context.performer.add("act", "shake", context.reply_id)
    return {"rolled": random.randint(1, max(2, sides))}
