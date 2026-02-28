"""
Module: test_dataset_session
Layer: integration/gui
Covers: app_gui/dataset_session.py

数据集会话切换与路径刷新测试
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app_gui.dataset_session import DatasetSessionController


def _build_window(current_path):
    return SimpleNamespace(
        current_yaml_path=current_path,
        operations_panel=SimpleNamespace(reset_for_dataset_switch=MagicMock()),
        overview_panel=SimpleNamespace(refresh=MagicMock()),
        gui_config={},
        _update_dataset_label=MagicMock(),
    )


def test_switch_to_updates_path_and_refreshes_state():
    window = _build_window("D:/data/old/inventory.yaml")
    controller = DatasetSessionController(window, normalize_yaml_path=lambda p: str(p))
    target = "D:/data/new/inventory.yaml"

    with patch(
        "app_gui.dataset_session.assert_allowed_inventory_yaml_path",
        return_value=target,
    ) as assert_mock, patch("app_gui.dataset_session.save_gui_config") as save_mock:
        result = controller.switch_to(target, reason="manual_switch")

    assert result == target
    assert window.current_yaml_path == target
    window.operations_panel.reset_for_dataset_switch.assert_called_once()
    window._update_dataset_label.assert_called_once()
    window.overview_panel.refresh.assert_called_once()
    assert window.gui_config["yaml_path"] == target
    assert_mock.assert_called_once_with(target, must_exist=True)
    save_mock.assert_called_once_with(window.gui_config)


def test_switch_to_skips_reset_for_same_path_in_manual_mode():
    path = os.path.abspath("D:/data/same/inventory.yaml")
    window = _build_window(path)
    controller = DatasetSessionController(window, normalize_yaml_path=lambda p: str(p))

    with patch(
        "app_gui.dataset_session.assert_allowed_inventory_yaml_path",
        return_value=path,
    ), patch("app_gui.dataset_session.save_gui_config") as save_mock:
        result = controller.switch_to(path, reason="manual_switch")

    assert result == path
    window.operations_panel.reset_for_dataset_switch.assert_not_called()
    window._update_dataset_label.assert_not_called()
    window.overview_panel.refresh.assert_not_called()
    save_mock.assert_not_called()


def test_switch_to_forces_refresh_for_import_success_even_same_path():
    path = os.path.abspath("D:/data/same/inventory.yaml")
    window = _build_window(path)
    controller = DatasetSessionController(window, normalize_yaml_path=lambda p: str(p))

    with patch(
        "app_gui.dataset_session.assert_allowed_inventory_yaml_path",
        return_value=path,
    ), patch("app_gui.dataset_session.save_gui_config"):
        result = controller.switch_to(path, reason="import_success")

    assert result == path
    window.operations_panel.reset_for_dataset_switch.assert_called_once()
    window._update_dataset_label.assert_called_once()
    window.overview_panel.refresh.assert_called_once()

