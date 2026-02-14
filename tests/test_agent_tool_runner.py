import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from lib.yaml_ops import load_yaml, write_yaml


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


class AgentToolRunnerTests(unittest.TestCase):
    def test_list_tools_contains_core_entries(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        names = set(runner.list_tools())
        self.assertIn("query_inventory", names)
        self.assertIn("add_entry", names)
        self.assertIn("record_thaw", names)
        self.assertIn("manage_boxes", names)

    def test_manage_boxes_returns_confirmation_marker(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        response = runner.run("manage_boxes", {"operation": "add", "count": 1})
        self.assertTrue(response["ok"])
        self.assertTrue(response.get("waiting_for_user_confirmation"))
        self.assertEqual("add", response.get("request", {}).get("operation"))

    def test_manage_boxes_not_staged_when_plan_store_enabled(self):
        from lib.plan_store import PlanStore

        store = PlanStore()
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml", plan_store=store)
        response = runner.run("manage_boxes", {"operation": "add", "count": 1})
        self.assertTrue(response["ok"])
        self.assertTrue(response.get("waiting_for_user_confirmation"))
        self.assertEqual(0, store.count())

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

    def test_query_inventory_dispatch(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    {
                        "id": 2,
                        "cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "positions": [10],
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("query_inventory", {"cell": "K562", "box": 2})
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])

    def test_query_inventory_ignores_unknown_kwargs(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_query_unknown_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 2,
                            "cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 2,
                            "positions": [10],
                            "frozen_at": "2026-02-10",
                        }
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "query_inventory",
                {
                    "cell": "K562",
                    "limit": 3,
                    "offset": 0,
                    "unused": "value",
                },
            )
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])

    def test_add_entry_writes_agent_audit_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
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
                    "parent_cell_line": "K562",
                    "short_name": "clone-2",
                    "box": 1,
                    "positions": "2,3",
                    "frozen_at": "2026-02-10",
                    "note": "via runner",
                },
                trace_id="trace-agent-test",
            )
            self.assertTrue(response["ok"])

            current = load_yaml(str(yaml_path))
            # Tube-level model: positions "2,3" creates 2 new tube records.
            self.assertEqual(3, len(current["inventory"]))

            audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
            rows = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last = rows[-1]
            self.assertEqual("agent", last["actor_type"])
            self.assertEqual("agent", last["channel"])
            self.assertEqual("agent", last["actor_id"])
            self.assertEqual("session-agent-test", last["session_id"])
            self.assertEqual("trace-agent-test", last["trace_id"])

    def test_record_thaw_requires_integer_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_bad_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("record_thaw", {"position": 1, "date": "2026-02-10"})
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

    def test_search_records_normalizes_keyword_mode_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "positions": [10],
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "K562", "mode": "keyword"})

            self.assertTrue(response["ok"])
            self.assertEqual("keywords", response["result"]["mode"])
            self.assertEqual(1, response["result"]["total_count"])

    def test_search_records_falls_back_to_fuzzy_for_invalid_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_mode_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 3,
                        "parent_cell_line": "NCCIT",
                        "short_name": "nccit-abc",
                        "box": 1,
                        "positions": [1],
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "NCCIT", "mode": "bad-mode"})

            self.assertTrue(response["ok"])
            self.assertEqual("fuzzy", response["result"]["mode"])
            self.assertEqual(1, response["result"]["total_count"])

    def test_add_entry_supports_common_alias_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
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
            self.assertTrue(response["ok"])

            current = load_yaml(str(yaml_path))
            records = current.get("inventory", [])
            self.assertEqual(2, len(records))
            self.assertEqual("K562", records[-1]["cell_line"])
            self.assertEqual([2], records[-1]["positions"])

    def test_record_thaw_supports_id_and_pos_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_thaw_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_thaw",
                {
                    "id": 1,
                    "pos": 1,
                    "thaw_date": "2026-02-10",
                    "action": "取出",
                },
            )
            self.assertTrue(response["ok"])

    def test_record_thaw_move_supports_target_position_aliases(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_thaw",
                {
                    "id": 1,
                    "pos": 1,
                    "to_pos": 2,
                    "thaw_date": "2026-02-10",
                    "action": "move",
                },
            )

            self.assertTrue(response["ok"])
            current = load_yaml(str(yaml_path))
            self.assertEqual([2], current["inventory"][0]["positions"])

    def test_record_thaw_move_missing_target_returns_hint(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_hint_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "record_thaw",
                {
                    "record_id": 1,
                    "position": 1,
                    "date": "2026-02-10",
                    "action": "move",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_move_target", response["error_code"])
            self.assertIn("to_position", response.get("_hint", ""))

    def test_tool_specs_expose_required_fields(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("add_entry", specs)
        self.assertIn("required", specs["add_entry"])
        self.assertIn("positions", specs["add_entry"]["required"])

        self.assertIn("search_records", specs)
        search_params = specs["search_records"].get("params", {})
        self.assertIn("mode", search_params)
        self.assertEqual(
            ["fuzzy", "exact", "keywords"],
            search_params["mode"].get("enum"),
        )

        self.assertIn("record_thaw", specs)
        self.assertIn("to_position", specs["record_thaw"].get("optional", []))

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
        self.assertIn("question", notes)
        self.assertIn("human", notes)


class EditEntryToolRunnerTests(unittest.TestCase):
    """Integration tests for edit_entry through AgentToolRunner."""

    def test_edit_entry_stages_plan_item(self):
        """edit_entry should produce a plan item with real position from record."""
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=2, positions=[15])]),
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
                {"record_id": 1, "fields": {"note": "updated note"}},
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, store.count())
            item = store.list_items()[0]
            self.assertEqual("edit", item["action"])
            self.assertEqual(1, item["record_id"])
            self.assertEqual(2, item["box"])
            self.assertEqual(15, item["position"])
            self.assertEqual("ai", item["source"])
            self.assertEqual({"note": "updated note"}, item["payload"]["fields"])

    def test_edit_entry_missing_record_id(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
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
                make_data([make_record(1, box=1, positions=[1])]),
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
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"record_id": 1, "fields": {}})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_nonexistent_record_uses_defaults(self):
        """When record doesn't exist, lookup returns defaults (box=0, pos=1)."""
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
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
                {"record_id": 999, "fields": {"note": "x"}},
            )

            # Should still stage (validation happens at plan execution time)
            self.assertTrue(response["ok"])
            self.assertEqual(1, store.count())
            item = store.list_items()[0]
            self.assertEqual(999, item["record_id"])
            # Defaults from _lookup_record_info when record not found
            self.assertEqual(0, item["box"])
            self.assertEqual(1, item["position"])

    def test_edit_entry_listed_in_tools(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        self.assertIn("edit_entry", set(runner.list_tools()))

    def test_edit_entry_in_tool_specs(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("edit_entry", specs)

    # --- cell_line alias tests ---

    def test_query_cell_alias(self):
        """Short 'cell' alias should work in query_inventory."""
        with tempfile.TemporaryDirectory(prefix="ln2_agent_cell_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {**make_record(1, box=1, positions=[1]), "cell_line": "NCCIT"},
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("query_inventory", {"cell": "NCCIT"})
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["count"])

    def test_add_entry_cell_line_in_tool_specs(self):
        """cell_line should be listed as optional param in add_entry spec."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("cell_line", specs["add_entry"]["optional"])

    def test_query_cell_line_in_tool_specs(self):
        """cell_line should be listed as optional param in query_inventory spec."""
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("cell_line", specs["query_inventory"]["optional"])


if __name__ == "__main__":
    unittest.main()
