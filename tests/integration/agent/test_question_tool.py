"""
Module: test_question_tool
Layer: integration/agent
Covers: agent/question_tool.py

Agent 用户询问工具的交互流程
"""

import threading
import time
import tempfile
from unittest.mock import patch

import pytest

from agent.tool_runner import AgentToolRunner
from lib.inventory_paths import create_managed_dataset_yaml_path

OTHER_OPTION = "\u5176\u4ed6\uff1a\u8bf7\u8f93\u5165"


@pytest.fixture
def runner():
    with tempfile.TemporaryDirectory(prefix="ln2_question_") as install_root, patch(
        "lib.inventory_paths.get_install_dir",
        return_value=install_root,
    ):
        yaml_path = create_managed_dataset_yaml_path("question")
        with open(yaml_path, "w", encoding="utf-8") as handle:
            handle.write("inventory: []\nmeta:\n  box_layout: {rows: 9, cols: 9}\n")
        yield AgentToolRunner(yaml_path=str(yaml_path))


# --- Validation ---

class TestQuestionValidation:
    def test_missing_question(self, runner):
        result = runner.run("question", {"options": ["yes", "no"]})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "question" in result["message"]

    def test_missing_options(self, runner):
        result = runner.run("question", {"question": "Continue?"})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "options" in result["message"]

    def test_options_must_be_array(self, runner):
        result = runner.run("question", {"question": "Continue?", "options": "yes"})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "options" in result["message"]

    def test_options_count_range(self, runner):
        result = runner.run("question", {"question": "Continue?", "options": ["yes"]})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "2 to 5" in result["message"]

    def test_option_must_be_string(self, runner):
        result = runner.run("question", {"question": "Continue?", "options": ["yes", 2]})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "options[1]" in result["message"]

    def test_option_must_be_non_empty(self, runner):
        result = runner.run("question", {"question": "Continue?", "options": ["yes", "  "]})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert "options[1]" in result["message"]

    def test_valid_returns_waiting(self, runner):
        result = runner.run(
            "question",
            {"question": "Continue?", "options": ["yes", "no"]},
        )
        assert result["ok"] is True
        assert result["waiting_for_user"] is True
        assert "question_id" in result
        assert result["question"] == "Continue?"
        assert result["options"] == ["yes", "no", OTHER_OPTION]

    def test_rejects_reserved_other_option(self, runner):
        result = runner.run(
            "question",
            {"question": "Continue?", "options": ["yes", OTHER_OPTION]},
        )
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"
        assert OTHER_OPTION in result["message"]

    def test_rejects_legacy_questions_payload(self, runner):
        result = runner.run(
            "question",
            {
                "questions": [
                    {"header": "Cell", "question": "Which cell?", "options": ["K562", "HeLa"]},
                ]
            },
        )
        assert result["ok"] is False
        assert result["error_code"] == "invalid_tool_input"


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

        result = runner.run(
            "question",
            {"question": "New?", "options": ["yes", "no"]},
        )
        assert result["ok"] is True
        # Event should be cleared after new question
        assert not runner._answer_event.is_set()
        assert runner._pending_answer is None


# --- Tool listing ---

class TestToolListing:
    def test_question_in_list_tools(self, runner):
        tools = runner.list_tools()
        assert "question" in tools

    def test_question_in_tool_schemas(self, runner):
        schemas = runner.tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "question" in names
        question_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "question"),
            None,
        )
        assert question_schema is not None
        required = question_schema.get("function", {}).get("parameters", {}).get("required", [])
        assert required == ["question", "options"]
