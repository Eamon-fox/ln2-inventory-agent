import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from lib.yaml_ops import load_yaml, read_audit_events, write_yaml


def _collect_agent_tool_runner_i18n_keys():
    source = (ROOT / "agent" / "tool_runner.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    keys = set()

    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_msg"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)

    for node in module.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_TOOL_CONTRACTS" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            continue

        for name_node, contract_node in zip(node.value.keys, node.value.values):
            if not (
                isinstance(name_node, ast.Constant)
                and isinstance(name_node.value, str)
                and isinstance(contract_node, ast.Dict)
            ):
                continue

            tool_name = name_node.value
            has_description = False
            has_notes = False
            for key_node, _value_node in zip(contract_node.keys, contract_node.values):
                if isinstance(key_node, ast.Constant) and key_node.value == "description":
                    has_description = True
                if isinstance(key_node, ast.Constant) and key_node.value == "notes":
                    has_notes = True

            if has_description:
                keys.add(f"toolContracts.{tool_name}.description")
            if has_notes:
                keys.add(f"toolContracts.{tool_name}.notes")
        break

    return keys


def _flatten_leaf_keys(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix} if prefix else set()

    flattened = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened |= _flatten_leaf_keys(value, path)
        else:
            flattened.add(path)
    return flattened


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
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def make_data_alphanumeric(records):
    data = make_data(records)
    data["meta"]["box_layout"]["indexing"] = "alphanumeric"
    return data


class AgentToolRunnerTests(unittest.TestCase):
    def test_list_tools_contains_core_entries(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        names = set(runner.list_tools())
        self.assertIn("search_records", names)
        self.assertIn("recent_frozen", names)
        self.assertIn("query_takeout_summary", names)
        self.assertIn("add_entry", names)
        self.assertIn("record_takeout", names)
        self.assertIn("manage_boxes_add", names)
        self.assertIn("manage_boxes_remove", names)
        self.assertIn("staged_list", names)
        self.assertIn("staged_remove", names)
        self.assertIn("staged_clear", names)
        self.assertNotIn("manage_boxes", names)
        self.assertNotIn("manage_staged", names)
        self.assertNotIn("collect_timeline", names)
        self.assertNotIn("list_staged", names)
        self.assertNotIn("remove_staged", names)
        self.assertNotIn("clear_staged", names)

    def test_manage_boxes_ignores_dry_run_input(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_box_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "manage_boxes_add",
                {"count": 2, "dry_run": True},
            )
            self.assertTrue(response["ok"])
            self.assertTrue(response.get("waiting_for_user_confirmation"))
            self.assertEqual("add", response.get("request", {}).get("operation"))


    def test_add_entry_rejects_undeclared_fields_via_schema_validation(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                session_id="session-agent-test",
            )
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": [2, 3],
                    "frozen_at": "2026-02-10",
                    "fields": {
                        "cell_line": "K562",
                        "short_name": "clone-2",
                        "note": "via runner",
                    },
                },
                trace_id="trace-agent-test",
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("short_name", str(response.get("message") or ""))

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, len(current["inventory"]))

    def test_add_entry_staging_supports_alphanumeric_positions(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=PlanStore(),
            )
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": ["A5"],
                    "frozen_at": "2026-02-10",
                    "fields": {
                        "cell_line": "K562",
                    },
                },
            )

            self.assertTrue(response["ok"])
            self.assertTrue(response.get("staged"))

    def test_record_takeout_requires_integer_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_bad_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("record_takeout", {"position": 1, "date": "2026-02-10"})
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertTrue(response.get("_hint"))
            self.assertIn("Required", response.get("_hint", ""))

    def test_unknown_tool_returns_hint(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("nonexistent_tool", {})

        self.assertFalse(response["ok"])
        self.assertEqual("unknown_tool", response["error_code"])
        self.assertTrue(response.get("_hint"))
        self.assertIn("available tools", response.get("_hint", "").lower())

    def test_search_records_rejects_keyword_mode_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "position": 10,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "K562", "mode": "keyword"})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_search_records_rejects_invalid_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_mode_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 3,
                        "parent_cell_line": "NCCIT",
                        "short_name": "nccit-abc",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "NCCIT", "mode": "bad-mode"})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_search_records_requires_non_empty_query(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("search_records", {})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])
        self.assertEqual("未输入检索词", response.get("message"))

    def test_search_records_supports_structured_slot_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_slot_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "position": 15,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "k562", "box": 2, "position": 15})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])

    def test_search_records_supports_alphanumeric_slot_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_slot_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric(
                    [
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 2,
                            "position": 15,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "k562", "box": 2, "position": "B6"})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])

    def test_search_records_supports_location_shortcut_query(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_shortcut_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 3,
                        "parent_cell_line": "NCCIT",
                        "short_name": "nccit-a",
                        "box": 2,
                        "position": 15,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "2:15"})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(3, response["result"]["records"][0]["id"])
            self.assertEqual("2:15", response["result"]["applied_filters"]["query_shortcut"])

    def test_search_records_default_excludes_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_active_default_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "active",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [1]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "K562"})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual([1], [item.get("id") for item in response["result"]["records"]])
            self.assertTrue(response["result"]["applied_filters"]["active_only"])

    def test_generate_stats_supports_optional_box_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_stats_box_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [1],
                                }
                            ],
                        },
                        make_record(3, box=2, position=1),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("generate_stats", {"box": 1})

            self.assertTrue(response["ok"])
            result = response.get("result") or {}
            self.assertEqual(1, result.get("box"))
            self.assertEqual(1, result.get("box_record_count"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1], ids)

    def test_generate_stats_include_inactive_adds_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_stats_box_inactive_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [1]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("generate_stats", {"box": 1, "include_inactive": True})

            self.assertTrue(response["ok"])
            result = response.get("result") or {}
            self.assertEqual(2, result.get("box_record_count"))
            self.assertTrue(result.get("include_inactive"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2], ids)

    def test_recent_frozen_replaces_recent_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_recent_search_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "old",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2025-01-01",
                    },
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "new",
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("recent_frozen", {"basis": "count", "value": 1})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["count"])
            self.assertEqual("new", response["result"]["records"][0]["short_name"])

    def test_search_records_rejects_mixed_recent_and_query_filters(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("search_records", {"query": "K562", "recent_count": 1})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])

    def test_query_takeout_events_summary_mode_replaces_collect_timeline(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_timeline_summary_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "A",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("query_takeout_summary", {"range": "all"})

            self.assertTrue(response["ok"])
            self.assertIn("summary", response["result"])

    def test_query_takeout_events_summary_rejects_event_filters(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("query_takeout_summary", {"range": "all", "action": "takeout"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])

    def test_add_entry_rejects_alias_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "add_entry",
                {
                    "cell_line": "K562",
                    "short": "alias-test",
                    "box_num": 1,
                    "position": 2,
                    "date": "2026-02-10",
                    "notes": "alias payload",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

            current = load_yaml(str(yaml_path))
            records = current.get("inventory", [])
            self.assertEqual(1, len(records))

    def test_record_takeout_rejects_id_and_pos_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_thaw_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_takeout",
                {
                    "id": 1,
                    "pos": 1,
                    "thaw_date": "2026-02-10",
                    "action": "takeout",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_record_takeout_move_rejects_target_position_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_takeout",
                {
                    "id": 1,
                    "pos": 1,
                    "to_pos": 2,
                    "thaw_date": "2026-02-10",
                    "action": "move",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

    def test_record_takeout_missing_source_returns_hint(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_hint_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_takeout",
                {
                    "record_id": 1,
                    "date": "2026-02-10",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_box", response.get("message", ""))

    def test_plan_preflight_hint_guides_record_repair_flow(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        payload = {
            "error_code": "plan_preflight_failed",
            "message": "Write blocked: integrity validation failed\n- Record #16 (id=16): invalid cell_line",
            "blocked_items": [
                {
                    "action": "takeout",
                    "record_id": 21,
                    "message": "Write blocked: integrity validation failed\n- Record #16 (id=16): invalid cell_line",
                }
            ],
        }

        hint = runner._hint_for_error("record_takeout", payload)
        self.assertIn("get_raw_entries", hint)
        self.assertIn("edit_entry", hint)
        self.assertIn("16", hint)

    def test_tool_schemas_expose_required_fields(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        schemas = runner.tool_schemas()
        names = [item.get("function", {}).get("name") for item in schemas]

        self.assertIn("add_entry", names)
        add_entry_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "add_entry"),
            None,
        )
        if not isinstance(add_entry_schema, dict):
            self.fail("add_entry schema should exist")
        add_entry_params = add_entry_schema.get("function", {}).get("parameters", {})
        self.assertIn("positions", add_entry_params.get("required", []))
        self.assertIn("fields", add_entry_params.get("required", []))
        add_entry_positions = (add_entry_params.get("properties") or {}).get("positions", {})
        self.assertEqual("array", add_entry_positions.get("type"))
        self.assertEqual("integer", (add_entry_positions.get("items") or {}).get("type"))
        add_entry_fields = (add_entry_params.get("properties") or {}).get("fields", {})
        self.assertEqual("object", add_entry_fields.get("type"))
        self.assertEqual(False, add_entry_fields.get("additionalProperties"))
        self.assertIn("cell_line", (add_entry_fields.get("properties") or {}))
        self.assertIn("note", (add_entry_fields.get("properties") or {}))
        self.assertIn("cell_line", add_entry_fields.get("required", []))
        self.assertNotIn("dry_run", (add_entry_params.get("properties") or {}))

        search_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "search_records"
            ),
            None,
        )
        if not isinstance(search_schema, dict):
            self.fail("search_records schema should exist")
        search_params = search_schema.get("function", {}).get("parameters", {})
        self.assertEqual(["query"], search_params.get("required", []))
        self.assertIn("box", (search_params.get("properties") or {}))
        self.assertIn("position", (search_params.get("properties") or {}))
        mode_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("mode", {})
        )
        self.assertEqual(["fuzzy", "exact", "keywords"], mode_schema.get("enum"))
        record_takeout_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "record_takeout"
            ),
            None,
        )
        if not isinstance(record_takeout_schema, dict):
            self.fail("record_takeout schema should exist")
        record_takeout_properties = (
            record_takeout_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )
        record_takeout_required = (
            record_takeout_schema.get("function", {})
            .get("parameters", {})
            .get("required", [])
        )
        self.assertIn("from_box", record_takeout_required)
        self.assertIn("from_position", record_takeout_required)
        self.assertIn("date", record_takeout_required)
        self.assertNotIn("dry_run", record_takeout_properties)

        self.assertIn("recent_frozen", names)
        self.assertIn("query_takeout_summary", names)
        self.assertNotIn("collect_timeline", names)
        self.assertNotIn("list_staged", names)
        self.assertNotIn("remove_staged", names)
        self.assertNotIn("clear_staged", names)
        self.assertIn("staged_list", names)
        self.assertIn("staged_remove", names)
        self.assertIn("staged_clear", names)

        staged_remove_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "staged_remove"),
            None,
        )
        if not isinstance(staged_remove_schema, dict):
            self.fail("staged_remove schema should exist")
        self.assertIn(
            "index",
            staged_remove_schema.get("function", {}).get("parameters", {}).get("required", []),
        )

        generate_stats_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "generate_stats"),
            None,
        )
        if not isinstance(generate_stats_schema, dict):
            self.fail("generate_stats schema should exist")
        self.assertIn(
            "box",
            generate_stats_schema.get("function", {}).get("parameters", {}).get("properties", {}),
        )
        self.assertIn(
            "include_inactive",
            generate_stats_schema.get("function", {}).get("parameters", {}).get("properties", {}),
        )

        for tool_name in [
            "record_move",
            "batch_takeout",
            "batch_move",
            "manage_boxes_add",
            "manage_boxes_remove",
        ]:
            schema_item = next(
                (item for item in schemas if item.get("function", {}).get("name") == tool_name),
                None,
            )
            if not isinstance(schema_item, dict):
                self.fail(f"{tool_name} schema should exist")
            self.assertNotIn(
                "dry_run",
                schema_item.get("function", {}).get("parameters", {}).get("properties", {}),
            )

    def test_tool_schemas_positions_follow_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_schema_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            schemas = runner.tool_schemas()

            def _schema(name):
                return next(
                    (item for item in schemas if item.get("function", {}).get("name") == name),
                    None,
                )

            add_entry_schema = _schema("add_entry")
            if not isinstance(add_entry_schema, dict):
                self.fail("add_entry schema should exist")
            add_positions = (
                add_entry_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("positions", {})
            )
            self.assertEqual("array", add_positions.get("type"))
            self.assertEqual("string", (add_positions.get("items") or {}).get("type"))

            search_schema = _schema("search_records")
            if not isinstance(search_schema, dict):
                self.fail("search_records schema should exist")
            search_position = (
                search_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("position", {})
            )
            self.assertEqual("string", search_position.get("type"))

            takeout_schema = _schema("record_takeout")
            if not isinstance(takeout_schema, dict):
                self.fail("record_takeout schema should exist")
            from_position = (
                takeout_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("from_position", {})
            )
            self.assertEqual("string", from_position.get("type"))

    def test_tool_schemas_include_dynamic_custom_fields_for_add_and_edit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_schema_custom_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            seeded_record = make_record(1, box=1, position=1)
            seeded_record["passage_number"] = 1
            custom_data = make_data([seeded_record])
            custom_data.setdefault("meta", {}).update(
                {
                    "cell_line_required": False,
                    "custom_fields": [
                        {"key": "passage_number", "label": "Passage", "type": "int", "required": True},
                        {"key": "source_batch", "label": "Source Batch", "type": "str", "required": False},
                    ],
                }
            )
            write_yaml(
                custom_data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            schemas = runner.tool_schemas()

            add_schema = next(
                (item for item in schemas if item.get("function", {}).get("name") == "add_entry"),
                None,
            )
            if not isinstance(add_schema, dict):
                self.fail("add_entry schema should exist")
            add_fields = (
                add_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("fields", {})
            )
            add_field_props = add_fields.get("properties", {})
            self.assertIn("passage_number", add_field_props)
            self.assertEqual("integer", add_field_props["passage_number"].get("type"))
            self.assertIn("source_batch", add_field_props)
            self.assertEqual("string", add_field_props["source_batch"].get("type"))
            self.assertIn("passage_number", add_fields.get("required", []))
            self.assertNotIn("cell_line", add_fields.get("required", []))
            self.assertIn(
                "fields",
                add_schema.get("function", {}).get("parameters", {}).get("required", []),
            )

            edit_schema = next(
                (item for item in schemas if item.get("function", {}).get("name") == "edit_entry"),
                None,
            )
            if not isinstance(edit_schema, dict):
                self.fail("edit_entry schema should exist")
            edit_fields = (
                edit_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("fields", {})
            )
            edit_field_props = edit_fields.get("properties", {})
            self.assertIn("frozen_at", edit_field_props)
            self.assertIn("passage_number", edit_field_props)
            self.assertEqual("integer", edit_field_props["passage_number"].get("type"))
            self.assertEqual("object", edit_fields.get("type"))
            self.assertEqual(1, edit_fields.get("minProperties"))
            self.assertEqual(False, edit_fields.get("additionalProperties"))

    def test_add_entry_rejects_positions_string_payload(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_schema_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": "2,3",
                    "frozen_at": "2026-02-10",
                    "fields": {"cell_line": "K562"},
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("positions", str(response.get("message") or ""))

    def test_record_takeout_rejects_string_position_in_numeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_takeout_numeric_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_takeout",
                {
                    "record_id": 1,
                    "from_box": 1,
                    "from_position": "1",
                    "date": "2026-02-10",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_position", str(response.get("message") or ""))

    def test_record_takeout_rejects_integer_position_in_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_takeout_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_takeout",
                {
                    "record_id": 1,
                    "from_box": 1,
                    "from_position": 5,
                    "date": "2026-02-10",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_position", str(response.get("message") or ""))

    def test_rollback_tool_schema_mentions_explicit_backup_path(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        rollback_schema = next(
            (
                item
                for item in runner.tool_schemas()
                if item.get("function", {}).get("name") == "rollback"
            ),
            None,
        )
        if not isinstance(rollback_schema, dict):
            self.fail("rollback schema should exist")
        description = str(rollback_schema.get("function", {}).get("description") or "").lower()

        self.assertIn("backup_path", description)
        self.assertIn("explicit", description)

    def test_staged_tools_list_remove_clear(self):
        from lib.plan_store import PlanStore

        store = PlanStore()
        store.add([
            {
                "action": "takeout",
                "record_id": 1,
                "box": 1,
                "position": 5,
                "source": "ai",
            },
            {
                "action": "move",
                "record_id": 2,
                "box": 1,
                "position": 6,
                "to_position": 7,
                "source": "ai",
            },
        ])
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=store)

        list_resp = runner.run("staged_list", {})
        self.assertTrue(list_resp["ok"])
        self.assertEqual(2, list_resp["result"]["count"])

        remove_resp = runner.run("staged_remove", {"index": 0})
        self.assertTrue(remove_resp["ok"])
        self.assertEqual(1, remove_resp["result"]["removed"])

        clear_resp = runner.run("staged_clear", {})
        self.assertTrue(clear_resp["ok"])
        self.assertEqual(1, clear_resp["result"]["cleared_count"])

    def test_staged_remove_requires_index(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("staged_remove", {})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])


    def test_agent_tool_runner_i18n_keys_covered_in_en_and_zh(self):
        required_keys = _collect_agent_tool_runner_i18n_keys()
        i18n_dir = ROOT / "app_gui" / "i18n" / "translations"

        for locale in ("en.json", "zh-CN.json"):
            data = json.loads((i18n_dir / locale).read_text(encoding="utf-8"))
            available = _flatten_leaf_keys(data.get("agentToolRunner", {}))
            missing = sorted(required_keys - available)
            self.assertEqual(
                [],
                missing,
                f"{locale} missing agentToolRunner keys: {missing}",
            )

    def test_removed_tools_are_unknown(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        for name in ("collect_timeline", "manage_boxes", "manage_staged", "list_staged", "remove_staged", "clear_staged"):
            response = runner.run(name, {})
            self.assertFalse(response["ok"])
            self.assertEqual("unknown_tool", response["error_code"])


class EditEntryToolRunnerTests(unittest.TestCase):
    """Integration tests for edit_entry through AgentToolRunner."""

    def test_edit_entry_stages_plan_item(self):
        """edit_entry should produce a plan item with real position from record."""
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=2, position=15)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore
            store = PlanStore()
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=store,
            )

            response = runner.run(
                "edit_entry",
                {"record_id": 1, "fields": {"cell_line": "HeLa"}},
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, store.count())
            item = store.list_items()[0]
            self.assertEqual("edit", item["action"])
            self.assertEqual(1, item["record_id"])
            self.assertEqual(2, item["box"])
            self.assertEqual(15, item["position"])
            self.assertEqual("ai", item["source"])
            self.assertEqual({"cell_line": "HeLa"}, item["payload"]["fields"])

    def test_edit_entry_missing_record_id(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"fields": {"note": "x"}})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_missing_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"record_id": 1})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_empty_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"record_id": 1, "fields": {}})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_listed_in_tools(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        self.assertIn("edit_entry", set(runner.list_tools()))

    def test_edit_entry_in_tool_schemas(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        schemas = runner.tool_schemas()
        names = [item.get("function", {}).get("name") for item in schemas]
        self.assertIn("edit_entry", names)

    # --- cell_line alias tests ---


if __name__ == "__main__":
    unittest.main()

