"""Dataset session switching controller.

All dataset-path switches in GUI should go through this controller.
"""

import os
from typing import Callable

from app_gui.gui_config import save_gui_config
from lib.inventory_paths import assert_allowed_inventory_yaml_path


class DatasetSessionController:
    """Single entrypoint for dataset switching side effects."""

    def __init__(
        self,
        window,
        *,
        normalize_yaml_path: Callable[[str], str],
    ):
        self._window = window
        self._normalize_yaml_path = normalize_yaml_path

    def switch_to(self, yaml_path: str, *, reason: str = "manual_switch") -> str:
        """Switch active dataset path and refresh all dependent UI state.

        Raises:
            ValueError / FileNotFoundError / InventoryPathError on invalid paths.
        """
        window = self._window
        old_abs = os.path.abspath(str(window.current_yaml_path or ""))
        normalized = self._normalize_yaml_path(yaml_path)
        target = assert_allowed_inventory_yaml_path(normalized, must_exist=True)
        new_abs = os.path.abspath(str(target))
        if old_abs == new_abs and str(reason or "") != "import_success":
            return target

        window.current_yaml_path = target
        window.operations_panel.reset_for_dataset_switch()
        window._update_dataset_label()
        window.overview_panel.refresh()
        window.gui_config["yaml_path"] = target
        save_gui_config(window.gui_config)
        return target

