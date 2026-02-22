"""Tests for lib.migrate_cell_line_policy."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.custom_fields import DEFAULT_UNKNOWN_CELL_LINE
from lib.migrate_cell_line_policy import migrate_cell_line_policy
from lib.yaml_ops import load_yaml, write_yaml


def _seed_yaml(path, data):
    write_yaml(
        data,
        path=str(path),
        auto_backup=False,
        audit_meta={"action": "seed", "source": "tests"},
    )


class TestMigrateCellLinePolicy(unittest.TestCase):
    def test_migrate_normalizes_required_options_and_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_migrate_cl_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {
                        "box_layout": {"rows": 9, "cols": 9},
                        "cell_line_options": ["K562", "HeLa"],
                    },
                    "inventory": [
                        {"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"},
                        {"id": 2, "cell_line": "", "box": 1, "position": 2, "frozen_at": "2026-02-10"},
                        {"id": 3, "cell_line": "  U2OS  ", "box": 1, "position": 3, "frozen_at": "2026-02-10"},
                    ],
                },
            )

            result = migrate_cell_line_policy(
                yaml_path=str(yaml_path),
                dry_run=False,
                auto_backup=False,
                audit_source="tests",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])

            data = load_yaml(str(yaml_path))
            meta = data["meta"]
            self.assertTrue(meta["cell_line_required"])
            self.assertIn(DEFAULT_UNKNOWN_CELL_LINE, meta["cell_line_options"])
            self.assertIn("U2OS", meta["cell_line_options"])

            by_id = {int(rec["id"]): rec for rec in data["inventory"]}
            self.assertEqual(DEFAULT_UNKNOWN_CELL_LINE, by_id[1]["cell_line"])
            self.assertEqual(DEFAULT_UNKNOWN_CELL_LINE, by_id[2]["cell_line"])
            self.assertEqual("U2OS", by_id[3]["cell_line"])

    def test_migrate_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="ln2_migrate_cl_idem_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {
                        "box_layout": {"rows": 9, "cols": 9},
                    },
                    "inventory": [
                        {"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"},
                    ],
                },
            )

            first = migrate_cell_line_policy(str(yaml_path), dry_run=False, auto_backup=False, audit_source="tests")
            second = migrate_cell_line_policy(str(yaml_path), dry_run=False, auto_backup=False, audit_source="tests")

            self.assertTrue(first["ok"])
            self.assertTrue(first["changed"])
            self.assertTrue(second["ok"])
            self.assertFalse(second["changed"])
            self.assertEqual(0, second["summary"]["records_changed"])

    def test_dry_run_reports_change_without_writing(self):
        with tempfile.TemporaryDirectory(prefix="ln2_migrate_cl_dry_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _seed_yaml(
                yaml_path,
                {
                    "meta": {"box_layout": {"rows": 9, "cols": 9}},
                    "inventory": [{"id": 1, "box": 1, "position": 1, "frozen_at": "2026-02-10"}],
                },
            )

            result = migrate_cell_line_policy(str(yaml_path), dry_run=True, auto_backup=False, audit_source="tests")
            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["changed"])

            data = load_yaml(str(yaml_path))
            self.assertNotIn("cell_line_required", data["meta"])
            self.assertNotIn("cell_line", data["inventory"][0])


if __name__ == "__main__":
    unittest.main()
