import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QDialog, QMessageBox

    from app_gui.main_window_flows import DatasetFlow, ManageBoxesFlow, SettingsFlow, WindowStateFlow

    PYSIDE_AVAILABLE = True
except Exception:
    QDialog = None
    QMessageBox = None
    DatasetFlow = None
    ManageBoxesFlow = None
    SettingsFlow = None
    WindowStateFlow = None
    PYSIDE_AVAILABLE = False


pytestmark = pytest.mark.skipif(not PYSIDE_AVAILABLE, reason="PySide6 is required")


class _FakeTextField:
    def __init__(self):
        self._value = ""

    def setText(self, value):
        self._value = str(value)

    def text(self):
        return self._value

    @property
    def value(self):
        return self._value


class _FakeSpinField:
    def __init__(self):
        self._value = 0

    def setValue(self, value):
        self._value = int(value)

    def value(self):
        return self._value

    @property
    def current(self):
        return self._value


class _FakeCheckField:
    def __init__(self):
        self._value = False

    def setChecked(self, value):
        self._value = bool(value)

    def isChecked(self):
        return self._value

    @property
    def value(self):
        return self._value


def _build_settings_window(path_text):
    status = MagicMock()
    window = SimpleNamespace()
    window.current_yaml_path = path_text
    window.gui_config = {
        "language": "zh-CN",
        "theme": "dark",
        "ui_scale": 1.0,
        "api_keys": {},
        "ai": {},
    }
    window.bridge = SimpleNamespace(set_api_keys=MagicMock())
    window.ai_panel = SimpleNamespace(
        ai_provider=_FakeTextField(),
        ai_model=_FakeTextField(),
        ai_steps=_FakeSpinField(),
        ai_thinking_enabled=_FakeCheckField(),
        ai_thinking_collapsed=False,
        ai_custom_prompt="",
    )
    window._update_dataset_label = MagicMock()
    window.overview_panel = SimpleNamespace(refresh=MagicMock())
    window.operations_panel = SimpleNamespace(apply_meta_update=MagicMock())
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status))
    return window, status


def test_settings_flow_apply_and_finalize_updates_runtime_state():
    window, status_message = _build_settings_window("/tmp/missing-inventory.yaml")
    flow = SettingsFlow(window, normalize_yaml_path=lambda x: str(x or "").strip())
    values = {
        "api_keys": {"deepseek": "sk-test"},
        "language": "zh-CN",
        "theme": "dark",
        "ui_scale": 1.0,
        "ai_provider": "deepseek",
        "ai_model": "deepseek-chat",
        "ai_max_steps": 9,
        "ai_thinking_enabled": False,
        "ai_thinking_expanded": False,
        "ai_custom_prompt": "use concise style",
    }

    with patch("app_gui.main_window_flows.save_gui_config") as save_mock:
        flow.apply_dialog_values(values)
        flow.finalize_after_settings()

    assert window.gui_config["api_keys"] == {"deepseek": "sk-test"}
    assert window.gui_config["yaml_path"] == window.current_yaml_path
    assert window.ai_panel.ai_provider.value == "deepseek"
    assert window.ai_panel.ai_model.value == "deepseek-chat"
    assert window.ai_panel.ai_steps.current == 9
    assert window.ai_panel.ai_thinking_enabled.value is False
    assert window.ai_panel.ai_thinking_collapsed is True
    assert window.ai_panel.ai_custom_prompt == "use concise style"
    window.bridge.set_api_keys.assert_called_once_with({"deepseek": "sk-test"})
    window._update_dataset_label.assert_called_once()
    window.overview_panel.refresh.assert_called_once()
    window.operations_panel.apply_meta_update.assert_called_once_with()
    status_message.assert_called_once()
    save_mock.assert_called_once_with(window.gui_config)


def test_settings_flow_data_change_ignores_other_dataset():
    window, _status_message = _build_settings_window("D:/tmp/current.yaml")
    flow = SettingsFlow(window, normalize_yaml_path=lambda x: os.path.abspath(str(x or "")))

    flow.handle_data_changed(yaml_path="D:/tmp/other.yaml", meta={"box_layout": {"A": 1}})
    window.operations_panel.apply_meta_update.assert_not_called()
    window.overview_panel.refresh.assert_not_called()

    flow.handle_data_changed(yaml_path="D:/tmp/current.yaml", meta={"box_layout": {"A": 1}})
    window.operations_panel.apply_meta_update.assert_called_once_with({"box_layout": {"A": 1}})
    window.overview_panel.refresh.assert_called_once()


def test_dataset_flow_writes_new_dataset_yaml():
    class _AcceptedCustomFieldsDialog:
        def __init__(self, _parent):
            pass

        def exec(self):
            return QDialog.Accepted

        def get_custom_fields(self):
            return [{"key": "short_name", "label": "Short Name", "type": "str", "required": False}]

        def get_display_key(self):
            return "short_name"

        def get_cell_line_required(self):
            return True

        def get_cell_line_options(self):
            return ["K562", "HeLa"]

    flow = DatasetFlow(SimpleNamespace())
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "new_inventory.yaml")
        created_path = flow.create_dataset_file(
            target_path=target,
            box_layout={"box_1": {"rows": 9, "cols": 9}},
            custom_fields_dialog_cls=_AcceptedCustomFieldsDialog,
        )

        assert created_path == target
        payload = yaml.safe_load(Path(target).read_text(encoding="utf-8"))
        assert payload["inventory"] == []
        assert payload["meta"]["box_layout"] == {"box_1": {"rows": 9, "cols": 9}}
        assert payload["meta"]["display_key"] == "short_name"
        assert payload["meta"]["cell_line_required"] is True
        assert payload["meta"]["cell_line_options"] == ["K562", "HeLa"]


