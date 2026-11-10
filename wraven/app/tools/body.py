"""CUSTOMISE: part of the agent. Edit this to change what Raven is, knows or does.

Raven's body: crow calls, head turns, head shakes and eye effects.
How Raven uses them: prompts/5-body.md."""

TURNS = {"left": "look left", "right": "look right", "far_left": "look far left",
         "far_right": "look far right", "center": "look at you"}
EFFECTS = ("pulse", "flicker", "glare", "closed")


# CUSTOMISE: each tool's function. Gets `context`, returns a dict that goes back to the model.
def caw(context, kind):
    if kind not in ("squawk", "scold"):
        return {"error": f"unknown kind of caw: {kind}"}
    if kind == "scold":
        context.performer.add("act", "scold", context.reply_id)  # the jerk of the head
    context.performer.add("sound", kind, context.reply_id)
    return {"ok": True}


def turn_head(context, direction):
    if direction not in TURNS:
        return {"error": f"unknown direction: {direction}"}
    context.performer.add("act", TURNS[direction], context.reply_id)
    return {"ok": True}


def shake_head(context):
    context.performer.add("act", "shake", context.reply_id)
    return {"ok": True}


def set_eyes(context, effect):
    if effect not in EFFECTS:
        return {"error": f"unknown eye effect: {effect}"}
    context.performer.add("act", f"eyes {effect}", context.reply_id)
    return {"ok": True}


# CUSTOMISE: what Dialog-RSN-1 is told about each tool, and the function that runs it.
# The "description" is what the model reads to decide when to call the tool, so it's
# the main thing to tune. "parameters" is a JSON schema; its names must match the
# function's arguments.
TOOLS = [
    {"name": "caw",
     "description": "Let out a crow call through your speaker. 'squawk' is a short caw; "
                    "'scold' is an angry, scolding cry with a jerk of the head.",
     "parameters": {"type": "object",
                    "properties": {"kind": {"type": "string", "enum": ["squawk", "scold"]}},
                    "required": ["kind"]},
     "run": caw},

    {"name": "turn_head",
     "description": "Turn your head to look left or right ('far_left'/'far_right' turn as far "
                    "as your neck goes), or back at the person ('center'). A few seconds after "
                    "looking away, you turn back to face the person by yourself.",
     "parameters": {"type": "object",
                    "properties": {"direction": {"type": "string", "enum": list(TURNS)}},
                    "required": ["direction"]},
     "run": turn_head},

    {"name": "shake_head",
     "description": "Shake your head, as in 'no'.",
     "parameters": {"type": "object", "properties": {}},
     "run": shake_head},

    {"name": "set_eyes",
     "description": "Change your glowing eyes for a few seconds: 'pulse' (slow breathing "
                    "glow), 'flicker' (nervous flicker), 'glare' (steady stare) or 'closed'. "
                    "Only use this when someone asks, or for a big dramatic moment.",
     "parameters": {"type": "object",
                    "properties": {"effect": {"type": "string", "enum": list(EFFECTS)}},
                    "required": ["effect"]},
     "run": set_eyes},
]
