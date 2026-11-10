"""BOILERPLATE (tests): checks the plumbing still works. Run with: python -m pytest

The project-work client, against a fake Wren speaking Wren's real event format."""
import asyncio
import json

import pytest

import settings
from integrations import wren as wren_module
from tests.fakes import wren_client, wren_events


@pytest.fixture(autouse=True)
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WREN_ACCOUNT_ID", "acct")
    monkeypatch.setattr(settings, "WREN_PROJECTS", {"Demo restaurant": "AGENT-1"})
    monkeypatch.setenv("POLYAI_PAT", "test-token")
    monkeypatch.setattr(wren_module, "LOG_DIR", tmp_path)


async def finish(job, seconds=5):
    for _ in range(int(seconds / 0.02)):
        if job.status not in ("working", "queued"):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job.number} still {job.status}")


def test_a_run_ends_with_its_report_and_wrens_own_decisions():
    decided = {"type": "user_input_answered", "inputKind": "question", "auto": True, "requestId": "q1",
               "value": {"answers": [{"selected": ["Keep placeholders"]}]}}
    asked = {"type": "user_input_required", "inputKind": "question", "requestId": "q1",
             "questions": [{"question": "Keep placeholders?"}]}
    late_error = {"type": "error", "errorCode": "internal", "message": "Something went wrong"}

    async def handler(request):
        response = wren_events("Added two topics on branch wren/topics.", extra=[asked, decided])
        return response
    updates = []

    async def go():
        w = wren_module.Wren(lambda job, kind: updates.append(kind), client=wren_client(handler))
        job = w.start("Demo restaurant", "Add two topics")
        await finish(job)
        return job
    job = asyncio.run(go())
    assert job.status == "done" and updates == ["done"] and job.question is None
    assert job.report.endswith("Added two topics on branch wren/topics.")
    assert "decided: Keep placeholders" in job.steps


def test_a_late_error_after_the_run_finished_is_ignored():
    async def handler(request):
        import httpx

        async def body():
            for event in ({"type": "message_end", "depth": 0, "sessionId": "s", "message": {"content": [
                              {"type": "toolCall", "name": "submit_report", "arguments": {"report": "ok"}}]}},
                          {"type": "complete", "depth": 0, "suspended": False, "sessionId": "s"},
                          {"type": "error", "errorCode": "internal", "message": "Something went wrong"}):
                yield ("data: " + json.dumps(event) + "\n\n").encode()
        return httpx.Response(200, content=body())

    async def go():
        job = wren_module.Wren(client=wren_client(handler)).start("Demo restaurant", "x")
        await finish(job)
        return job
    assert asyncio.run(go()).status == "done"


def test_plan_approval_is_sent_with_the_right_session_and_request():
    sent = []

    async def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if body.get("type") == "input_response":
            return wren_events("Done after approval.", session="chat-9")
        import httpx

        async def parked():
            yield b'data: {"type": "user_input_required", "inputKind": "plan", "requestId": "plan-1", "sessionId": "chat-9", "content": "Add a topic"}\n\n'
        return httpx.Response(200, content=parked())

    async def go():
        w = wren_module.Wren(client=wren_client(handler))
        job = w.start("Demo restaurant", "Add a topic")
        await finish(job)
        assert job.status == "needs_answer"
        w.answer(job, approved=True)
        await asyncio.sleep(0.05)
        await finish(job)
        return job
    job = asyncio.run(go())
    answer = sent[1]
    assert job.status == "done"
    assert answer["sessionId"] == "chat-9" and answer["requestId"] == "plan-1"
    assert answer["answer"] == {"inputKind": "plan", "value": {"approved": True}}
    assert answer["context"]["projectId"] == "AGENT-1"


def test_same_project_requests_queue_and_share_one_wren_chat():
    sessions = []

    async def handler(request):
        body = json.loads(request.content)
        sessions.append(body.get("sessionId"))
        return wren_events(body["prompt"], session="chat-1", gap=0.2)

    async def go():
        w = wren_module.Wren(client=wren_client(handler))
        first = w.start("Demo restaurant", "Change the greeting")
        await asyncio.sleep(0.05)
        second = w.start("Demo restaurant", "Also add a menu topic")
        assert second.status == "queued" and second.after is first
        await finish(first)
        await asyncio.sleep(0.05)
        await finish(second)
        third = w.start("Demo restaurant", "And a parking topic")
        await finish(third)
    asyncio.run(go())
    assert sessions == [None, "chat-1", "chat-1"]


def test_an_odd_event_cannot_leave_a_job_stuck():
    import httpx

    async def handler(request):
        return httpx.Response(200, content=b'data: {"type": "message_end", "depth": 0, "message": 12345}\n\n')

    async def go():
        job = wren_module.Wren(client=wren_client(handler)).start("Demo restaurant", "x")
        await finish(job)
        return job
    assert asyncio.run(go()).status in ("done", "failed")
