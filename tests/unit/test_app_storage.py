"""Unit tests for app storage helpers."""

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import app_storage


class AppStorageTests(unittest.TestCase):
    def test_remap_inventory_yaml_path_preserves_dataset_relative_path(self):
        remapped = app_storage.remap_inventory_yaml_path(
            "/tmp/source/inventories/demo/inventory.yaml",
            source_root="/tmp/source",
            target_root="/tmp/target",
        )
        self.assertEqual("/tmp/target/inventories/demo/inventory.yaml", remapped)

    def test_migrate_data_root_copies_inventories_and_migrate(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            Path(source_dir, "inventories", "demo").mkdir(parents=True, exist_ok=True)
            Path(source_dir, "inventories", "demo", "inventory.yaml").write_text(
                "meta: {}\ninventory: []\n",
                encoding="utf-8",
            )
            Path(source_dir, "migrate", "output").mkdir(parents=True, exist_ok=True)
            Path(source_dir, "migrate", "output", "migration_checklist.md").write_text(
                "# checklist\n",
                encoding="utf-8",
            )

            app_storage.migrate_data_root(source_dir, target_dir)

            self.assertTrue(os.path.isfile(Path(target_dir, "inventories", "demo", "inventory.yaml")))
            self.assertTrue(os.path.isfile(Path(target_dir, "migrate", "output", "migration_checklist.md")))


if __name__ == "__main__":
    unittest.main()
