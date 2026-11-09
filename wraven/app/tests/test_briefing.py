"""What Raven is told: prompts in order, editor notes removed, knowledge topics, tool groups."""
import settings
import tools
from conversation_runtime import briefing


def test_prompts_join_in_filename_order_without_editor_notes(tmp_path, monkeypatch):
    (tmp_path / "tools").mkdir()
    (tmp_path / "2-second.md").write_text("<!-- note for editors -->\nSecond.")
    (tmp_path / "1-first.md").write_text("First.")
    monkeypatch.setattr(settings, "PROMPTS_DIR", tmp_path)
    assert briefing.instructions([], tools.Context()) == "First.\n\nSecond."


def test_knowledge_topics_from_files(tmp_path, monkeypatch):
    (tmp_path / "hours.md").write_text("# Opening hours\nNine to five.")
    (tmp_path / "parking.md").write_text("Behind the building.")       # no heading: name from file
    (tmp_path / "_draft.md").write_text("# Not yet\nskip me")
    (tmp_path / "README.md").write_text("# Knowledge\nhow this folder works")
    monkeypatch.setattr(settings, "KNOWLEDGE_DIR", tmp_path)
    assert briefing.knowledge() == [{"name": "Opening hours", "content": "Nine to five."},
                                    {"name": "parking", "content": "Behind the building."}]


def test_project_tools_and_prompt_only_when_project_work_is_set_up():
    off, off_tools, _ = briefing.build(tools.Context(wren=None))
    on, on_tools, _ = briefing.build(tools.Context(wren=object()))
    names = lambda defs: {d["name"] for d in defs}
    assert names(off_tools) == {"caw", "turn_head", "shake_head", "set_eyes"}
    assert names(on_tools) == names(off_tools) | {"draft_project_task", "start_project_task",
                                                  "project_task_status", "answer_project_question"}
    assert "draft_project_task" in on and "draft_project_task" not in off
    assert "<!--" not in on


def test_nothing_the_model_sees_about_project_work_names_wren_except_the_twin_rule():
    instructions, definitions, _ = briefing.build(tools.Context(wren=object()))
    for definition in definitions:
        assert "wren" not in str(definition).lower()
    mentions = [p for p in instructions.split("\n\n") if "Wren" in p]
    assert len(mentions) == 1 and "twin" in mentions[0]
