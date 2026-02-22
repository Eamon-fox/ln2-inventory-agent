"""Tests for write-gate cell_line migration integration."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.custom_fields import DEFAULT_UNKNOWN_CELL_LINE
from lib.tool_api import validate_write_tool_call
from lib.yaml_ops import load_yaml, write_yaml


def _seed_yaml(path, data):
    write_yaml(
        data,
        path=str(path),
        auto_backup=False,
        audit_meta={"action": "seed", "source": "tests"},
    )


class TestWriteGateCellLineMigration(unittest.TestCase):
    def test_execute_mode_write_runs_cell_line_migration(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gate_cl_exec_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {
                        "box_layout": {"rows": 9, "cols": 9},
                        "cell_line_options": ["K562"],
                    },
                    "inventory": [
                        {"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"},
                    ],
                },
            )

            result = validate_write_tool_call(
                yaml_path=str(yaml_path),
                action="add_entry",
                source="agent.react",
                tool_name="tool_add_entry",
                tool_input={
                    "box": 1,
                    "positions": [2],
                    "frozen_at": "2026-02-10",
                },
                payload={"frozen_at": "2026-02-10", "positions": [2]},
                dry_run=False,
                execution_mode="execute",
                auto_backup=False,
            )
            self.assertTrue(result["ok"])

            data = load_yaml(str(yaml_path))
            self.assertTrue(data["meta"]["cell_line_required"])
            self.assertIn(DEFAULT_UNKNOWN_CELL_LINE, data["meta"]["cell_line_options"])
            self.assertEqual(DEFAULT_UNKNOWN_CELL_LINE, data["inventory"][0]["cell_line"])

    def test_execute_mode_rollback_skips_cell_line_migration(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gate_cl_rollback_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {"box_layout": {"rows": 9, "cols": 9}},
                    "inventory": [{"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"}],
                },
            )

            result = validate_write_tool_call(
                yaml_path=str(yaml_path),
                action="rollback",
                source="agent.react",
                tool_name="tool_rollback",
                tool_input={"dry_run": False},
                payload={},
                dry_run=False,
                execution_mode="execute",
                auto_backup=False,
            )
            self.assertTrue(result["ok"])

            data = load_yaml(str(yaml_path))
            self.assertNotIn("cell_line_required", data["meta"])
            self.assertNotIn("cell_line", data["inventory"][0])

    def test_direct_mode_write_does_not_run_migration(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gate_cl_direct_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {"box_layout": {"rows": 9, "cols": 9}},
                    "inventory": [{"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"}],
                },
            )

            result = validate_write_tool_call(
                yaml_path=str(yaml_path),
                action="add_entry",
                source="tool_api",
                tool_name="tool_add_entry",
                tool_input={
                    "box": 1,
                    "positions": [2],
                    "frozen_at": "2026-02-10",
                },
                payload={"frozen_at": "2026-02-10", "positions": [2]},
                dry_run=False,
                execution_mode=None,
                auto_backup=False,
            )
            self.assertTrue(result["ok"])
            self.assertEqual("direct", result["execution_mode"])

            data = load_yaml(str(yaml_path))
            self.assertNotIn("cell_line_required", data["meta"])
            self.assertNotIn("cell_line", data["inventory"][0])


if __name__ == "__main__":
    unittest.main()
