"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The whole conversation, against a fake Dialog-RSN-1 server, with silent audio."""
import asyncio
import json
import time

import httpx
import pytest
import websockets

import settings
from conversation_runtime import session
from hardware.body import Body
from tests import fakes


@pytest.fixture
def poly(monkeypatch):
    monkeypatch.setenv("POLY_API_KEY", "test-key")
    monkeypatch.setattr(settings, "WREN_PROJECTS", {})  # project work off unless a test turns it on


def run_conversation(nano, script, typed=None, port=8790, seconds=15):
    async def go():
        async with fakes.fake_dialog(script, port) as (url, received):
            settings.POLY_URL = url
            try:
                await asyncio.wait_for(session.run(nano, Body(nano), typed), seconds)
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                pass  # the fake server hanging up ends the conversation, as in real use
            return received
    return asyncio.run(go())


def test_sentences_tools_and_knowledge(poly, silent_audio, fake_voice, nano, capsys):
    async def script(ws, received):
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "response.created", "response": {"id": "r1"}}))
        for piece in ["[amu", "sed] Well,", " well. A vis", "itor!"]:  # tag and sentences split mid-word
            await ws.send(json.dumps({"type": "response.output_text.delta", "delta": piece}))
        await ws.send(json.dumps({"type": "response.output_text.done"}))
        await ws.send(json.dumps({"type": "response.function_call_arguments.done", "name": "turn_head",
                                  "call_id": "c1", "arguments": '{"direction": "left"}'}))
        await ws.send(json.dumps({"type": "response.done", "response": {
            "status": "completed", "poly_cited_topics": ["PolyAI"]}}))
        await asyncio.sleep(0.2)
        await fakes.server_reply(ws, "r2", "There.")
    received = run_conversation(nano, script, typed=["Hello"])
    setup = received[0]["session"]
    assert setup["poly_knowledge"][0]["name"] == "PolyAI"
    assert {"caw", "turn_head", "shake_head", "set_eyes", "draft_project_task"} <= {t["name"] for t in setup["tools"]}
    assert fake_voice == ["Well, well.", "A visitor!", "There."]  # emotion tag never spoken
    result = next(e for e in received if e["type"] == "conversation.item.create"
                  and e["item"]["type"] == "function_call_output")
    assert json.loads(result["item"]["output"]) == {"ok": True}
    assert "[knowledge] used: PolyAI" in capsys.readouterr().out


def test_talking_over_raven_stops_it_and_reports_what_was_heard(poly, silent_audio, monkeypatch, nano):
    import conversation_runtime.performer as performer
    said = []
    monkeypatch.setattr(performer, "synthesize",
                        lambda text, rate: (said.append(text), (fakes.np.full(rate, 0.05, fakes.np.float32), rate))[1])

    async def script(ws, received):
        await asyncio.sleep(0.2)
        await fakes.server_reply(ws, "r1", "Once upon a time there was a raven. It was very clever. It lived in a tower.")
        await asyncio.sleep(1.5)                                      # mid-way through the story
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_stopped"}))
        await fakes.server_reply(ws, "r2", "Fine, I'll stop.")
        await asyncio.sleep(1.5)
        await ws.close()
    received = run_conversation(nano, script, port=8791)
    reports = [e for e in received if e["type"].startswith("poly.output_audio")]
    stopped = next(e for e in reports if e["type"] == "poly.output_audio.stopped" and e["response_id"] == "r1")
    assert stopped["dropped_ms"] > 0 and stopped["spoken_text"].startswith("Once upon a time")
    assert "It lived in a tower." not in stopped["spoken_text"]
    assert any(e["type"] == "input_audio_buffer.append" for e in received)  # the mic kept streaming
    assert "Fine, I'll stop." in said



def test_cutting_in_straight_away_still_reports_what_was_heard(poly, silent_audio, monkeypatch, nano):
    """Interrupted before the first 250 ms report (or before any sound came out):
    the server must still be told, or it assumes the whole reply was heard."""
    import time
    import conversation_runtime.performer as performer

    def slow_voice(text, rate):
        time.sleep(0.3)  # the voice is still being made when the person cuts in
        return fakes.np.full(rate, 0.05, fakes.np.float32), rate
    monkeypatch.setattr(performer, "synthesize", slow_voice)

    async def script(ws, received):
        await asyncio.sleep(0.2)
        await fakes.server_reply(ws, "r1", "Your code is 4 8 1 5. Write it down.")
        await asyncio.sleep(0.05)                                     # cut in at once
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
        await asyncio.sleep(1.0)
        await ws.close()
    received = run_conversation(nano, script, port=8797)
    reports = [e["type"] for e in received if e.get("response_id") == "r1" and e["type"].startswith("poly.output_audio")]
    assert reports[:1] == ["poly.output_audio.started"] and "poly.output_audio.stopped" in reports
    stopped = next(e for e in received if e["type"] == "poly.output_audio.stopped" and e["response_id"] == "r1")
    assert "4 8 1 5" not in stopped["spoken_text"]

def test_background_news_waits_for_a_quiet_moment(poly, silent_audio, fake_voice, monkeypatch, nano):
    monkeypatch.setattr(settings, "WREN_PROJECTS", {"Demo restaurant": "AGENT-1"})
    monkeypatch.setattr(settings, "WREN_ACCOUNT_ID", "acct")
    monkeypatch.setenv("POLYAI_PAT", "t")
    import integrations.wren as wren_module

    async def wren_handler(request):
        return fakes.wren_events("Added the topic on branch wren/x.", gap=0.5)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(wren_module.httpx, "AsyncClient",
                        lambda **kw: real_client(base_url="https://wren.test", transport=httpx.MockTransport(wren_handler)))
    timeline = {}

    async def script(ws, received):
        async def wait_for(predicate):
            while not any(predicate(e) for e in received):
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        await fakes.server_reply(ws, "r1", "Shall I go ahead?", tool=("draft_project_task", {"task": "Add a topic"}))
        await wait_for(lambda e: e.get("item", {}).get("type") == "function_call_output")
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))   # "yes"
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_stopped"}))
        await fakes.server_reply(ws, "r2", "On it.", tool=("start_project_task", {}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))   # chatting meanwhile
        timeline["talking"] = time.monotonic()
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_stopped"}))
        timeline["stopped"] = time.monotonic()
        await fakes.server_reply(ws, "r3", "Ha.")
        await wait_for(lambda e: e.get("item", {}).get("role") == "system")
        timeline["news"] = time.monotonic()
        await ws.close()
    received = run_conversation(nano, script, port=8792)
    news = next(e for e in received if e.get("item", {}).get("role") == "system")["item"]["content"][0]["text"]
    assert news.startswith("[Background work]") and "wren/" not in news
    assert timeline["news"] > timeline["stopped"]  # not while the person was talking
