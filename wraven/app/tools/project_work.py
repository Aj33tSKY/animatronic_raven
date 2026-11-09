"""
Project work on the person's PolyAI projects, done by Wren (PolyAI's agent
builder, integrations/wren.py) behind the scenes. Raven presents the work as
its own, so nothing here that the model sees mentions Wren. The framing is in
prompts/tools/project-work.md.

Nothing starts without the person's go-ahead: Raven drafts a task, reads it
back, and start_project_task is refused until the person has spoken since the
read-back. That's enforced here, not just asked of the model.
"""
import re
import time

import settings
from tools import tool

PROMPT = "project-work.md"


def enabled(context):
    return context.wren is not None


def prompt_extra(context):
    return "The person's projects are: " + ", ".join(settings.WREN_PROJECTS) + "."


def _task_parameters():
    projects = list(settings.WREN_PROJECTS)
    return {"type": "object", "properties": {
        "project": {"type": "string", "enum": projects},
        "task": {"type": "string", "description": "The work, written out in full, "
                 "including everything the person said that matters."},
        "follow_up_job": {"type": "integer", "description": "Optional: continue from an "
                          "earlier job (its job number)."}},
        # With one project, Raven doesn't have to say which
        "required": ["task"] if len(projects) == 1 else ["project", "task"]}


@tool("draft_project_task",
      "Write down a piece of work on one of the person's PolyAI projects: answering how an "
      "agent is set up, reviewing or analysing its conversations, or building and editing "
      "it. This does NOT start it. Afterwards, read the task back in a sentence or two and "
      "ask whether to go ahead. If they add or change anything, call this again with the "
      "complete, updated task.",
      _task_parameters)
def draft_project_task(context, task, project=None, follow_up_job=None):
    only = next(iter(settings.WREN_PROJECTS)) if len(settings.WREN_PROJECTS) == 1 else None
    project = project or only
    if project not in settings.WREN_PROJECTS:
        return {"error": f"unknown project {project!r}"}
    context.wren.draft = {"project": project, "request": task, "follow_up": follow_up_job,
                          "turn": context.user_turns, "time": time.monotonic()}
    print(f"[wren] draft (not sent yet): {task}")
    return {"status": "drafted, not started", "task": task,
            "next": "Read this back to the person and ask whether to go ahead."}


@tool("start_project_task",
      "Start the drafted task in the background. Only call this after the person has "
      "clearly confirmed your read-back (for example 'yes', 'go ahead', 'do it'). It takes "
      "a few minutes; you'll get a [Background work] message when it's done. Edits go on a "
      "branch for review and are never published to live.")
def start_project_task(context):
    wren = context.wren
    draft = getattr(wren, "draft", None)
    if not draft:
        return {"error": "There's no drafted task. Draft one and read it back first."}
    if time.monotonic() - draft["time"] > settings.WREN_DRAFT_EXPIRES_S:
        wren.draft = None
        return {"error": "That draft is too old. Draft it again and read it back."}
    if context.user_turns <= draft["turn"]:
        return {"error": "The person hasn't answered your read-back yet. "
                         "Read the task back and wait for them to confirm."}
    wren.draft = None
    job = wren.start(draft["project"], draft["request"], draft["follow_up"])
    print(f"[wren] job {job.number} sent to Wren ({job.project}): {job.request}")
    note = (f"You're still finishing job {job.after.number} on this project, so this "
            "starts straight after it." if job.status == "queued" else
            "This takes a few minutes. Tell the person you're on it.")
    return {"status": "started", "job": job.number, "note": note}


@tool("project_task_status",
      "Check on your background project work: what's still running, for how long, the "
      "current step, and what finished jobs found.")
def project_task_status(context):
    return {"jobs": [job.describe() for job in context.wren.jobs] or "no project work yet"}


@tool("answer_project_question",
      "Pass on the person's answer to a question or plan that came up in your background "
      "work. Only call this after they've clearly told you.",
      {"type": "object", "properties": {
          "job": {"type": "integer"},
          "approved": {"type": "boolean", "description": "For a plan: did they approve it?"},
          "answer": {"type": "string", "description": "Their answer, or what to change."}},
       "required": ["job"]})
def answer_project_question(context, job, approved=None, answer=""):
    found = context.wren.find(job)
    if found is None:
        return {"error": f"there's no job {job}"}
    context.wren.answer(found, approved, answer)
    print(f"[wren] job {found.number}: sent the person's answer")
    return {"status": "passed on", "job": found.number}


def background_note(job, kind):
    """The [Background work] message that tells Raven what happened to a job."""
    where = f"Job {job.number} on the {job.project} project"
    first_person = ("Speak about it as your own work, in first person ('I've...', "
                    "'I found...', 'I couldn't...'), and don't mention Wren. Don't read out "
                    "branch names or IDs; just say it's on a branch for review.")
    # Wren names its branches "wren/..."; keep that out of what Raven might say
    report = re.sub(r"\bwren/", "", job.report, flags=re.IGNORECASE)
    if kind == "done":
        decided = [step[9:] for step in job.steps if step.startswith("decided: ")]
        choices = ("\nChoices you made yourself along the way, without asking: " +
                   "; ".join(decided) + ". Mention any that matter, so the person can change "
                   "them.") if decided else ""
        return (f"[Background work] {where} is finished, after {job.minutes:.0f} minutes. "
                f"Your report:\n{report[:2500] or '(no report)'}{choices}\n"
                f"Tell the person what you did or found, in one to three sentences. {first_person}")
    if kind == "question":
        return (f"[Background work] {where} needs a decision before you can continue:\n"
                f"{job.question['text'][:2000]}\n"
                "Explain it to the person and ask what they want. Call answer_project_question "
                f"only once they've clearly told you. {first_person}")
    return (f"[Background work] {where} failed: {job.error}. Tell the person briefly, in plain "
            f"words with no error codes, that you couldn't finish it. {first_person}")
