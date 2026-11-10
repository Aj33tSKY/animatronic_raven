#!/usr/bin/env python3
"""
BOILERPLATE: Dialog-RSN-1 plumbing, the same for any agent. No need to edit it to build one.

Wren, PolyAI's agent builder, as a background helper for Raven.

Raven drafts a request, reads it back, and only sends it once the person
confirms. Wren can take minutes, so each request runs in the background while
the conversation goes on. When Wren finishes, fails, or needs an answer, Raven is told and speaks up.

Wren's API (docs.poly.ai/wren/api) streams server-sent events, but the docs
don't list the event types or their fields. So events are read loosely, and
every raw event is saved to logs/wren-YYYY-MM-DD.jsonl. To see exactly what a
run sends, run this file on its own:

    python wren.py --project pizza "What topics does this project have?"

Needs POLYAI_PAT (a personal access token) in .env, plus the WREN_ settings
in settings.py.
"""
import argparse
import asyncio
import datetime
import json
import os
import time
from pathlib import Path

import httpx

import settings

LOG_DIR = settings.LOGS_DIR
SESSION_KEYS = ("sessionId", "session_id", "conversationId", "conversation_id")
TEXT_KEYS = ("text", "message", "content", "summary", "report", "markdown", "body")


class WrenJob:
    """One request to Wren, and everything it has said back."""

    def __init__(self, number, project, request):
        self.number = number
        self.project = project
        self.request = request
        self.status = "working"     # queued, working, needs_answer, done or failed
        self.session_id = None      # Wren's conversation, for answers and follow-ups
        self.steps = []             # short progress notes
        self.report = ""            # Wren's latest message; its final report once done
        self.question = None        # what Wren is waiting on: {"request_id", "kind", "text", "count"}
        self.last_words = ""        # the latest thing Wren's main agent said
        self.finished = False       # Wren's main agent has completed the run
        self.after = None           # queued behind this earlier job on the same project
        self.error = None
        self.started_at = time.monotonic()

    @property
    def minutes(self):
        return (time.monotonic() - self.started_at) / 60

    def describe(self):
        """A short summary for Raven's wren_status tool."""
        info = {"job": self.number, "project": self.project, "request": self.request[:200],
                "status": self.status, "minutes_so_far": round(self.minutes, 1)}
        plans = [step for step in self.steps if step.startswith("plan: ")]
        if plans:
            info["task"] = plans[-1][6:]
        if self.steps:
            info["steps_so_far"] = len(self.steps)
            info["latest_step"] = self.steps[-1]
        if self.status == "queued" and self.after:
            info["queued_behind_job"] = self.after.number
        if self.question:
            info["waiting_for"] = self.question["text"][:500]
        if self.status == "done":
            info["report"] = self.report[:800]
        if self.error:
            info["error"] = self.error
        return info


