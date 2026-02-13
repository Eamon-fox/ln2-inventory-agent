"""Tests for the question tool in AgentToolRunner."""

import threading
import time

import pytest

from agent.tool_runner import AgentToolRunner


@pytest.fixture
def runner(tmp_path):
    yaml_path = tmp_path / "test_inventory.yaml"
    yaml_path.write_text("inventory: []\nmeta:\n  box_layout: {rows: 9, cols: 9}\n")
    return AgentToolRunner(yaml_path=str(yaml_path))


# --- Validation ---

class TestQuestionValidation:
    def test_no_questions(self, runner):
        result = runner.run("question", {"questions": []})
        assert result["ok"] is False
        assert result["error_code"] == "no_questions"

    def test_missing_questions_key(self, runner):
        result = runner.run("question", {})
        assert result["ok"] is False
        assert result["error_code"] == "no_questions"

    def test_non_dict_question(self, runner):
        result = runner.run("question", {"questions": ["not a dict"]})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_question_format"

    def test_missing_header(self, runner):
        result = runner.run("question", {"questions": [{"question": "Hello?"}]})
        assert result["ok"] is False
        assert result["error_code"] == "missing_required_field"

    def test_missing_question_text(self, runner):
        result = runner.run("question", {"questions": [{"header": "Test"}]})
        assert result["ok"] is False
        assert result["error_code"] == "missing_required_field"

    def test_valid_returns_waiting(self, runner):
        result = runner.run("question", {
            "questions": [{"header": "Test", "question": "Hello?"}]
        })
        assert result["ok"] is True
        assert result["waiting_for_user"] is True
        assert "question_id" in result
        assert len(result["questions"]) == 1

    def test_multiple_questions(self, runner):
        result = runner.run("question", {
            "questions": [
                {"header": "Cell", "question": "Which cell?", "options": ["K562", "HeLa"]},
                {"header": "Box", "question": "Which box?"},
            ]
        })
        assert result["ok"] is True
        assert len(result["questions"]) == 2


# --- Threading synchronization ---

class TestAnswerSync:
    def test_set_answer(self, runner):
        """Verify _set_answer unblocks _answer_event."""
        runner._answer_event.clear()

        def delayed_answer():
            time.sleep(0.05)
            runner._set_answer(["K562-dTAG"])

        threading.Thread(target=delayed_answer).start()

        answered = runner._answer_event.wait(timeout=5)
        assert answered is True
        assert runner._pending_answer == ["K562-dTAG"]
        assert runner._answer_cancelled is False

    def test_cancel_answer(self, runner):
        """Verify _cancel_answer unblocks _answer_event with cancelled flag."""
        runner._answer_event.clear()

        def delayed_cancel():
            time.sleep(0.05)
            runner._cancel_answer()

        threading.Thread(target=delayed_cancel).start()

        runner._answer_event.wait(timeout=5)
        assert runner._answer_cancelled is True
        assert runner._pending_answer is None

    def test_event_reset_on_new_question(self, runner):
        """Each question call resets the event state."""
        runner._set_answer(["old answer"])
        assert runner._answer_event.is_set()

        result = runner.run("question", {
            "questions": [{"header": "Test", "question": "New?"}]
        })
        assert result["ok"] is True
        # Event should be cleared after new question
        assert not runner._answer_event.is_set()
        assert runner._pending_answer is None


# --- Tool listing ---

class TestToolListing:
    def test_question_in_list_tools(self, runner):
        tools = runner.list_tools()
        assert "question" in tools

    def test_question_in_tool_specs(self, runner):
        specs = runner.tool_specs()
        assert "question" in specs
        assert specs["question"]["required"] == ["questions"]

    def test_question_in_tool_schemas(self, runner):
        schemas = runner.tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "question" in names
