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

    def test_query_inventory_dispatch(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "positions": [10],
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
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
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 2,
                            "positions": [10],
                            "frozen_at": "2026-02-10",
                        }
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
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
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                actor_id="react-agent-test",
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
            self.assertEqual(2, len(current["inventory"]))

            audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
            rows = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last = rows[-1]
            self.assertEqual("agent", last["actor_type"])
            self.assertEqual("agent", last["channel"])
            self.assertEqual("react-agent-test", last["actor_id"])
            self.assertEqual("session-agent-test", last["session_id"])
            self.assertEqual("trace-agent-test", last["trace_id"])

    def test_record_thaw_requires_integer_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_bad_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("record_thaw", {"position": 1, "date": "2026-02-10"})
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_add_entry_supports_common_alias_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
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
            self.assertEqual("K562", records[-1]["parent_cell_line"])
            self.assertEqual([2], records[-1]["positions"])

    def test_record_thaw_supports_id_and_pos_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_thaw_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
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

    def test_tool_specs_expose_required_fields(self):
        runner = AgentToolRunner(yaml_path="/tmp/fake.yaml")
        specs = runner.tool_specs()
        self.assertIn("add_entry", specs)
        self.assertIn("required", specs["add_entry"])
        self.assertIn("positions", specs["add_entry"]["required"])


if __name__ == "__main__":
    unittest.main()
