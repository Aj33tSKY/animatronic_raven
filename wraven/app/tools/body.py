"""Raven's body: crow calls, head turns, head shakes and eye effects."""
from tools import tool

PROMPT = "body.md"


@tool("caw",
      "Let out a crow call through your speaker. 'squawk' is a short caw; 'scold' is "
      "an angry, scolding cry with a jerk of the head.",
      {"type": "object",
       "properties": {"kind": {"type": "string", "enum": ["squawk", "scold"]}},
       "required": ["kind"]})
def caw(context, kind):
    if kind not in ("squawk", "scold"):
        return {"error": f"unknown kind of caw: {kind}"}
    if kind == "scold":
        context.performer.add("act", "scold", context.reply_id)  # the jerk of the head
    context.performer.add("sound", kind, context.reply_id)
    return {"ok": True}


TURNS = {"left": "look left", "right": "look right", "far_left": "look far left",
         "far_right": "look far right", "center": "look at you"}


@tool("turn_head",
      "Turn your head to look left or right ('far_left'/'far_right' turn as far as your "
      "neck goes), or back at the person ('center'). A few seconds after looking away, "
      "you turn back to face the person by yourself.",
      {"type": "object",
       "properties": {"direction": {"type": "string", "enum": list(TURNS)}},
       "required": ["direction"]})
def turn_head(context, direction):
    if direction not in TURNS:
        return {"error": f"unknown direction: {direction}"}
    context.performer.add("act", TURNS[direction], context.reply_id)
    return {"ok": True}


@tool("shake_head", "Shake your head, as in 'no'.")
def shake_head(context):
    context.performer.add("act", "shake", context.reply_id)
    return {"ok": True}


EFFECTS = ("pulse", "flicker", "glare", "closed")


@tool("set_eyes",
      "Change your glowing eyes for a few seconds: 'pulse' (slow breathing glow), "
      "'flicker' (nervous flicker), 'glare' (steady stare) or 'closed'. Only use this "
      "when someone asks, or for a big dramatic moment.",
      {"type": "object",
       "properties": {"effect": {"type": "string", "enum": list(EFFECTS)}},
       "required": ["effect"]})
def set_eyes(context, effect):
    if effect not in EFFECTS:
        return {"error": f"unknown eye effect: {effect}"}
    context.performer.add("act", f"eyes {effect}", context.reply_id)
    return {"ok": True}
