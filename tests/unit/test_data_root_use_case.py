"""Unit tests for data-root migration orchestration."""

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import DataRootUseCase


class DataRootUseCaseTests(unittest.TestCase):
    def test_initialize_root_normalizes_target(self):
        use_case = DataRootUseCase(
            ensure_data_root_layout_fn=lambda value: str(Path(value).resolve()),
        )

        result = use_case.initialize_root(target_root="./demo-data")

        self.assertTrue(result.data_root.endswith("demo-data"))
        self.assertEqual("", result.yaml_path)
        self.assertFalse(result.migrated)

    def test_migrate_root_remaps_current_yaml_path(self):
        source_root = "/tmp/source-root"
        target_root = "/tmp/target-root"
        current_yaml = "/tmp/source-root/inventories/demo/inventory.yaml"
        use_case = DataRootUseCase(
            migrate_data_root_fn=lambda source, target: {"data_root": target},
            remap_inventory_yaml_path_fn=lambda yaml_path, source_root, target_root: (
                yaml_path.replace(source_root, target_root, 1)
            ),
        )

        result = use_case.migrate_root(
            source_root=source_root,
            target_root=target_root,
            current_yaml_path=current_yaml,
        )

        self.assertEqual(os.path.abspath(target_root), result.data_root)
        self.assertEqual("/tmp/target-root/inventories/demo/inventory.yaml", result.yaml_path)
        self.assertTrue(result.migrated)


if __name__ == "__main__":
    unittest.main()
