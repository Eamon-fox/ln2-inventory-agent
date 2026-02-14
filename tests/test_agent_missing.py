"""Missing unit tests for agent/ layer modules.

Tests for:
- tool_runner.py: plan staging, normalization, hints
- react_agent.py: history, parsing, step limits
- llm_client.py: client behavior
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from agent.llm_client import DeepSeekLLMClient
from lib.yaml_ops import create_yaml_backup, load_yaml, write_yaml


def make_record(rec_id=1, box=1, positions=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


# ── tool_runner.py Tests ──────────────────────────────────────────


class ToolRunnerNormalizationTests(unittest.TestCase):
    """Test normalization functions in AgentToolRunner."""

    def test_first_value_fallback_chain(self):
        """Test _first_value tries keys in order."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"key1": None, "key2": "found", "key3": "ignored"}
        result = runner._first_value(payload, "key1", "key2", "key3")
        self.assertEqual("found", result)

    def test_first_value_all_none(self):
        """Test _first_value returns None when all keys missing."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {}
        result = runner._first_value(payload, "key1", "key2")
        self.assertIsNone(result)

    def test_as_bool_various_true(self):
        """Test _as_bool recognizes various True representations."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        true_values = [True, 1, "1", "true", "TRUE", "yes", "YES", "y", "Y", "on", "ON"]
        for val in true_values:
            self.assertTrue(runner._as_bool(val), f"Failed for value: {val}")

    def test_as_bool_various_false(self):
        """Test _as_bool recognizes various False representations."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        false_values = [False, 0, "0", "false", "FALSE", "no", "NO", "n", "N", "off", "OFF", ""]
        for val in false_values:
            self.assertFalse(runner._as_bool(val), f"Failed for value: {val}")

    def test_as_bool_default(self):
        """Test _as_bool default value."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        self.assertTrue(runner._as_bool(None, default=True))
        self.assertFalse(runner._as_bool(None, default=False))

    def test_normalize_positions_list(self):
        """Test _normalize_positions with list."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        result = runner._normalize_positions([1, 2, 3])
        self.assertEqual([1, 2, 3], result)

    def test_normalize_positions_tuple(self):
        """Test _normalize_positions with tuple."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        result = runner._normalize_positions((1, 2, 3))
        self.assertEqual([1, 2, 3], result)

    def test_normalize_positions_single_int(self):
        """Test _normalize_positions with single int."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        result = runner._normalize_positions(5)
        self.assertEqual([5], result)

    def test_normalize_positions_string(self):
        """Test _normalize_positions with string."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        result = runner._normalize_positions("1,2,3")
        self.assertEqual([1, 2, 3], result)

    def test_normalize_positions_none(self):
        """Test _normalize_positions with None."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        result = runner._normalize_positions(None)
        self.assertIsNone(result)


class ToolRunnerPlanStagingTests(unittest.TestCase):
    """Test plan staging functionality in AgentToolRunner."""

    def setUp(self):
        from lib.plan_store import PlanStore
        self.plan_store = PlanStore()

    def _seed_yaml(self, records):
        """Create a temporary inventory YAML file."""
        tmpdir = tempfile.TemporaryDirectory(prefix="tool_runner_stage_")
        self.addCleanup(tmpdir.cleanup)
        yaml_path = Path(tmpdir.name) / "inventory.yaml"
        write_yaml(
            make_data(records),
            path=str(yaml_path),
            auto_backup=False,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return str(yaml_path)

    def test_stage_to_plan_add_entry(self):
        """Test staging add_entry operation."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "add_entry",
            {
                "parent_cell_line": "K562",
                "short_name": "clone-new",
                "box": 1,
                "positions": [2, 3],
                "frozen_at": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("add", self.plan_store.list_items()[0]["action"])
        self.assertEqual(1, self.plan_store.list_items()[0]["box"])

    def test_stage_to_plan_record_thaw(self):
        """Test staging record_thaw operation."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "record_thaw",
            {
                "record_id": 1,
                "position": 5,
                "date": "2026-02-10",
                "action": "取出",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("takeout", self.plan_store.list_items()[0]["action"])
        self.assertEqual(5, self.plan_store.list_items()[0]["position"])

    def test_stage_to_plan_record_thaw_supports_legacy_action_alias(self):
        """Legacy alias 解冻 should normalize to thaw."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "record_thaw",
            {
                "record_id": 1,
                "position": 5,
                "date": "2026-02-10",
                "action": "解冻",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("thaw", self.plan_store.list_items()[0]["action"])

    def test_stage_to_plan_record_thaw_move(self):
        """Test staging record_thaw with move action."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "record_thaw",
            {
                "record_id": 1,
                "position": 5,
                "to_position": 10,
                "date": "2026-02-10",
                "action": "move",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("move", self.plan_store.list_items()[0]["action"])
        self.assertEqual(10, self.plan_store.list_items()[0]["to_position"])

    def test_stage_to_plan_batch_thaw(self):
        """Test staging batch_thaw operation."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "batch_thaw",
            {
                "entries": [(1, 5), (2, 10)],
                "date": "2026-02-10",
                "action": "取出",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(2, len(self.plan_store.list_items()))

    def test_stage_to_plan_batch_thaw_move(self):
        """Test staging batch_thaw with move entries."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "batch_thaw",
            {
                "entries": [(1, 5, 10)],
                "date": "2026-02-10",
                "action": "move",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("move", self.plan_store.list_items()[0]["action"])
        self.assertEqual(10, self.plan_store.list_items()[0]["to_position"])

    def test_stage_to_plan_validation_failure(self):
        """Test plan validation failure with invalid box."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "add_entry",
            {
                "fields": {"parent_cell_line": "K562", "short_name": "x"},
                "box": -1,  # Invalid: negative box
                "positions": [2],
                "frozen_at": "2026-02-10",
            },
        )
        self.assertFalse(result["ok"])
        self.assertEqual("plan_validation_failed", result["error_code"])
        self.assertEqual(0, len(self.plan_store.list_items()))

    def test_stage_to_plan_preflight_blocked_returns_tool_error(self):
        """Invalid staged write should be rejected before entering plan."""
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, positions=[5])])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "record_thaw",
            {
                "record_id": 999,
                "position": 5,
                "date": "2026-02-10",
                "action": "Takeout",
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual("plan_preflight_failed", result["error_code"])
        self.assertEqual(0, len(self.plan_store.list_items()))
        self.assertEqual(1, result.get("result", {}).get("blocked_count"))
        self.assertEqual(1, len(result.get("blocked_items", [])))
        self.assertEqual("record_not_found", result["blocked_items"][0].get("error_code"))

    def test_stage_to_plan_preflight_mixed_batch_rejects_all(self):
        """Mixed-valid batch should be rejected atomically."""
        records = [
            make_record(rec_id=1, box=1, positions=[5]),
            make_record(rec_id=2, box=1, positions=[10]),
        ]
        yaml_path = self._seed_yaml(records)
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "batch_thaw",
            {
                "entries": [(1, 5), (999, 5)],
                "date": "2026-02-10",
                "action": "Takeout",
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual("plan_preflight_failed", result["error_code"])
        self.assertFalse(result.get("staged"))
        self.assertEqual(0, len(self.plan_store.list_items()))
        self.assertEqual(0, result.get("result", {}).get("staged_count"))
        self.assertEqual(1, result.get("result", {}).get("blocked_count"))
        self.assertEqual(1, len(result.get("blocked_items", [])))

    def test_stage_to_plan_schema_mixed_batch_rejects_all(self):
        """Schema errors in batch should reject all items atomically."""
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, positions=[5])])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "batch_thaw",
            {
                "entries": [
                    (1, 5),
                    {"record_id": 2},  # Missing position -> normalized to 0 -> schema invalid
                ],
                "date": "2026-02-10",
                "action": "Takeout",
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual("plan_validation_failed", result["error_code"])
        self.assertFalse(result.get("staged"))
        self.assertEqual(0, len(self.plan_store.list_items()))
        self.assertEqual(0, result.get("result", {}).get("staged_count"))
        self.assertEqual(1, result.get("result", {}).get("blocked_count"))

    def test_stage_to_plan_rollback_resolves_latest_backup(self):
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, positions=[5])])
        backup_path = create_yaml_backup(yaml_path)
        self.assertTrue(os.path.exists(str(backup_path)))

        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan("rollback", {})

        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        staged = self.plan_store.list_items()[0]
        self.assertEqual("rollback", staged.get("action"))
        self.assertEqual(str(backup_path), (staged.get("payload") or {}).get("backup_path"))


