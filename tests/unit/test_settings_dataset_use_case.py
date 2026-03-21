"""Unit tests for settings managed-dataset application use case."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import SettingsDatasetUseCase


class SettingsDatasetUseCaseTests(unittest.TestCase):
    def test_is_valid_inventory_file_path_requires_allowed_existing_yaml(self):
        use_case = SettingsDatasetUseCase(
            normalize_yaml_path=lambda value: str(value or "").strip(),
            assert_allowed_path=lambda path, must_exist=True: path,
        )

        self.assertFalse(use_case.is_valid_inventory_file_path(path_text=""))
        self.assertFalse(use_case.is_valid_inventory_file_path(path_text="D:/inventories/current.txt"))
        self.assertTrue(use_case.is_valid_inventory_file_path(path_text="D:/inventories/current.yaml"))

    def test_build_dataset_choices_normalizes_selected_yaml(self):
        calls = []
        use_case = SettingsDatasetUseCase(
            normalize_yaml_path=lambda value: str(value or "").strip().upper(),
            list_managed_datasets_fn=lambda: [{"name": "A", "yaml_path": "A.yaml"}],
            build_dataset_combo_items_fn=lambda rows, current_yaml: (
                calls.append((rows, current_yaml)) or [("A", "A.yaml")],
                0,
            ),
        )

        items, selected_idx = use_case.build_dataset_choices(selected_yaml=" a.yaml ")

        self.assertEqual([("A", "A.yaml")], items)
        self.assertEqual(0, selected_idx)
        self.assertEqual(([{"name": "A", "yaml_path": "A.yaml"}], "A.YAML"), calls[0])

    def test_managed_dataset_name_falls_back_to_parent_directory(self):
        use_case = SettingsDatasetUseCase(
            normalize_yaml_path=lambda value: str(value or "").strip(),
            managed_dataset_name_from_yaml_path_fn=lambda path: (_ for _ in ()).throw(ValueError(path)),
        )

        result = use_case.managed_dataset_name(
            yaml_path="D:/inventories/my-dataset/inventory.yaml",
        )

        self.assertEqual("my-dataset", result)

    def test_resolve_existing_yaml_path_returns_blank_when_disallowed(self):
        use_case = SettingsDatasetUseCase(
            normalize_yaml_path=lambda value: str(value or "").strip(),
            assert_allowed_path=lambda path, must_exist=True: (_ for _ in ()).throw(ValueError(path)),
        )

        self.assertEqual("", use_case.resolve_existing_yaml_path(yaml_path="D:/inventories/current.yaml"))


if __name__ == "__main__":
    unittest.main()
