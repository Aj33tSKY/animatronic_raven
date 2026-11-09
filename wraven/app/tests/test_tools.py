"""The tools: body moves are queued, and project work never starts without a confirmed read-back."""
import time

import settings
import tools
from integrations.wren import WrenJob


class FakePerformer:
    def __init__(self):
        self.queued = []

    def add(self, kind, value, reply_id=None):
        self.queued.append((kind, value))


class FakeWren:
    def __init__(self):
        self.jobs, self.draft = [], None

    def start(self, project, request, follow_up=None):
        job = WrenJob(len(self.jobs) + 1, project, request)
        self.jobs.append(job)
        return job


def context(**kw):
    tools.groups(tools.Context(wren=object()))  # make sure every tool file is loaded
    return tools.Context(performer=FakePerformer(), **kw)


def test_body_tools_queue_moves_and_sounds():
    c = context()
    assert tools.run("turn_head", {"direction": "far_left"}, c) == {"ok": True}
    assert tools.run("caw", {"kind": "scold"}, c) == {"ok": True}
    assert tools.run("set_eyes", {"effect": "pulse"}, c) == {"ok": True}
    assert c.performer.queued == [("act", "look far left"), ("act", "scold"), ("sound", "scold"),
                                  ("act", "eyes pulse")]


def test_bad_calls_come_back_as_errors_for_the_model():
    c = context()
    assert "error" in tools.run("turn_head", {"direction": "upside down"}, c)
    assert "error" in tools.run("turn_head", {}, c)
    assert "error" in tools.run("no_such_tool", {}, c)


def test_project_work_needs_a_confirmed_read_back():
    c = context(wren=FakeWren())
    run = lambda name, turns, **args: tools.run(name, args, _with_turns(c, turns))
    assert "error" in run("start_project_task", 1)                                  # nothing drafted
    run("draft_project_task", 1, task="Change the greeting")
    assert "hasn't answered" in run("start_project_task", 1)["error"]               # same turn
    run("draft_project_task", 2, task="Change the greeting and add two topics")      # they added to it
    assert run("start_project_task", 3)["status"] == "started"                       # they said yes
    assert [job.request for job in c.wren.jobs] == ["Change the greeting and add two topics"]
    run("draft_project_task", 4, task="Old idea")
    c.wren.draft["time"] -= settings.WREN_DRAFT_EXPIRES_S + 1
    assert "too old" in run("start_project_task", 5)["error"]


def _with_turns(c, turns):
    c.user_turns = turns
    return c


def test_example_tool_is_not_loaded():
    names = {d["name"] for d in tools.definitions(tools.groups(tools.Context(wren=object())))}
    assert "roll_dice" not in names
