"""Unit tests for first-open legacy dataset auto-migration."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.inventory_paths import ensure_inventories_root, get_inventories_root
from lib.yaml_ops import ensure_runtime_dataset_canonical, load_yaml_raw, read_audit_events


class RuntimeDatasetMigrationTests(unittest.TestCase):
    def _make_dataset_yaml(self, payload):
        ensure_inventories_root()
        dataset_dir = tempfile.mkdtemp(prefix="ln2_runtime_upgrade_", dir=get_inventories_root())
        self.addCleanup(shutil.rmtree, dataset_dir, True)
        yaml_path = os.path.join(dataset_dir, "inventory.yaml")
        with open(yaml_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        return yaml_path

    def test_legacy_dataset_is_backed_up_and_migrated_in_place(self):
        yaml_path = self._make_dataset_yaml(
            {
                "meta": {
                    "version": "1.0",
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 1, "box_numbers": [1]},
                    "cell_line_options": ["K562", "NCCIT"],
                    "cell_line_required": True,
                },
                "inventory": [
                    {
                        "id": 1,
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-01-02",
                        "parent_cell_line": "K562",
                        "short_name": "clone-a",
                    }
                ],
            }
        )

        result = ensure_runtime_dataset_canonical(
            yaml_path,
            source="tests.runtime_dataset_upgrade",
        )

        self.assertTrue(result["changed"])
        self.assertTrue(os.path.isfile(result["backup_path"]))

        migrated = load_yaml_raw(yaml_path)
        meta = migrated["meta"]
        record = migrated["inventory"][0]

        self.assertNotIn("cell_line_options", meta)
        self.assertNotIn("cell_line_required", meta)
        self.assertEqual("cell_line", meta["custom_fields"][0]["key"])
        self.assertNotIn("parent_cell_line", record)
        self.assertEqual("K562", record["cell_line"])
        self.assertNotIn("frozen_at", record)
        self.assertEqual("2026-01-02", record["stored_at"])

        events = read_audit_events(yaml_path)
        actions = [str((event or {}).get("action") or "") for event in events]
        self.assertIn("backup", actions)
        self.assertIn("dataset_auto_migrate_legacy", actions)

    def test_canonical_dataset_is_left_untouched(self):
        yaml_path = self._make_dataset_yaml(
            {
                "meta": {
                    "version": "1.0",
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 1, "box_numbers": [1]},
                    "custom_fields": [
                        {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "box": 1,
                        "position": 1,
                        "stored_at": "2026-01-02",
                        "cell_line": "K562",
                        "short_name": "clone-a",
                    }
                ],
            }
        )

        result = ensure_runtime_dataset_canonical(
            yaml_path,
            source="tests.runtime_dataset_upgrade",
        )

        self.assertFalse(result["changed"])
        self.assertIsNone(result["backup_path"])


if __name__ == "__main__":
    unittest.main()
