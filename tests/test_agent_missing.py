"""Missing unit tests for agent/ layer modules.

Tests for:
- tool_runner.py: plan staging, normalization, hints
- react_agent.py: history, parsing, step limits
- llm_client.py: client behavior
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from agent.llm_client import DeepSeekLLMClient
from lib.tool_api_write_validation import resolve_request_backup_path
from lib.yaml_ops import create_yaml_backup, write_yaml


def make_record(rec_id=1, box=1, position=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records,
    }


# --- tool_runner.py Tests ---


class ToolRunnerNormalizationTests(unittest.TestCase):
    """Test normalization functions in AgentToolRunner."""

    def test_required_int_accepts_integer(self):
        """Test _required_int accepts strict integers."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"count": 3}
        self.assertEqual(3, runner._required_int(payload, "count"))

    def test_required_int_rejects_string(self):
        """Test _required_int rejects string values in strict mode."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"count": "3"}
        with self.assertRaises(ValueError):
            runner._required_int(payload, "count")

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
        """Test _normalize_positions rejects scalar int (array-only)."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        with self.assertRaises(ValueError):
            runner._normalize_positions(5)

    def test_normalize_positions_string(self):
        """Test _normalize_positions rejects comma string (array-only)."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        with self.assertRaises(ValueError):
            runner._normalize_positions("1,2,3")

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

    def _seed_yaml_alphanumeric(self, records):
        """Create a temporary YAML file with alphanumeric slot indexing."""
        tmpdir = tempfile.TemporaryDirectory(prefix="tool_runner_stage_alpha_")
        self.addCleanup(tmpdir.cleanup)
        yaml_path = Path(tmpdir.name) / "inventory.yaml"
        data = make_data(records)
        data["meta"]["box_layout"]["indexing"] = "alphanumeric"
        write_yaml(
            data,
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
                "fields": {"cell_line": "K562", "note": "clone-new"},
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

    def test_stage_to_plan_takeout(self):
        """Test staging takeout operation."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": 5,
                    }
                ],
                "date": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("takeout", self.plan_store.list_items()[0]["action"])
        self.assertEqual(5, self.plan_store.list_items()[0]["position"])

    def test_stage_to_plan_takeout_accepts_alphanumeric_position(self):
        """Position parsing should accept display values like A5 in alphanumeric layout."""
        yaml_path = self._seed_yaml_alphanumeric([make_record(rec_id=1, box=1, position=5)])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": "A5",
                    }
                ],
                "date": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual(5, self.plan_store.list_items()[0]["position"])

    def test_stage_to_plan_takeout_rejects_numeric_text_in_alphanumeric_layout(self):
        """In alphanumeric mode, numeric text should be rejected (use A1-style input)."""
        yaml_path = self._seed_yaml_alphanumeric([make_record(rec_id=1, box=1, position=5)])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": "5",
                    }
                ],
                "date": "2026-02-10",
            },
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tool_input", result.get("error_code"))
        self.assertEqual(0, len(self.plan_store.list_items()))

    def test_stage_to_plan_takeout_rejects_legacy_action_alias(self):
        """Legacy alias 瑙ｅ喕 should be rejected by strict schema."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": 5,
                    }
                ],
                "date": "2026-02-10",
                "action": "瑙ｅ喕",
            },
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tool_input", result["error_code"])
        self.assertEqual(0, len(self.plan_store.list_items()))

    def test_stage_to_plan_move(self):
        """Test staging move operation."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "move",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": 5,
                        "to_box": 1,
                        "to_position": 10,
                    }
                ],
                "date": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("move", self.plan_store.list_items()[0]["action"])
        self.assertEqual(10, self.plan_store.list_items()[0]["to_position"])

    def test_stage_to_plan_takeout_multiple_entries(self):
        """Test staging takeout operation with multiple entries."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {"record_id": 1, "from_box": 1, "from_position": 5},
                    {"record_id": 2, "from_box": 1, "from_position": 10},
                ],
                "date": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(2, len(self.plan_store.list_items()))

    def test_stage_to_plan_move_multiple_entries(self):
        """Test staging move operation with multiple entries."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "move",
            {
                "entries": [
                    {
                        "record_id": 1,
                        "from_box": 1,
                        "from_position": 5,
                        "to_box": 1,
                        "to_position": 10,
                    }
                ],
                "date": "2026-02-10",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))
        self.assertEqual("move", self.plan_store.list_items()[0]["action"])
        self.assertEqual(10, self.plan_store.list_items()[0]["to_position"])

    def test_stage_to_plan_validation_failure(self):
        """Strict input schema should reject invalid box before staging."""
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
        self.assertEqual("invalid_tool_input", result["error_code"])
        self.assertEqual(0, len(self.plan_store.list_items()))

    def test_stage_to_plan_preflight_blocked_returns_tool_error(self):
        """Invalid staged write should be rejected before entering plan."""
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, position=5)])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {
                        "record_id": 999,
                        "from_box": 1,
                        "from_position": 5,
                    }
                ],
                "date": "2026-02-10",
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
            make_record(rec_id=1, box=1, position=5),
            make_record(rec_id=2, box=1, position=10),
        ]
        yaml_path = self._seed_yaml(records)
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {"record_id": 1, "from_box": 1, "from_position": 5},
                    {"record_id": 999, "from_box": 1, "from_position": 5},
                ],
                "date": "2026-02-10",
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
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, position=5)])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "takeout",
            {
                "entries": [
                    {"record_id": 1, "from_box": 1, "from_position": 5},
                    {"record_id": 2},  # Missing from_box/from_position -> schema invalid
                ],
                "date": "2026-02-10",
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tool_input", result["error_code"])
        self.assertEqual(0, len(self.plan_store.list_items()))

    def test_stage_to_plan_validates_existing_plus_incoming_as_one_batch(self):
        """Second staged add must be rejected if it conflicts with existing staged items."""
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, position=1)])
        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)

        first = runner._stage_to_plan(
            "add_entry",
            {
                "fields": {"cell_line": "K562"},
                "box": 1,
                "positions": [2],
                "frozen_at": "2026-02-10",
            },
        )
        self.assertTrue(first["ok"])
        self.assertEqual(1, len(self.plan_store.list_items()))

        second = runner._stage_to_plan(
            "add_entry",
            {
                "fields": {"cell_line": "K562"},
                "box": 1,
                "positions": [2],
                "frozen_at": "2026-02-10",
            },
        )

        self.assertFalse(second["ok"])
        self.assertEqual("plan_preflight_failed", second["error_code"])
        self.assertEqual(1, len(self.plan_store.list_items()))

    def test_stage_to_plan_rollback_requires_explicit_backup_path(self):
        yaml_path = self._seed_yaml([make_record(rec_id=1, box=1, position=5)])
        backup_path = resolve_request_backup_path(
            yaml_path=yaml_path,
            execution_mode="execute",
            dry_run=False,
            request_backup_path=None,
            backup_event_source="tests.stage.rollback",
        )
        self.assertTrue(os.path.exists(str(backup_path)))

        runner = AgentToolRunner(yaml_path=yaml_path, plan_store=self.plan_store)
        result = runner._stage_to_plan("rollback", {"backup_path": str(backup_path)})

        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))
        staged = self.plan_store.list_items()[0]
        self.assertEqual("rollback", staged.get("action"))
        self.assertEqual(str(backup_path), (staged.get("payload") or {}).get("backup_path"))

    def test_stage_to_plan_allows_valid_write_when_baseline_cell_line_is_dirty(self):
        """Historical cell_line mismatch should not block staging of valid incoming writes."""
        tmpdir = tempfile.TemporaryDirectory(prefix="tool_runner_stage_badbase_")
        self.addCleanup(tmpdir.cleanup)
        yaml_path = Path(tmpdir.name) / "inventory.yaml"
        bad_data = {
            "meta": {
                "box_layout": {"rows": 9, "cols": 9},
                "cell_line_required": True,
                "cell_line_options": ["K562", "HeLa"],
            },
            "inventory": [
                {
                    "id": 1,
                    "cell_line": "U2OS",
                    "short_name": "bad",
                    "box": 1,
                    "position": 5,
                    "frozen_at": "2025-01-01",
                }
            ],
        }
        yaml_path.write_text(
            yaml.safe_dump(bad_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        runner = AgentToolRunner(yaml_path=str(yaml_path), plan_store=self.plan_store)
        result = runner._stage_to_plan(
            "add_entry",
            {
                "fields": {"cell_line": "K562"},
                "box": 1,
                "positions": [6],
                "frozen_at": "2026-02-10",
            },
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.plan_store.list_items()))


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
        hint = runner._hint_for_error("takeout", payload)
        self.assertIn("search_records", hint)

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
        hint = runner._hint_for_error("takeout", payload)
        self.assertIn("to_position", hint)

    def test_hint_for_error_no_backups(self):
        """Test hint for no_backups."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "no_backups"}
        hint = runner._hint_for_error("rollback", payload)
        self.assertIn("backup_path", hint)

    def test_hint_for_error_missing_backup_path(self):
        """Test hint for missing_backup_path."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "missing_backup_path"}
        hint = runner._hint_for_error("rollback", payload)
        self.assertIn("list_audit_timeline", hint)

    def test_hint_for_error_backup_not_in_timeline(self):
        """Test hint for backup_not_in_timeline."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "backup_not_in_timeline"}
        hint = runner._hint_for_error("rollback", payload)
        self.assertIn("action=backup", hint)

    def test_hint_for_error_missing_audit_seq(self):
        """Test hint for missing_audit_seq."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "missing_audit_seq"}
        hint = runner._hint_for_error("rollback", payload)
        self.assertIn("audit_seq", hint)

    def test_hint_for_error_invalid_box(self):
        """Test hint for invalid_box."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "invalid_box"}
        hint = runner._hint_for_error("add_entry", payload)
        self.assertIn("valid", hint.lower())
        self.assertIn("A1", hint)

    def test_hint_for_error_plan_preflight_failed(self):
        """Test hint for plan_preflight_failed."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {"error_code": "plan_preflight_failed"}
        hint = runner._hint_for_error("takeout", payload)
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
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(RuntimeError):
            DeepSeekLLMClient()


# --- react_agent.py Tests (Unit Tests) ---


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


# --- ReactAgent run() Behavior Tests ---


class ReactAgentRunBehaviorTests(unittest.TestCase):
    """Test ReactAgent.run() high-level behavior."""

    def setUp(self):
        """Remove stream_chat attribute from Mock to force chat() fallback."""
        self.mock_llm = Mock()
        # Delete any auto-generated stream_chat attribute to ensure we use chat()
        if hasattr(self.mock_llm, 'stream_chat'):
            delattr(self.mock_llm, 'stream_chat')


    def test_run_includes_trace_id(self):
        """Test run() includes trace_id in result."""
        from agent.react_agent import ReactAgent
        self.mock_llm.chat.return_value = {"content": "Answer", "tool_calls": []}

        mock_tools = Mock()
        mock_tools.list_tools.return_value = []
        mock_tools.tool_schemas.return_value = []

        agent = ReactAgent(llm_client=self.mock_llm, tool_runner=mock_tools, max_steps=1)
        result = agent.run("test")

        self.assertTrue("ok" in result)
        self.assertIn("trace-", result.get("trace_id", ""))


if __name__ == "__main__":
    unittest.main()

