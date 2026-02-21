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


class AgentToolRunnerTests(unittest.TestCase):
    def test_list_tools_contains_core_entries(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        names = set(runner.list_tools())
        self.assertIn("search_records", names)
        self.assertIn("add_entry", names)
        self.assertIn("record_takeout", names)
        self.assertIn("manage_boxes", names)
        self.assertIn("manage_staged", names)
        self.assertNotIn("recent_frozen", names)
        self.assertNotIn("collect_timeline", names)
        self.assertNotIn("list_staged", names)
        self.assertNotIn("remove_staged", names)
        self.assertNotIn("clear_staged", names)

    def test_manage_boxes_dry_run_dispatches_tool_api(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_box_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "manage_boxes",
                {"operation": "add", "count": 2, "dry_run": True},
            )
            self.assertTrue(response["ok"])
            self.assertTrue(response.get("dry_run"))
            self.assertEqual("add", response.get("preview", {}).get("operation"))


    def test_add_entry_requires_execute_mode(self):
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
                    "positions": "2,3",
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
            self.assertEqual("write_requires_execute_mode", response["error_code"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, len(current["inventory"]))

            rows = read_audit_events(str(yaml_path))
            last = rows[-1]
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("write_requires_execute_mode", (last.get("error") or {}).get("error_code"))

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
            response = runner.run("search_records", {"box": 2, "position": 15})

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

    def test_search_records_recent_filters_replace_recent_tool(self):
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
            response = runner.run("search_records", {"recent_count": 1})

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
            response = runner.run("query_takeout_events", {"view": "summary", "all_history": True})

            self.assertTrue(response["ok"])
            self.assertIn("summary", response["result"])

    def test_query_takeout_events_summary_rejects_event_filters(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("query_takeout_events", {"view": "summary", "action": "takeout"})

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

    def test_record_takeout_move_missing_target_returns_hint(self):
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
                    "position": 1,
                    "date": "2026-02-10",
                    "action": "move",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("to_position", response.get("message", ""))

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

    def test_tool_specs_expose_required_fields(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("add_entry", specs)
        self.assertIn("required", specs["add_entry"])
        self.assertIn("positions", specs["add_entry"]["required"])

        self.assertIn("search_records", specs)
        self.assertEqual([], specs["search_records"].get("required"))
        self.assertIn("box", specs["search_records"].get("optional", []))
        self.assertIn("position", specs["search_records"].get("optional", []))
        search_params = specs["search_records"].get("params", {})
        self.assertIn("mode", search_params)
        self.assertIn("record_id", search_params)
        self.assertIn("active_only", search_params)
        self.assertIn("recent_days", search_params)
        self.assertIn("recent_count", search_params)
        self.assertEqual(
            ["fuzzy", "exact", "keywords"],
            search_params["mode"].get("enum"),
        )

        self.assertNotIn("recent_frozen", specs)
        self.assertNotIn("collect_timeline", specs)
        self.assertNotIn("list_staged", specs)
        self.assertNotIn("remove_staged", specs)
        self.assertNotIn("clear_staged", specs)
        self.assertIn("manage_staged", specs)
        self.assertIn("operation", specs["manage_staged"].get("required", []))

        self.assertIn("record_takeout", specs)
        self.assertIn("to_position", specs["record_takeout"].get("optional", []))

        schemas = runner.tool_schemas()
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
        mode_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("mode", {})
        )
        self.assertEqual(["fuzzy", "exact", "keywords"], mode_schema.get("enum"))

    def test_rollback_tool_spec_mentions_question_workflow(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        rollback_spec = runner.tool_specs().get("rollback", {})

        description = str(rollback_spec.get("description") or "").lower()
        notes = str(rollback_spec.get("notes") or "").lower()

        self.assertIn("backup_path", description)
        self.assertIn("explicit", notes)

    def test_manage_staged_list_remove_clear(self):
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

        list_resp = runner.run("manage_staged", {"operation": "list"})
        self.assertTrue(list_resp["ok"])
        self.assertEqual(2, list_resp["result"]["count"])

        remove_resp = runner.run("manage_staged", {"operation": "remove", "index": 0})
        self.assertTrue(remove_resp["ok"])
        self.assertEqual(1, remove_resp["result"]["removed"])

        clear_resp = runner.run("manage_staged", {"operation": "clear"})
        self.assertTrue(clear_resp["ok"])
        self.assertEqual(1, clear_resp["result"]["cleared_count"])

    def test_manage_staged_remove_requires_selector(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("manage_staged", {"operation": "remove"})

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
        for name in ("recent_frozen", "collect_timeline", "list_staged", "remove_staged", "clear_staged"):
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

    def test_edit_entry_in_tool_specs(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("edit_entry", specs)

    # --- cell_line alias tests ---


if __name__ == "__main__":
    unittest.main()

