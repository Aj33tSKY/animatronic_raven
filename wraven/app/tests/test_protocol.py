"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The protocol rules from PolyAI's own client, which keep a session from failing with
generation_failed: tool calls answered once their reply is done (completed, or cancelled by the
person speaking; a failed reply's calls are dropped), one response.create, slow tools not blocking
the conversation, nothing slipped in while a tool call is in flight or the server is about to reply."""
import asyncio
import json
import time

import pytest
import websockets

import settings
from conversation_runtime import session
from conversation_runtime.session import Turns
from hardware.body import Body
from integrations.dialog_rsn1 import DialogRSN1
from tests import fakes


@pytest.fixture
def poly(monkeypatch):
    monkeypatch.setenv("POLY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "WREN_PROJECTS", {})


def converse(nano, script, port, typed=("Hello",), seconds=8):
    async def go():
        async with fakes.fake_dialog(script, port) as (url, received):
            settings.POLY_URL = url
            try:
                await asyncio.wait_for(session.run(nano, Body(nano), list(typed)), seconds)
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                pass
            return received
    return asyncio.run(go())


async def send(ws, **event):
    await ws.send(json.dumps(event))


def test_two_tool_calls_are_answered_together_after_the_reply_with_one_create(poly, silent_audio, fake_voice, nano):
    marks = {}

    async def script(ws, received):
        await asyncio.sleep(0.1)
        await send(ws, type="response.created", response={"id": "r1"})
        for n, direction in enumerate(("far_left", "far_right")):
            await send(ws, type="response.output_item.added", response_id="r1",
                       item={"type": "function_call", "id": f"item{n}", "call_id": f"call_{n}" * 4, "name": "turn_head"})
            await send(ws, type="response.function_call_arguments.done", response_id="r1", item_id=f"item{n}",
                       call_id=f"call_{n}" * 4, name="turn_head", arguments=json.dumps({"direction": direction}))
        await asyncio.sleep(0.4)  # the reply is still open: nothing should be answered yet
        marks["done_at"] = len(received)
        await send(ws, type="response.done", response={"id": "r1", "status": "completed"})
        await asyncio.sleep(0.4)
        await fakes.server_reply(ws, "r2", "There.")
        await asyncio.sleep(0.3)
        await ws.close()
    received = converse(nano, script, port=8793)
    after_open = received[1:]  # skip session.update
    outputs = [i for i, e in enumerate(after_open, 1) if e.get("item", {}).get("type") == "function_call_output"]
    creates = [i for i, e in enumerate(after_open, 1) if e["type"] == "response.create"]
    assert len(outputs) == 2 and min(outputs) >= marks["done_at"]       # only after response.done
    assert [received[i]["item"]["call_id"] for i in outputs] == ["call_0" * 4, "call_1" * 4]  # exactly as given
    follow_ups = [i for i in creates if i > max(outputs)]
    assert len(follow_ups) == 1 and len([i for i in creates if i >= marks["done_at"]]) == 1  # one create


def one_call_then_done(status, reply_id="r1", call_id="c0", name="shake_head", arguments="{}"):
    async def script(ws, received):
        await asyncio.sleep(0.1)
        await send(ws, type="response.created", response={"id": reply_id})
        await send(ws, type="response.output_item.added", response_id=reply_id,
                   item={"type": "function_call", "id": "item0", "call_id": call_id, "name": name})
        await send(ws, type="response.function_call_arguments.done", response_id=reply_id, item_id="item0",
                   call_id=call_id, name=name, arguments=arguments)
        await send(ws, type="response.done", response={"id": reply_id, "status": status})
        await asyncio.sleep(0.8)
        await ws.close()
    return script


def test_a_cancelled_replys_tool_call_is_still_answered(poly, silent_audio, fake_voice, nano):
    received = converse(nano, one_call_then_done("cancelled"), port=8794)
    outputs = [e for e in received if e.get("item", {}).get("type") == "function_call_output"]
    assert [e["item"]["call_id"] for e in outputs] == ["c0"]    # the call stays open, so its result is owed
    assert [e["type"] for e in received].count("response.create") == 2   # the typed turn's, and one follow-up


def test_a_failed_replys_tool_call_is_dropped(poly, silent_audio, fake_voice, nano, capsys):
    received = converse(nano, one_call_then_done("failed"), port=8795)
    assert not [e for e in received if e.get("item", {}).get("type") == "function_call_output"]
    assert [e["type"] for e in received].count("response.create") == 1   # only the typed turn's own
    assert "dropped shake_head" in capsys.readouterr().out


def test_a_cancelled_replys_result_waits_until_the_person_has_finished_talking(poly, silent_audio, fake_voice, nano):
    marks = {}

    async def script(ws, received):
        await asyncio.sleep(0.1)
        await send(ws, type="response.created", response={"id": "r1"})
        await send(ws, type="response.output_item.added", response_id="r1",
                   item={"type": "function_call", "id": "item0", "call_id": "c0", "name": "shake_head"})
        await send(ws, type="response.function_call_arguments.done", response_id="r1", item_id="item0",
                   call_id="c0", name="shake_head", arguments="{}")
        await send(ws, type="input_audio_buffer.speech_started")    # the person cuts in...
        await send(ws, type="response.done", response={"id": "r1", "status": "cancelled"})
        await asyncio.sleep(0.5)
        marks["answered_while_talking"] = any(e.get("item", {}).get("type") == "function_call_output"
                                              for e in received)
        await send(ws, type="input_audio_buffer.speech_stopped")    # ...and finishes
        await asyncio.sleep(2.0)
        await ws.close()
    received = converse(nano, script, port=8796)
    outputs = [e for e in received if e.get("item", {}).get("type") == "function_call_output"]
    assert not marks["answered_while_talking"] and len(outputs) == 1
    assert [e["type"] for e in received].count("response.create") == 2


def test_news_waits_until_the_conversation_is_clear():
    class FakeDialog:
        def __init__(self):
            self.sent = []

        async def system_message(self, text):
            self.sent.append((time.monotonic(), text))

    class Idle:
        busy = type("E", (), {"is_set": staticmethod(lambda: False)})()

    async def go():
        dialog, turns, notes = FakeDialog(), Turns(), asyncio.Queue()
        task = asyncio.create_task(session.pass_on_news(dialog, Idle(), turns, notes))
        turns.tool_calls["r1"] = [{"call_id": "c"}]             # a tool call in flight
        notes.put_nowait("[Background work] done")
        await asyncio.sleep(0.3)
        held_for_tool = not dialog.sent
        turns.tool_calls.clear()
        turns.user_speaking = True                              # then the person talks
        await asyncio.sleep(0.3)
        held_for_speech = not dialog.sent
        turns.user_speaking = False
        turns.auto_reply_until = time.monotonic() + 0.3         # and the server is about to reply
        await asyncio.sleep(0.15)
        held_for_auto_reply = not dialog.sent
        await asyncio.sleep(0.4)
        sent = len(dialog.sent) == 1
        waiting = turns.waiting_for_create()                    # our news's own reply is now pending
        task.cancel()
        return held_for_tool, held_for_speech, held_for_auto_reply, sent, waiting
    assert asyncio.run(go()) == (True, True, True, True, True)


def test_keepalive_on_an_idle_line(monkeypatch):
    async def script(ws, received):
        pass
    monkeypatch.setattr(DialogRSN1, "KEEPALIVE_AFTER_S", 0.3)

    async def go():
        async with fakes.fake_dialog(script, 8795) as (url, received):
            dialog = DialogRSN1(url, "key")
            await dialog.connect("Be brief.", [], [], 16000)
            await asyncio.sleep(1.0)
            await dialog.close()
            return received
    updates = [e for e in asyncio.run(go()) if e["type"] == "session.update"]
    assert updates[0]["session"]["instructions"] == "Be brief." and {"session": {}, "type": "session.update"} in updates[1:]


def test_out_of_domain_is_shown(poly, silent_audio, fake_voice, nano, capsys):
    async def script(ws, received):
        await asyncio.sleep(0.1)
        await send(ws, type="response.created", response={"id": "r1"})
        await send(ws, type="response.output_text.delta", delta="I can't help with that.")
        await send(ws, type="response.output_text.done")
        await send(ws, type="response.done", response={"id": "r1", "status": "completed", "poly_out_of_domain": True})
        await asyncio.sleep(0.5)
        await ws.close()
    converse(nano, script, port=8796)
    assert "[out of domain]" in capsys.readouterr().out