class Wren:
    def __init__(self, on_update=None, client=None):
        self.token = os.environ.get("POLYAI_PAT")
        self.jobs = []
        self.on_update = on_update or (lambda job, kind: None)  # kind: done, question or failed
        self.client = client or httpx.AsyncClient(
            base_url=settings.WREN_BASE_URL,
            timeout=httpx.Timeout(30, read=settings.WREN_READ_TIMEOUT_S))

    @property
    def ready(self):
        return bool(self.token and settings.WREN_ACCOUNT_ID and settings.WREN_PROJECTS)

    def find(self, number):
        return next((job for job in self.jobs if job.number == number), None)

    def start(self, project, request, follow_up=None):
        """Send a (confirmed) request to Wren and return its job straight away."""
        if project not in settings.WREN_PROJECTS:
            raise ValueError(f"unknown project {project!r}; known: {', '.join(settings.WREN_PROJECTS)}")
        job = WrenJob(len(self.jobs) + 1, project, request)
        earlier = self.find(follow_up) if follow_up else None
        if earlier and earlier.session_id and earlier.project == project:
            job.session_id = earlier.session_id  # carry on in that job's Wren conversation
        self.jobs.append(job)
        # Two runs editing one project at once trip over each other's branch, so
        # wait for the current one, then carry on in its conversation
        busy = [other for other in self.jobs[:-1]
                if other.project == project and other.status in ("working", "queued")]
        if busy:
            job.status, job.after = "queued", busy[-1]
            return job
        # Keep one ongoing Wren conversation per project, so Wren remembers what it
        # already did (unless that conversation is waiting on the person)
        if not job.session_id:
            done = [other for other in self.jobs[:-1] if other.project == project
                    and other.session_id and other.status in ("done", "failed")]
            if done:
                job.session_id = done[-1].session_id
        asyncio.create_task(self._run(job, {"prompt": request}))
        return job

    def _start_queued(self, finished):
        for job in self.jobs:
            if job.status == "queued" and job.after is finished:
                job.session_id = job.session_id or finished.session_id
                job.started_at = time.monotonic()
                asyncio.create_task(self._run(job, {"prompt": job.request}))

    def answer(self, job, approved=None, answer=""):
        """Send the person's answer to the question or plan Wren is waiting on."""
        question = job.question
        if not question:
            raise ValueError(f"job {job.number} isn't waiting for an answer")
        if question["kind"] == "plan":
            value = {"approved": bool(approved)}
            if not approved and answer:
                value["feedback"] = answer
        else:
            value = {"answers": [{"selected": [], "freeform": answer}] * max(1, question["count"])}
        job.question = None
        asyncio.create_task(self._run(job, {
            "type": "input_response", "requestId": question["request_id"],
            "answer": {"inputKind": question["kind"], "value": value}}))

    async def _run(self, job, body):
        body["context"] = {"accountId": settings.WREN_ACCOUNT_ID,
                           "projectId": settings.WREN_PROJECTS[job.project],
                           "mode": settings.WREN_MODE}
        if job.session_id:
            body["sessionId"] = job.session_id
        job.status, job.error, job.finished = "working", None, False
        try:
            async with self.client.stream("POST", "/v1/studio-assistant/turn", json=body,
                                          headers={"x-api-key": self.token}) as response:
                if response.status_code != 200:
                    detail = (await response.aread()).decode(errors="replace")[:300]
                    raise RuntimeError(f"HTTP {response.status_code}: {detail}")
                async for name, data in sse_events(response):
                    self._log(job, name, data)
                    self._read(job, name, data)
                    if job.status == "failed" or job.finished:
                        break  # the stream can stay open after the run ends
        except Exception as error:  # never leave a job stuck on "working"
            if not job.finished:
                job.status, job.error = "failed", f"{type(error).__name__}: {error}"
        if job.status == "failed":
            self.on_update(job, "failed")
        elif job.question:
            job.status = "needs_answer"
            self.on_update(job, "question")
        else:
            job.status = "done"
            self.on_update(job, "done")
        if job.status != "needs_answer":
            self._start_queued(job)

    def _read(self, job, name, data):
        """Pull what matters out of one event.

        Seen on real runs: `depth` 0 is Wren's main agent, 1+ its helpers. The
        main agent's set_plan tool call names the task, tool_execution_end shows
        each step, the final answer is a submit_report tool call, and `complete`
        at depth 0 that isn't `suspended` ends the run. Questions for the person
        (user_input_required) and errors are matched more loosely, as they
        haven't been seen live yet."""
        kind = (data.get("type") or name or "").lower()
        depth = int(data.get("depth") or 0)
        job.session_id = job.session_id or find_key(data, SESSION_KEYS)
        if kind == "user_input_answered":
            # In auto mode Wren answers its own questions straight away
            if job.question and data.get("requestId") in (None, job.question["request_id"]):
                job.question = None
            value = data.get("value") if isinstance(data.get("value"), dict) else {}
            answers = [a for a in value.get("answers") or [] if isinstance(a, dict)]
            chosen = "; ".join(", ".join(a.get("selected") or []) or a.get("freeform", "")
                               for a in answers)
            if value.get("approved") is not None:
                chosen = "approved the plan" if value["approved"] else "rejected the plan"
            job.steps.append(f"decided: {chosen}" if data.get("auto") else f"answered: {chosen}")
        elif "user_input_required" in kind:
            job.question = {"request_id": find_key(data, ("requestId", "request_id")),
                            "kind": find_key(data, ("inputKind", "input_kind")) or "question",
                            "text": " ".join(texts(data))[:3000] or "(no details)",
                            "count": len(find_key(data, ("questions",)) or []) or 1}
        elif kind == "error" or (kind.endswith("error") and not data.get("toolName")):
            if job.finished:
                return  # a late error after the run already finished
            job.status = "failed"
            job.error = (find_key(data, ("errorCode", "error_code")) or "error") + ": " + \
                " ".join(texts(data))[:300]
        elif kind == "message_end" and depth == 0:
            message = data.get("message")
            for block in (message.get("content") or []) if isinstance(message, dict) else []:
                if not isinstance(block, dict):
                    continue
                args = block.get("arguments") if isinstance(block.get("arguments"), dict) else {}
                if block.get("type") == "toolCall" and block.get("name") == "set_plan":
                    job.steps.append(f"plan: {args.get('title', '')}")
                elif block.get("type") == "toolCall" and block.get("name") == "submit_report":
                    title = args.get("title")
                    job.report = (f"{title}\n\n" if title else "") + (args.get("report") or "")
                elif block.get("type") == "text" and block.get("text") and not job.report:
                    job.last_words = block["text"]  # Wren talking, kept in case there's no report
        elif kind == "tool_execution_end" and data.get("toolName") not in ("set_plan", "submit_report"):
            failed = " (failed)" if data.get("isError") else ""
            job.steps.append(f"{data.get('toolName', 'step')}{failed}")
        elif kind == "complete" and depth == 0 and not data.get("suspended"):
            job.report = job.report or job.last_words
            job.finished = True

    def _log(self, job, name, data):
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / f"wren-{datetime.date.today()}.jsonl"
        with path.open("a") as log:
            log.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                                  "job": job.number, "event": name, "data": data}) + "\n")