def test_manage_boxes_flow_add_request_executes_and_emits_notice():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

        bridge_calls = []

        class _Bridge:
            def adjust_box_count(self, **kwargs):
                bridge_calls.append(kwargs)
                return {"ok": True, "result": {"count": 2}, "message": "ok"}

        window = SimpleNamespace(
            current_yaml_path=yaml_path,
            bridge=_Bridge(),
            overview_panel=SimpleNamespace(refresh=MagicMock()),
            on_operation_completed=MagicMock(),
            operations_panel=SimpleNamespace(emit_external_operation_event=MagicMock()),
            show_status=MagicMock(),
        )
        flow = ManageBoxesFlow(window)

        with patch("app_gui.main_window_flows.QMessageBox.question", return_value=QMessageBox.Yes):
            result = flow.handle_request(
                {"operation": "add", "count": 2},
                from_ai=False,
                yaml_path_override=yaml_path,
            )

        assert result["ok"] is True
        assert bridge_calls
        assert bridge_calls[0]["operation"] == "add"
        assert bridge_calls[0]["count"] == 2
        window.overview_panel.refresh.assert_called_once()
        window.on_operation_completed.assert_called_once_with(True)
        window.show_status.assert_called_once()
        window.operations_panel.emit_external_operation_event.assert_called_once()


def test_window_state_flow_restore_and_label_and_stats():
    stats_bar = SimpleNamespace(setText=MagicMock())
    dataset_label = SimpleNamespace(setText=MagicMock())
    window = SimpleNamespace(
        settings=SimpleNamespace(value=MagicMock(return_value=b"geometry")),
        restoreGeometry=MagicMock(),
        gui_config={
            "ai": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "max_steps": 7,
                "thinking_enabled": False,
                "thinking_expanded": False,
                "custom_prompt": "abc",
            }
        },
        ai_panel=SimpleNamespace(
            ai_provider=_FakeTextField(),
            ai_model=_FakeTextField(),
            ai_steps=_FakeSpinField(),
            ai_thinking_enabled=_FakeCheckField(),
            ai_thinking_collapsed=False,
            ai_custom_prompt="",
        ),
        dataset_label=dataset_label,
        current_yaml_path="D:/tmp/inventory.yaml",
        stats_bar=stats_bar,
    )
    flow = WindowStateFlow(window)

    flow.restore_ui_settings()
    flow.update_dataset_label()
    flow.update_stats_bar({"total": 1, "occupied": 1, "empty": 0, "rate": 100.0})
    flow.update_hover_stats("hover details")
    flow.update_hover_stats("")

    window.restoreGeometry.assert_called_once_with(b"geometry")
    assert window.ai_panel.ai_provider.value == "deepseek"
    assert window.ai_panel.ai_model.value == "deepseek-chat"
    assert window.ai_panel.ai_steps.current == 7
    assert window.ai_panel.ai_thinking_enabled.value is False
    assert window.ai_panel.ai_thinking_collapsed is True
    assert window.ai_panel.ai_custom_prompt == "abc"
    dataset_label.setText.assert_called_once_with("D:/tmp/inventory.yaml")
    assert stats_bar.setText.call_count >= 3


def test_window_state_flow_close_event_busy_and_persist():
    busy_event = SimpleNamespace(ignore=MagicMock())
    busy_window = SimpleNamespace(ai_panel=SimpleNamespace(ai_run_inflight=True))
    busy_flow = WindowStateFlow(busy_window)
    with patch("app_gui.main_window_flows.QMessageBox.warning") as warn_mock:
        ok = busy_flow.handle_close_event(busy_event)
    assert ok is False
    busy_event.ignore.assert_called_once()
    warn_mock.assert_called_once()

    event = SimpleNamespace(ignore=MagicMock())
    window = SimpleNamespace(
        ai_panel=SimpleNamespace(
            ai_run_inflight=False,
            ai_provider=_FakeTextField(),
            ai_model=_FakeTextField(),
            ai_steps=_FakeSpinField(),
            ai_thinking_enabled=_FakeCheckField(),
            ai_thinking_collapsed=False,
            ai_custom_prompt="prompt text",
        ),
        settings=SimpleNamespace(setValue=MagicMock()),
        saveGeometry=MagicMock(return_value=b"geo"),
        gui_config={},
        current_yaml_path="D:/tmp/current.yaml",
    )
    window.ai_panel.ai_provider.setText("deepseek")
    window.ai_panel.ai_model.setText("deepseek-chat")
    window.ai_panel.ai_steps.setValue(11)
    window.ai_panel.ai_thinking_enabled.setChecked(True)
    flow = WindowStateFlow(window)

    with patch("app_gui.main_window_flows.save_gui_config") as save_mock:
        ok = flow.handle_close_event(event)

    assert ok is True
    window.settings.setValue.assert_called_once_with("ui/geometry", b"geo")
    assert window.gui_config["yaml_path"] == "D:/tmp/current.yaml"
    assert window.gui_config["ai"]["provider"] == "deepseek"
    assert window.gui_config["ai"]["model"] == "deepseek-chat"
    assert window.gui_config["ai"]["max_steps"] == 11
    assert window.gui_config["ai"]["thinking_enabled"] is True
    assert window.gui_config["ai"]["thinking_expanded"] is True
    assert window.gui_config["ai"]["custom_prompt"] == "prompt text"
    save_mock.assert_called_once_with(window.gui_config)
