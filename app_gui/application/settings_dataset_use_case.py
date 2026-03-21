"""Application use case for settings-dialog managed dataset interactions."""

import os
from typing import Callable, List, Tuple

from lib.inventory_paths import (
    assert_allowed_inventory_yaml_path,
    build_dataset_combo_items,
    list_managed_datasets,
    managed_dataset_name_from_yaml_path,
    normalize_inventory_yaml_path,
)


class SettingsDatasetUseCase:
    """Coordinate managed dataset path and chooser behavior for settings UI."""

    def __init__(
        self,
        *,
        normalize_yaml_path: Callable[[str], str] = normalize_inventory_yaml_path,
        assert_allowed_path: Callable[..., str] = assert_allowed_inventory_yaml_path,
        list_managed_datasets_fn: Callable[[], list] = list_managed_datasets,
        build_dataset_combo_items_fn: Callable[[list, str], Tuple[List[Tuple[str, str]], int]] = build_dataset_combo_items,
        managed_dataset_name_from_yaml_path_fn: Callable[[str], str] = managed_dataset_name_from_yaml_path,
    ):
        self._normalize_yaml_path = normalize_yaml_path
        self._assert_allowed_path = assert_allowed_path
        self._list_managed_datasets = list_managed_datasets_fn
        self._build_dataset_combo_items = build_dataset_combo_items_fn
        self._managed_dataset_name_from_yaml_path = managed_dataset_name_from_yaml_path_fn

    def is_valid_inventory_file_path(self, *, path_text: str) -> bool:
        path = self._normalize_yaml_path(path_text)
        if not path or os.path.isdir(path):
            return False
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in {".yaml", ".yml"}:
            return False
        try:
            self._assert_allowed_path(path, must_exist=True)
        except Exception:
            return False
        return True

    def build_dataset_choices(self, *, selected_yaml: str) -> Tuple[List[Tuple[str, str]], int]:
        rows = self._list_managed_datasets()
        current_yaml = self._normalize_yaml_path(selected_yaml)
        return self._build_dataset_combo_items(rows, current_yaml)

    def managed_dataset_name(self, *, yaml_path: str) -> str:
        normalized = self._normalize_yaml_path(yaml_path)
        if not normalized:
            return ""
        try:
            return self._managed_dataset_name_from_yaml_path(normalized)
        except Exception:
            return os.path.basename(os.path.dirname(normalized)) or normalized

    def resolve_existing_yaml_path(self, *, yaml_path: str) -> str:
        normalized = self._normalize_yaml_path(yaml_path)
        if not normalized:
            return ""
        try:
            return self._assert_allowed_path(normalized, must_exist=True)
        except Exception:
            return ""