class ToolRunnerHintTests(unittest.TestCase):
    """Test error hint generation."""

    def test_hint_for_error_invalid_tool_input(self):
        """Test hint for invalid_tool_input."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_tool_input"}
        hint = runner._hint_for_error("add_entry", payload)
        self.assertIn("Required", hint)
        self.assertIn("Optional", hint)

    def test_hint_for_error_unknown_tool(self):
        """Test hint for unknown_tool."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "unknown_tool", "available_tools": ["tool1", "tool2"]}
        hint = runner._hint_for_error("bad_tool", payload)
        self.assertIn("available tools", hint)
        self.assertIn("tool1", hint)

    def test_hint_for_error_invalid_mode(self):
        """Test hint for invalid_mode."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_mode"}
        hint = runner._hint_for_error("search_records", payload)
        self.assertIn("fuzzy", hint)
        self.assertIn("exact", hint)

    def test_hint_for_error_invalid_date(self):
        """Test hint for invalid_date."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_date"}
        hint = runner._hint_for_error("add_entry", payload)
        self.assertIn("YYYY-MM-DD", hint)

    def test_hint_for_error_record_not_found(self):
        """Test hint for record_not_found."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "record_not_found"}
        hint = runner._hint_for_error("record_thaw", payload)
        self.assertIn("query_inventory", hint)

    def test_hint_for_error_position_conflict(self):
        """Test hint for position_conflict."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "position_conflict"}
        hint = runner._hint_for_error("add_entry", payload)
        self.assertIn("list_empty_positions", hint)

    def test_hint_for_error_invalid_move_target(self):
        """Test hint for invalid_move_target."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_move_target"}
        hint = runner._hint_for_error("record_thaw", payload)
        self.assertIn("to_position", hint)

    def test_hint_for_error_no_backups(self):
        """Test hint for no_backups."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "no_backups"}
        hint = runner._hint_for_error("rollback", payload)
        self.assertIn("backup_path", hint)

    def test_hint_for_error_invalid_box(self):
        """Test hint for invalid_box."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_box"}
        hint = runner._hint_for_error("add_entry", payload)
        self.assertIn("range", hint)

    def test_hint_for_error_plan_preflight_failed(self):
        """Test hint for plan_preflight_failed."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "plan_preflight_failed"}
        hint = runner._hint_for_error("record_thaw", payload)
        self.assertIn("invalid", hint.lower())
        self.assertIn("retry", hint.lower())

    def test_hint_for_error_default_fallback(self):
        """Test default hint fallback."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "unknown_error"}
        hint = runner._hint_for_error("some_tool", payload)
        # When no spec exists for tool, should return general fallback
        self.assertIn("corrected", hint.lower())


class DeepSeekLLMClientMockTests(unittest.TestCase):
    """Test DeepSeekLLMClient with mocked responses."""

    def test_deepseek_client_requires_api_key(self):
        """Test DeepSeekLLMClient requires API key."""
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                DeepSeekLLMClient()


# ── react_agent.py Tests (Unit Tests) ───────────────────────────


class ReactAgentHistoryTests(unittest.TestCase):
    """Test ReactAgent history normalization."""

    def test_normalize_history_filters_invalid_roles(self):
        """Test _normalize_history filters out invalid roles."""
        history = [
            {"role": "user", "content": "msg1"},
            {"role": "system", "content": "sys"},
            {"role": "invalid", "content": "bad"},
            {"role": "assistant", "content": "msg2"},
        ]
        from agent.react_agent import ReactAgent
        result = ReactAgent._normalize_history(history)
        # Should only have user and assistant
        self.assertEqual(2, len(result))
        roles = {r["role"] for r in result}
        self.assertEqual({"user", "assistant"}, roles)

    def test_normalize_history_filters_empty_content(self):
        """Test _normalize_history filters empty content."""
        history = [
            {"role": "user", "content": "valid"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
        ]
        from agent.react_agent import ReactAgent
        result = ReactAgent._normalize_history(history)
        self.assertEqual(1, len(result))

    def test_normalize_history_respects_max_turns(self):
        """Test _normalize_history respects max_turns parameter."""
        history = [
            {"role": "user", "content": f"msg{i}"} for i in range(20)
        ]
        from agent.react_agent import ReactAgent
        result = ReactAgent._normalize_history(history, max_turns=5)
        self.assertEqual(5, len(result))

    def test_normalize_history_preserves_timestamps(self):
        """Test _normalize_history preserves timestamps."""
        history = [
            {"role": "user", "content": "msg", "timestamp": 1234567890.123},
        ]
        from agent.react_agent import ReactAgent
        result = ReactAgent._normalize_history(history)
        self.assertEqual(1234567890.123, result[0]["timestamp"])

    def test_normalize_history_dict_list_input(self):
        """Test _normalize_history handles various input types."""
        from agent.react_agent import ReactAgent
        # None input
        self.assertEqual([], ReactAgent._normalize_history(None))
        # String input
        self.assertEqual([], ReactAgent._normalize_history("not a list"))


class ReactAgentParsingTests(unittest.TestCase):
    """Test ReactAgent parsing functions."""

    def test_build_runtime_context_message(self):
        """Test _build_runtime_context_message structure."""
        from agent.react_agent import ReactAgent
        tool_specs = {"test_tool": {"required": [], "optional": []}}
        result = ReactAgent._build_runtime_context_message(tool_specs)
        self.assertEqual("system", result["role"])
        self.assertIn("tool_specs", result["content"])

    def test_is_runtime_system_prompt_message_true(self):
        """Test _is_runtime_system_prompt_message recognizes runtime prompts."""
        from agent.react_agent import ReactAgent
        msg = {"role": "system", "content": '{"agent_runtime": {"tool_specs": {}}}'}
        self.assertTrue(ReactAgent._is_runtime_system_prompt_message(msg))

    def test_is_runtime_system_prompt_message_false(self):
        """Test _is_runtime_system_prompt_message rejects other system prompts."""
        from agent.react_agent import ReactAgent
        msg = {"role": "system", "content": "You are a helpful assistant"}
        self.assertFalse(ReactAgent._is_runtime_system_prompt_message(msg))

    def test_parse_tool_arguments_dict(self):
        """Test _parse_tool_arguments with dict input."""
        from agent.react_agent import ReactAgent
        args = {"key1": "value1", "key2": "value2"}
        result = ReactAgent._parse_tool_arguments(args)
        self.assertEqual(args, result)

    def test_parse_tool_arguments_json_string(self):
        """Test _parse_tool_arguments with JSON string."""
        from agent.react_agent import ReactAgent
        args = '{"key": "value"}'
        result = ReactAgent._parse_tool_arguments(args)
        self.assertEqual({"key": "value"}, result)

    def test_parse_tool_arguments_none(self):
        """Test _parse_tool_arguments with None."""
        from agent.react_agent import ReactAgent
        result = ReactAgent._parse_tool_arguments(None)
        self.assertEqual({}, result)

    def test_parse_tool_arguments_invalid_json(self):
        """Test _parse_tool_arguments with invalid JSON."""
        from agent.react_agent import ReactAgent
        result = ReactAgent._parse_tool_arguments("{not valid json")
        self.assertIsNone(result)

    def test_normalize_tool_call_with_function_dict(self):
        """Test _normalize_tool_call handles function parameter fallback."""
        from agent.react_agent import ReactAgent
        raw_call = {
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'}
        }
        result = ReactAgent._normalize_tool_call(raw_call, 0)
        self.assertEqual("test_tool", result["name"])
        self.assertEqual({"key": "value"}, result["arguments"])

    def test_normalize_tool_call_with_name_direct(self):
        """Test _normalize_tool_call with direct name field."""
        from agent.react_agent import ReactAgent
        raw_call = {"name": "test_tool", "arguments": {"key": "value"}}
        result = ReactAgent._normalize_tool_call(raw_call, 0)
        self.assertEqual("test_tool", result["name"])

    def test_normalize_tool_call_invalid_returns_none(self):
        """Test _normalize_tool_call returns None for invalid input."""
        from agent.react_agent import ReactAgent
        self.assertIsNone(ReactAgent._normalize_tool_call({}, 0))
        self.assertIsNone(ReactAgent._normalize_tool_call(None, 0))

    def test_yield_stream_end_extracts_timestamps(self):
        """Test _yield_stream_end extracts user timestamps."""
        from agent.react_agent import ReactAgent
        messages = [
            {"role": "user", "content": "msg1", "timestamp": 100.0},
            {"role": "user", "content": "msg2", "timestamp": 200.0},
            {"role": "system", "content": "sys"},
        ]
        result = ReactAgent._yield_stream_end(messages)
        self.assertEqual(200.0, result["data"]["last_user_ts"])
        self.assertEqual(100.0, result["data"]["earliest_retryable_ts"])

    def test_yield_stream_end_no_user_messages(self):
        """Test _yield_stream_end with no user messages."""
        from agent.react_agent import ReactAgent
        messages = [{"role": "system", "content": "sys"}]
        result = ReactAgent._yield_stream_end(messages)
        self.assertIsNone(result["data"]["last_user_ts"])
        self.assertIsNone(result["data"]["earliest_retryable_ts"])

    def test_yield_stream_end_status_parameter(self):
        """Test _yield_stream_end status parameter."""
        from agent.react_agent import ReactAgent
        result1 = ReactAgent._yield_stream_end([], status="complete")
        self.assertEqual("complete", result1["data"]["status"])
        result2 = ReactAgent._yield_stream_end([], status="error")
        self.assertEqual("error", result2["data"]["status"])
        result3 = ReactAgent._yield_stream_end([], status="max_steps")
        self.assertEqual("max_steps", result3["data"]["status"])


# ── ReactAgent run() Behavior Tests ────────────────────────────


class ReactAgentRunBehaviorTests(unittest.TestCase):
    """Test ReactAgent.run() high-level behavior."""

    def setUp(self):
        """Remove stream_chat attribute from Mock to force chat() fallback."""
        self.mock_llm = Mock()
        # Delete any auto-generated stream_chat attribute to ensure we use chat()
        if hasattr(self.mock_llm, 'stream_chat'):
            delattr(self.mock_llm, 'stream_chat')

    def test_run_max_steps_reached(self):
        """Test run() behavior when max_steps is reached."""
        from agent.react_agent import ReactAgent
        # Provide multiple responses for each step
        # Step 1: tool call
        # Step 2: after forced_final_retry prompt, another tool call (which triggers max_steps fallback)
        self.mock_llm.chat.side_effect = [
            {
                "content": "",
                "tool_calls": [{"id": "call_1", "name": "query_inventory", "arguments": {"cell": "K562"}}]
            },
            {
                "content": "",
                "tool_calls": [{"id": "call_2", "name": "query_inventory", "arguments": {"cell": "K562"}}]
            },
        ]
        mock_tools = Mock()
        mock_tools.list_tools.return_value = ["query_inventory"]
        mock_tools.run.return_value = {"ok": True, "result": {"count": 0}}
        mock_tools.tool_specs.return_value = {"query_inventory": {"required": [], "optional": []}}
        mock_tools.tool_schemas.return_value = []

        agent = ReactAgent(llm_client=self.mock_llm, tool_runner=mock_tools, max_steps=2)
        result = agent.run("test query")

        self.assertFalse(result["ok"])
        self.assertEqual(2, result["steps"])
        self.assertIn("Max steps reached", result["final"])

    def test_run_empty_response_retry(self):
        """Test run() handles empty LLM response."""
        from agent.react_agent import ReactAgent
        # First: empty response with tools (will trigger forced retry),
        # Second: direct answer after retry prompt
        self.mock_llm.chat.side_effect = [
            {"content": "", "tool_calls": [{"id": "call_1", "name": "query_inventory", "arguments": {}}]},
            {"content": "Direct answer", "tool_calls": []},
        ]

        mock_tools = Mock()
        mock_tools.list_tools.return_value = ["query_inventory"]
        mock_tools.run.return_value = {"ok": True, "result": {"count": 0}}
        mock_tools.tool_specs.return_value = {"query_inventory": {"required": [], "optional": []}}
        mock_tools.tool_schemas.return_value = []

        agent = ReactAgent(llm_client=self.mock_llm, tool_runner=mock_tools, max_steps=5)
        result = agent.run("test query")

        self.assertTrue(result["ok"])
        self.assertIn("Direct answer", result["final"])

    def test_run_with_parallel_tool_calls(self):
        """Test run() handles parallel tool calls."""
        from agent.react_agent import ReactAgent
        # Response with two tool calls, then a final answer
        self.mock_llm.chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "name": "query_inventory", "arguments": {"cell": "K562"}},
                    {"id": "call_2", "name": "generate_stats", "arguments": {}},
                ]
            },
            {
                "content": "Found 1 K562 record and stats ready.",
                "tool_calls": [],
            },
        ]

        call_count = [0]

        def mock_run(tool_name, tool_input, trace_id=None):
            _ = trace_id  # Not used in mock
            call_count[0] += 1
            return {"ok": True, "result": {"count": call_count[0]}}

        mock_tools = Mock()
        mock_tools.list_tools.return_value = ["query_inventory", "generate_stats"]
        mock_tools.run.side_effect = mock_run
        mock_tools.tool_specs.return_value = {
            "query_inventory": {"required": [], "optional": []},
            "generate_stats": {"required": [], "optional": []},
        }
        mock_tools.tool_schemas.return_value = []

        agent = ReactAgent(llm_client=self.mock_llm, tool_runner=mock_tools, max_steps=3)
        result = agent.run("test query")

        self.assertTrue(result["ok"])
        # Both tools should have been called
        self.assertEqual(2, call_count[0])

    def test_run_includes_trace_id(self):
        """Test run() includes trace_id in result."""
        from agent.react_agent import ReactAgent
        self.mock_llm.chat.return_value = {"content": "Answer", "tool_calls": []}

        mock_tools = Mock()
        mock_tools.list_tools.return_value = []
        mock_tools.tool_specs.return_value = {}
        mock_tools.tool_schemas.return_value = []

        agent = ReactAgent(llm_client=self.mock_llm, tool_runner=mock_tools, max_steps=1)
        result = agent.run("test")

        self.assertTrue("ok" in result)
        self.assertIn("trace-", result.get("trace_id", ""))


if __name__ == "__main__":
    unittest.main()