async def sse_events(response):
    """Yield (event name, JSON data) from a server-sent event stream."""
    name, lines = None, []
    async for line in response.aiter_lines():
        if line == "":
            if lines:
                raw = "\n".join(lines)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"text": raw}
                yield name, data if isinstance(data, dict) else {"value": data}
            name, lines = None, []
        elif line.startswith(":"):
            continue  # keepalive comment
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip())


def find_key(value, keys):
    """The first value under any of these keys, searching nested dicts and lists."""
    if isinstance(value, dict):
        for key in keys:
            if value.get(key):
                return value[key]
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        found = find_key(child, keys)
        if found:
            return found
    return None


def texts(value):
    """Human-readable strings in an event, from fields that usually hold text."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in TEXT_KEYS and isinstance(child, str):
                found.append(child)
            elif isinstance(child, (dict, list)):
                found += texts(child)
    elif isinstance(value, list):
        for child in value:
            found += texts(child)
    return found


async def probe(project, prompt):
    """Run one Wren request and print every raw event, to learn the event format."""
    def on_update(job, kind):
        print(f"\n=== job {kind} after {job.minutes:.1f} min ===")
        print(json.dumps(job.describe(), indent=2))
    wren = Wren(on_update)
    if not wren.ready:
        raise SystemExit("Set POLYAI_PAT in .env and WREN_ACCOUNT_ID / WREN_PROJECTS in settings.py")
    original_read = wren._read

    def show(job, name, data):
        print(f"[{name or data.get('type')}] {json.dumps(data)[:400]}")
        original_read(job, name, data)
    wren._read = show
    job = wren.start(project, prompt)
    while job.status in ("queued", "working"):
        await asyncio.sleep(0.5)
    await asyncio.sleep(0.1)
    print(f"\nRaw events saved to {LOG_DIR}/wren-{datetime.date.today()}.jsonl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send one request to Wren and show its raw events.")
    parser.add_argument("--project", required=True, help="a name from WREN_PROJECTS in settings.py")
    parser.add_argument("prompt")
    args = parser.parse_args()
    asyncio.run(probe(args.project, args.prompt))
