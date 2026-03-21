"""
Module: test_main_window_flows
Layer: integration/gui
Covers: app_gui/main_window_flows.py

主窗口端到端用户流程测试
"""

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from app_gui.main_window_flows import DatasetFlow, ManageBoxesFlow, SettingsFlow, WindowStateFlow
    from app_gui.ui.dialogs.new_dataset_dialog import NewDatasetDialog
    from app_gui.ui.limits import MAX_BOX_COUNT_UI

    PYSIDE_AVAILABLE = True
except Exception:
    Qt = None
    QApplication = None
    QDialog = None
    QMessageBox = None
    DatasetFlow = None
    ManageBoxesFlow = None
    SettingsFlow = None
    WindowStateFlow = None
    NewDatasetDialog = None
    MAX_BOX_COUNT_UI = 200
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


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _FakeAIPanelState:
    def __init__(self, *, ai_run_inflight=False):
        self.ai_provider = _FakeTextField()
        self.ai_model = _FakeTextField()
        self.ai_steps = _FakeSpinField()
        self.ai_thinking_enabled = _FakeCheckField()
        self.ai_custom_prompt = ""
        self.ai_run_inflight = bool(ai_run_inflight)

    def apply_runtime_settings(self, *, provider, model, max_steps, thinking_enabled, custom_prompt=""):
        self.ai_provider.setText(provider)
        self.ai_model.setText(model)
        self.ai_steps.setValue(max_steps)
        self.ai_thinking_enabled.setChecked(thinking_enabled)
        self.ai_custom_prompt = str(custom_prompt or "")

    def runtime_settings_snapshot(self):
        return {
            "provider": self.ai_provider.text(),
            "model": self.ai_model.text(),
            "max_steps": self.ai_steps.value(),
            "thinking_enabled": self.ai_thinking_enabled.isChecked(),
            "custom_prompt": self.ai_custom_prompt,
        }

    def has_running_task(self):
        return bool(self.ai_run_inflight)


class _FakeCheckBoxWidget:
    def __init__(self, text="", parent=None):
        _ = parent
        self._text = str(text)
        self._checked = False

    def setChecked(self, value):
        self._checked = bool(value)

    def isChecked(self):
        return bool(self._checked)


class _FakeMessageBox:
    Information = 1
    AcceptRole = 0

    def __init__(self, parent=None):
        _ = parent
        self.finished = _FakeSignal()
        self._checkbox = None

    def setWindowTitle(self, value):
        self.window_title = str(value)

    def setText(self, value):
        self.text = str(value)

    def setIcon(self, value):
        self.icon = value

    def setCheckBox(self, checkbox):
        self._checkbox = checkbox

    def checkBox(self):
        return self._checkbox

    def addButton(self, text, role):
        btn = SimpleNamespace(text=str(text), role=role)
        self.default_button = btn
        return btn

    def setDefaultButton(self, button):
        self.default_button = button


class _FakeComboBox:
    def __init__(self):
        self.items = []
        self.current_index = -1
        self.enabled = True
        self.tooltip = ""
        self.blocked = False

    def blockSignals(self, value):
        self.blocked = bool(value)

    def clear(self):
        self.items = []
        self.current_index = -1

    def addItem(self, text, data):
        self.items.append((str(text), data))

    def setEnabled(self, value):
        self.enabled = bool(value)

    def findData(self, data):
        for idx, item in enumerate(self.items):
            if item[1] == data:
                return idx
        return -1

    def setCurrentIndex(self, index):
        self.current_index = int(index)

    def currentData(self):
        if self.current_index < 0 or self.current_index >= len(self.items):
            return None
        return self.items[self.current_index][1]

    def setToolTip(self, text):
        self.tooltip = str(text)


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _build_settings_window(path_text):
    status = MagicMock()
    window = SimpleNamespace()
    window.current_yaml_path = path_text
    window.gui_config = {
        "language": "zh-CN",
        "theme": "dark",
        "ui_scale": 1.0,
        "api_keys": {},
        "open_api": {"enabled": False, "port": 37666},
        "ai": {},
    }
    window.bridge = SimpleNamespace()
    window.agent_session = SimpleNamespace(set_api_keys=MagicMock())
    window.ai_panel = _FakeAIPanelState()
    window._apply_local_open_api_settings = MagicMock(return_value={"ok": True, "running": False})
    window._current_local_open_api_config = MagicMock(return_value={"enabled": False, "port": 37666})
    window._local_open_api_service = SimpleNamespace(stop=MagicMock())
    window._update_dataset_label = MagicMock()
    window.overview_panel = SimpleNamespace(refresh=MagicMock())
    window.operations_panel = SimpleNamespace(apply_meta_update=MagicMock())
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status))
    window._emit_system_notice = MagicMock()
    return window, status


def test_settings_flow_apply_and_finalize_updates_runtime_state():
    window, status_message = _build_settings_window("/tmp/missing-inventory.yaml")
    flow = SettingsFlow(window, normalize_yaml_path=lambda x: str(x or "").strip())
    values = SimpleNamespace(
        api_keys={"deepseek": "sk-test"},
        language="zh-CN",
        theme="dark",
        ui_scale=1.0,
        open_api_enabled=True,
        open_api_port=40123,
        ai_provider="deepseek",
        ai_model="deepseek-chat",
        ai_max_steps=9,
        ai_thinking_enabled=False,
        ai_custom_prompt="use concise style",
    )

    with patch("app_gui.main_window_flows.save_gui_config") as save_mock:
        flow.apply_dialog_values(values)
        flow.finalize_after_settings()

    assert window.gui_config["api_keys"] == {"deepseek": "sk-test"}
    assert window.gui_config["open_api"] == {"enabled": True, "port": 40123}
    assert window.gui_config["yaml_path"] == window.current_yaml_path
    assert window.ai_panel.ai_provider.value == "deepseek"
    assert window.ai_panel.ai_model.value == "deepseek-chat"
    assert window.ai_panel.ai_steps.current == 9
    assert window.ai_panel.ai_thinking_enabled.value is False
    assert window.ai_panel.ai_custom_prompt == "use concise style"
    window.agent_session.set_api_keys.assert_called_once_with({"deepseek": "sk-test"})
    window._apply_local_open_api_settings.assert_called_once_with(show_feedback=True)
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
    window._emit_system_notice.assert_not_called()


def test_settings_flow_data_change_emits_custom_fields_notice():
    window, _status_message = _build_settings_window("D:/tmp/current.yaml")
    flow = SettingsFlow(window, normalize_yaml_path=lambda x: os.path.abspath(str(x or "")))

    flow.handle_data_changed(
        yaml_path="D:/tmp/current.yaml",
        meta={"custom_fields": [{"key": "short_name"}]},
    )

    window._emit_system_notice.assert_called_once()
    notice_kwargs = window._emit_system_notice.call_args.kwargs
    assert notice_kwargs["code"] == "settings.custom_fields.updated"
    assert notice_kwargs["source"] == "settings_dialog"
    assert notice_kwargs["data"]["custom_field_count"] == 1


def test_dataset_flow_delegates_dataset_creation_to_lifecycle_use_case():
    class _AcceptedCustomFieldsDialog:
        def __init__(self, _parent):
            pass

        def exec(self):
            return QDialog.Accepted

        def get_custom_fields(self):
            return [
                {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ]

        def get_display_key(self):
            return "short_name"

        def get_color_key(self):
            return "cell_line"

    lifecycle = SimpleNamespace(
        create_dataset=MagicMock(
            return_value=SimpleNamespace(target_path="D:/inventories/new_inventory/inventory.yaml")
        )
    )
    flow = DatasetFlow(SimpleNamespace(), dataset_lifecycle_use_case=lifecycle)

    created_path = flow.create_dataset_file(
        target_path="D:/inventories/new_inventory/inventory.yaml",
        box_layout={"box_1": {"rows": 9, "cols": 9}},
        custom_fields_dialog_cls=_AcceptedCustomFieldsDialog,
    )

    assert created_path == "D:/inventories/new_inventory/inventory.yaml"
    lifecycle.create_dataset.assert_called_once_with(
        target_path="D:/inventories/new_inventory/inventory.yaml",
        box_layout={"box_1": {"rows": 9, "cols": 9}},
        custom_fields=[
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
            {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
        ],
        display_key="short_name",
        color_key="cell_line",
    )


def test_dataset_flow_returns_none_when_custom_fields_dialog_is_cancelled():
    class _RejectedCustomFieldsDialog:
        def __init__(self, _parent):
            pass

        def exec(self):
            return QDialog.Rejected

    lifecycle = SimpleNamespace(create_dataset=MagicMock())
    flow = DatasetFlow(SimpleNamespace(), dataset_lifecycle_use_case=lifecycle)

    created_path = flow.create_dataset_file(
        target_path="D:/inventories/new_inventory/inventory.yaml",
        box_layout={"box_1": {"rows": 9, "cols": 9}},
        custom_fields_dialog_cls=_RejectedCustomFieldsDialog,
    )

    assert created_path is None
    lifecycle.create_dataset.assert_not_called()


def test_new_dataset_dialog_box_count_limit_is_ui_max():
    _ensure_qapp()
    dialog = NewDatasetDialog()
    assert dialog.box_count_spin.minimum() == 1
    assert dialog.box_count_spin.maximum() == MAX_BOX_COUNT_UI


def test_manage_boxes_flow_add_request_executes_and_emits_notice():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

        bridge_calls = []

        class _Bridge:
            def manage_boxes(self, **kwargs):
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


def test_manage_boxes_flow_async_add_uses_non_modal_confirm_and_callback():
    app = _ensure_qapp()
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

        bridge_calls = []

        class _Bridge:
            def manage_boxes(self, **kwargs):
                bridge_calls.append(kwargs)
                return {"ok": True, "result": {"count": 2}, "message": "ok"}

        window = QDialog()
        window.current_yaml_path = yaml_path
        window.bridge = _Bridge()
        window.overview_panel = SimpleNamespace(refresh=MagicMock())
        window.on_operation_completed = MagicMock()
        window.operations_panel = SimpleNamespace(emit_external_operation_event=MagicMock())
        window.show_status = MagicMock()
        window._floating_dialog_refs = []
        flow = ManageBoxesFlow(window)
        results = []

        session = flow.handle_request_async(
            {"operation": "add", "count": 2},
            on_result=results.append,
            from_ai=True,
            yaml_path_override=yaml_path,
        )

        assert session is not None
        app.processEvents()

        dialogs = [dialog for dialog in window.findChildren(QMessageBox) if dialog.isVisible()]
        assert len(dialogs) == 1
        assert dialogs[0].windowModality() == Qt.NonModal

        dialogs[0].button(QMessageBox.Yes).click()
        app.processEvents()

        assert results and results[0]["ok"] is True
        assert bridge_calls
        assert bridge_calls[0]["operation"] == "add"
        assert bridge_calls[0]["count"] == 2
        window.overview_panel.refresh.assert_called_once()
        window.on_operation_completed.assert_called_once_with(True)
        window.show_status.assert_called_once()
        window.operations_panel.emit_external_operation_event.assert_called_once()


def test_manage_boxes_flow_async_remove_cancel_returns_user_cancelled():
    app = _ensure_qapp()
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 3\n"
                "inventory: []\n"
            ),
            encoding="utf-8",
        )

        adjust_mock = MagicMock(return_value={"ok": True})
        window = QDialog()
        window.current_yaml_path = yaml_path
        window.bridge = SimpleNamespace(manage_boxes=adjust_mock)
        window.overview_panel = SimpleNamespace(refresh=MagicMock())
        window.on_operation_completed = MagicMock()
        window.operations_panel = SimpleNamespace(emit_external_operation_event=MagicMock())
        window.show_status = MagicMock()
        window._floating_dialog_refs = []
        flow = ManageBoxesFlow(window)
        results = []

        session = flow.handle_request_async(
            {"operation": "remove", "box": 2},
            on_result=results.append,
            from_ai=True,
            yaml_path_override=yaml_path,
        )

        assert session is not None
        app.processEvents()

        dialogs = [dialog for dialog in window.findChildren(QMessageBox) if dialog.isVisible()]
        assert len(dialogs) == 1
        assert dialogs[0].windowModality() == Qt.NonModal

        dialogs[0].button(QMessageBox.Cancel).click()
        app.processEvents()

        assert results and results[0]["ok"] is False
        assert results[0]["error_code"] == "user_cancelled"
        adjust_mock.assert_not_called()
        window.overview_panel.refresh.assert_not_called()
        window.on_operation_completed.assert_not_called()
        window.operations_panel.emit_external_operation_event.assert_not_called()
        window.show_status.assert_not_called()


def test_manage_boxes_prompt_add_uses_ui_max_limit():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

        window = SimpleNamespace(current_yaml_path=yaml_path)
        flow = ManageBoxesFlow(window)

        with patch(
            "app_gui.main_window_flows.QInputDialog.getItem",
            return_value=("Add boxes", True),
        ), patch(
            "app_gui.main_window_flows.tr",
            side_effect=lambda key, **kwargs: (
                "Add boxes" if key == "main.boxOpAdd" else str(key)
            ),
        ), patch(
            "app_gui.main_window_flows.QInputDialog.getInt",
            return_value=(MAX_BOX_COUNT_UI, True),
        ) as get_int_mock:
            result = flow.prompt_request(yaml_path_override=yaml_path)

        assert result == {"operation": "add", "count": MAX_BOX_COUNT_UI}
        assert get_int_mock.call_count == 1
        assert get_int_mock.call_args.args[5] == MAX_BOX_COUNT_UI


def test_manage_boxes_flow_add_requires_explicit_count():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

        adjust_mock = MagicMock(return_value={"ok": True})
        window = SimpleNamespace(
            current_yaml_path=yaml_path,
            bridge=SimpleNamespace(manage_boxes=adjust_mock),
            overview_panel=SimpleNamespace(refresh=MagicMock()),
            on_operation_completed=MagicMock(),
            operations_panel=SimpleNamespace(emit_external_operation_event=MagicMock()),
            show_status=MagicMock(),
        )
        flow = ManageBoxesFlow(window)

        result = flow.handle_request(
            {"operation": "add"},
            from_ai=True,
            yaml_path_override=yaml_path,
        )

        assert result["ok"] is False
        assert result["error_code"] == "invalid_count"
        adjust_mock.assert_not_called()
        window.overview_panel.refresh.assert_not_called()
        window.on_operation_completed.assert_not_called()
        window.operations_panel.emit_external_operation_event.assert_not_called()
        window.show_status.assert_not_called()


def test_manage_boxes_flow_remove_invalid_box_fails_before_confirm():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 2\n"
                "inventory: []\n"
            ),
            encoding="utf-8",
        )

        adjust_mock = MagicMock(return_value={"ok": True})
        window = SimpleNamespace(
            current_yaml_path=yaml_path,
            bridge=SimpleNamespace(manage_boxes=adjust_mock),
            overview_panel=SimpleNamespace(refresh=MagicMock()),
            on_operation_completed=MagicMock(),
            operations_panel=SimpleNamespace(emit_external_operation_event=MagicMock()),
            show_status=MagicMock(),
        )
        flow = ManageBoxesFlow(window)

        with patch("app_gui.main_window_flows.QMessageBox.question") as confirm_mock:
            result = flow.handle_request(
                {"operation": "remove", "box": 99},
                from_ai=True,
                yaml_path_override=yaml_path,
            )

        assert result["ok"] is False
        assert result["error_code"] == "invalid_box"
        confirm_mock.assert_not_called()
        adjust_mock.assert_not_called()
        window.overview_panel.refresh.assert_not_called()
        window.on_operation_completed.assert_not_called()
        window.operations_panel.emit_external_operation_event.assert_not_called()
        window.show_status.assert_not_called()


def test_manage_boxes_flow_prepare_request_normalizes_remove_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 3\n"
                "inventory: []\n"
            ),
            encoding="utf-8",
        )

        window = SimpleNamespace(current_yaml_path=yaml_path)
        flow = ManageBoxesFlow(window)

        prepared = flow._prepare_request(
            {"operation": "remove_box", "box": 2, "renumber_mode": "compact"},
            yaml_path_override=yaml_path,
        )

        assert prepared["op"] == "remove"
        assert prepared["payload"]["operation"] == "remove"
        assert prepared["payload"]["box"] == 2
        assert prepared["suggested_mode"] == "renumber_contiguous"


def test_manage_boxes_flow_set_tag_executes_and_emits_notice():
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        Path(yaml_path).write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 2\n"
                "inventory: []\n"
            ),
            encoding="utf-8",
        )

        set_tag_mock = MagicMock(return_value={"ok": True, "result": {"box": 1, "tag_after": "virus"}})
        adjust_mock = MagicMock(return_value={"ok": True})
        window = SimpleNamespace(
            current_yaml_path=yaml_path,
            bridge=SimpleNamespace(manage_boxes=adjust_mock, set_box_tag=set_tag_mock),
            overview_panel=SimpleNamespace(refresh=MagicMock()),
            on_operation_completed=MagicMock(),
            operations_panel=SimpleNamespace(emit_external_operation_event=MagicMock()),
            show_status=MagicMock(),
        )
        flow = ManageBoxesFlow(window)

        result = flow.handle_request(
            {"operation": "set_tag", "box": 1, "tag": "virus"},
            from_ai=False,
            yaml_path_override=yaml_path,
        )

        assert result["ok"] is True
        set_tag_mock.assert_called_once_with(
            yaml_path=yaml_path,
            box=1,
            tag="virus",
            execution_mode="execute",
        )
        adjust_mock.assert_not_called()
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
                "custom_prompt": "abc",
            }
        },
        ai_panel=_FakeAIPanelState(),
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
    assert window.ai_panel.ai_custom_prompt == "abc"
    dataset_text = dataset_label.setText.call_args.args[0]
    assert dataset_text.endswith("tmp")
    assert "inventory.yaml" not in dataset_text
    assert stats_bar.setText.call_count >= 3


def test_window_state_flow_wire_plan_store_refreshes_overview_and_operations():
    plan_store = SimpleNamespace(_on_change=None)
    ops_panel = SimpleNamespace(refresh_plan_store_view=MagicMock())
    overview_panel = SimpleNamespace(
        bind_plan_store=MagicMock(),
        refresh_plan_store_view=MagicMock(),
    )
    window = SimpleNamespace(
        plan_store=plan_store,
        operations_panel=ops_panel,
        overview_panel=overview_panel,
    )
    flow = WindowStateFlow(window)

    with patch("PySide6.QtCore.QMetaObject.invokeMethod") as invoke_mock:
        flow.wire_plan_store()
        overview_panel.bind_plan_store.assert_called_once_with(plan_store)
        assert callable(plan_store._on_change)
        plan_store._on_change()

    called_pairs = [(call.args[0], call.args[1]) for call in invoke_mock.call_args_list]
    assert (ops_panel, "refresh_plan_store_view") in called_pairs
    assert (overview_panel, "refresh_plan_store_view") in called_pairs


def test_window_state_flow_close_event_busy_and_persist():
    busy_event = SimpleNamespace(ignore=MagicMock())
    busy_window = SimpleNamespace(ai_panel=_FakeAIPanelState(ai_run_inflight=True))
    busy_flow = WindowStateFlow(busy_window)
    with patch("app_gui.main_window_flows.QMessageBox.warning") as warn_mock:
        ok = busy_flow.handle_close_event(busy_event)
    assert ok is False
    busy_event.ignore.assert_called_once()
    warn_mock.assert_called_once()

    event = SimpleNamespace(ignore=MagicMock())
    window = SimpleNamespace(
        ai_panel=_FakeAIPanelState(),
        settings=SimpleNamespace(setValue=MagicMock()),
        saveGeometry=MagicMock(return_value=b"geo"),
        gui_config={},
        current_yaml_path="D:/tmp/current.yaml",
    )
    window.ai_panel.ai_provider.setText("deepseek")
    window.ai_panel.ai_model.setText("deepseek-chat")
    window.ai_panel.ai_steps.setValue(11)
    window.ai_panel.ai_thinking_enabled.setChecked(True)
    window.ai_panel.ai_custom_prompt = "prompt text"
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
    assert window.gui_config["ai"]["custom_prompt"] == "prompt text"
    save_mock.assert_called_once_with(window.gui_config)


def test_main_window_on_rename_dataset_switches_and_appends_audit():
    from app_gui.main import MainWindow

    old_yaml = "D:/inventories/old/inventory.yaml"
    new_yaml = "D:/inventories/new/inventory.yaml"
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = old_yaml
    window._dataset_lifecycle = SimpleNamespace(
        rename_dataset=MagicMock(
            return_value=SimpleNamespace(target_path=new_yaml, audit_error=None)
        )
    )
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=new_yaml))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    result = MainWindow.on_rename_dataset(window, old_yaml, "new")

    assert result == new_yaml
    window._dataset_lifecycle.rename_dataset.assert_called_once_with(
        current_yaml_path=old_yaml,
        new_dataset_name="new",
    )
    window._dataset_session.switch_to.assert_called_once_with(new_yaml, reason="dataset_rename")
    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=new_yaml)
    status_message.assert_called_once()
    assert status_message.call_args.args[1] == 4000


def test_main_window_on_rename_dataset_keeps_success_when_audit_append_fails():
    from app_gui.main import MainWindow

    old_yaml = "D:/inventories/old/inventory.yaml"
    new_yaml = "D:/inventories/new/inventory.yaml"
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = old_yaml
    window._dataset_lifecycle = SimpleNamespace(
        rename_dataset=MagicMock(
            return_value=SimpleNamespace(target_path=new_yaml, audit_error="audit failed")
        )
    )
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=new_yaml))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    with patch("app_gui.main.t", side_effect=lambda key, **kwargs: key) as t_mock:
        result = MainWindow.on_rename_dataset(window, old_yaml, "new")

    assert result == new_yaml
    window._dataset_lifecycle.rename_dataset.assert_called_once_with(
        current_yaml_path=old_yaml,
        new_dataset_name="new",
    )
    window._dataset_session.switch_to.assert_called_once_with(new_yaml, reason="dataset_rename")
    status_message.assert_called_once()
    assert status_message.call_args.args[1] == 6000
    assert status_message.call_args.args[0] == "settings.renameDatasetSuccessWithAuditWarning"
    t_mock.assert_called_once_with(
        "settings.renameDatasetSuccessWithAuditWarning",
        path=new_yaml,
        error="audit failed",
    )


def test_main_window_on_delete_dataset_switches_and_appends_audit():
    from app_gui.main import MainWindow

    old_yaml = "D:/inventories/old/inventory.yaml"
    switched_yaml = "D:/inventories/new/inventory.yaml"
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = old_yaml
    window._dataset_lifecycle = SimpleNamespace(
        delete_dataset=MagicMock(
            return_value=SimpleNamespace(
                target_path=switched_yaml,
                audit_error=None,
                deleted_yaml_path=old_yaml,
                fallback_created=False,
            )
        )
    )
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=switched_yaml))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    result = MainWindow.on_delete_dataset(window, old_yaml)

    assert result == switched_yaml
    window._dataset_lifecycle.delete_dataset.assert_called_once_with(
        current_yaml_path=old_yaml,
    )
    window._dataset_session.switch_to.assert_called_once_with(switched_yaml, reason="dataset_delete")
    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=switched_yaml)
    status_message.assert_called_once()
    assert status_message.call_args.args[1] == 4000


def test_main_window_on_delete_dataset_keeps_success_when_audit_append_fails():
    from app_gui.main import MainWindow

    old_yaml = "D:/inventories/old/inventory.yaml"
    switched_yaml = "D:/inventories/new/inventory.yaml"
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = old_yaml
    window._dataset_lifecycle = SimpleNamespace(
        delete_dataset=MagicMock(
            return_value=SimpleNamespace(
                target_path=switched_yaml,
                audit_error="audit failed",
                deleted_yaml_path=old_yaml,
                fallback_created=False,
            )
        )
    )
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=switched_yaml))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    with patch("app_gui.main.t", side_effect=lambda key, **kwargs: key) as t_mock:
        result = MainWindow.on_delete_dataset(window, old_yaml)

    assert result == switched_yaml
    window._dataset_lifecycle.delete_dataset.assert_called_once_with(
        current_yaml_path=old_yaml,
    )
    window._dataset_session.switch_to.assert_called_once_with(switched_yaml, reason="dataset_delete")
    status_message.assert_called_once()
    assert status_message.call_args.args[1] == 6000
    assert status_message.call_args.args[0] == "settings.deleteDatasetSuccessWithAuditWarning"
    t_mock.assert_called_once_with(
        "settings.deleteDatasetSuccessWithAuditWarning",
        path=switched_yaml,
        error="audit failed",
    )


def test_main_window_on_delete_dataset_creates_fallback_when_empty():
    from app_gui.main import MainWindow

    old_yaml = "D:/inventories/old/inventory.yaml"
    fallback_yaml = "D:/inventories/inventory/inventory.yaml"
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = old_yaml
    window._dataset_lifecycle = SimpleNamespace(
        delete_dataset=MagicMock(
            return_value=SimpleNamespace(
                target_path=fallback_yaml,
                audit_error=None,
                deleted_yaml_path=old_yaml,
                fallback_created=True,
            )
        )
    )
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=fallback_yaml))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    result = MainWindow.on_delete_dataset(window, old_yaml)

    assert result == fallback_yaml
    window._dataset_lifecycle.delete_dataset.assert_called_once_with(
        current_yaml_path=old_yaml,
    )
    window._dataset_session.switch_to.assert_called_once_with(fallback_yaml, reason="dataset_delete")
    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=fallback_yaml)
    status_message.assert_called_once()


def test_main_window_refresh_home_dataset_choices_selects_current_path():
    from app_gui.main import MainWindow

    path_a = os.path.abspath("D:/inventories/a/inventory.yaml")
    path_b = os.path.abspath("D:/inventories/b/inventory.yaml")
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = path_b
    window.home_dataset_switch_combo = _FakeComboBox()

    with patch(
        "app_gui.main.list_managed_datasets",
        return_value=[
            {"name": "dataset-a", "yaml_path": path_a},
            {"name": "dataset-b", "yaml_path": path_b},
        ],
    ):
        MainWindow._refresh_home_dataset_choices(window)

    assert window.home_dataset_switch_combo.enabled is True
    assert window.home_dataset_switch_combo.current_index == 1
    assert window.home_dataset_switch_combo.currentData() == path_b
    assert window.home_dataset_switch_combo.tooltip == path_b


def test_main_window_home_dataset_switch_uses_session_controller():
    from app_gui.main import MainWindow

    target_path = os.path.abspath("D:/inventories/next/inventory.yaml")
    switched_path = os.path.abspath("D:/inventories/switched/inventory.yaml")
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = os.path.abspath("D:/inventories/current/inventory.yaml")
    window.home_dataset_switch_combo = SimpleNamespace(currentData=MagicMock(return_value=target_path))
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(return_value=switched_path))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=MagicMock()))

    MainWindow._on_home_dataset_switch_changed(window)

    window._dataset_session.switch_to.assert_called_once_with(target_path, reason="manual_switch")
    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=switched_path)


def test_main_window_home_dataset_switch_failure_rolls_back_selection():
    from app_gui.main import MainWindow

    current_path = os.path.abspath("D:/inventories/current/inventory.yaml")
    target_path = os.path.abspath("D:/inventories/bad/inventory.yaml")
    status_message = MagicMock()
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = current_path
    window.home_dataset_switch_combo = SimpleNamespace(currentData=MagicMock(return_value=target_path))
    window._dataset_session = SimpleNamespace(switch_to=MagicMock(side_effect=RuntimeError("boom")))
    window._refresh_home_dataset_choices = MagicMock()
    window.statusBar = MagicMock(return_value=SimpleNamespace(showMessage=status_message))

    MainWindow._on_home_dataset_switch_changed(window)

    window._dataset_session.switch_to.assert_called_once_with(target_path, reason="manual_switch")
    status_message.assert_called_once()
    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=current_path)


def test_main_window_update_dataset_label_also_refreshes_home_switcher():
    from app_gui.main import MainWindow

    current_path = os.path.abspath("D:/inventories/current/inventory.yaml")
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = current_path
    window._refresh_home_dataset_choices = MagicMock()

    MainWindow._update_dataset_label(window)

    window._refresh_home_dataset_choices.assert_called_once_with(selected_yaml=current_path)


def test_main_window_dataset_switched_event_refreshes_and_emits_notice():
    from app_gui.main import MainWindow

    old_path = os.path.abspath("D:/inventories/old/inventory.yaml")
    new_path = os.path.abspath("D:/inventories/new/inventory.yaml")
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = new_path
    window.operations_panel = SimpleNamespace(reset_for_dataset_switch=MagicMock())
    window.overview_panel = SimpleNamespace(refresh=MagicMock())
    window._update_dataset_label = MagicMock()
    window._emit_system_notice = MagicMock()

    MainWindow._on_dataset_switched_event(
        window,
        SimpleNamespace(old_path=old_path, new_path=new_path, reason="manual_switch"),
    )

    window.operations_panel.reset_for_dataset_switch.assert_called_once_with()
    window._update_dataset_label.assert_called_once_with()
    window.overview_panel.refresh.assert_called_once_with()
    window._emit_system_notice.assert_called_once()
    notice_kwargs = window._emit_system_notice.call_args.kwargs
    assert notice_kwargs["code"] == "dataset.switch"
    assert notice_kwargs["source"] == "main_window"
    assert notice_kwargs["data"]["reason"] == "manual_switch"
    assert notice_kwargs["data"]["from_path"] == old_path
    assert notice_kwargs["data"]["to_path"] == new_path


def test_main_window_dataset_switched_event_tolerates_missing_optional_hooks():
    from app_gui.main import MainWindow

    new_path = os.path.abspath("D:/inventories/new/inventory.yaml")
    window = MainWindow.__new__(MainWindow)
    window.current_yaml_path = new_path
    window.operations_panel = SimpleNamespace()
    window.overview_panel = SimpleNamespace()
    window._emit_system_notice = MagicMock()

    MainWindow._on_dataset_switched_event(
        window,
        SimpleNamespace(old_path="", new_path="", reason="import_success"),
    )

    window._emit_system_notice.assert_called_once()
    notice_kwargs = window._emit_system_notice.call_args.kwargs
    assert notice_kwargs["data"]["reason"] == "import_success"
    assert notice_kwargs["data"]["to_path"] == new_path


@pytest.mark.parametrize(
    "success,operation,source",
    [
        (True, "plan_execute", "operations_panel"),
        (False, "ai_operation", "ai_panel"),
    ],
)
def test_main_window_operation_completed_signal_routes_through_use_case(success, operation, source):
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._plan_execution_use_case = SimpleNamespace(report_operation_completed=MagicMock())

    MainWindow._dispatch_operation_completed(
        window,
        success,
        operation=operation,
        source=source,
    )

    window._plan_execution_use_case.report_operation_completed.assert_called_once_with(
        success=success,
        operation=operation,
        source=source,
    )


def test_main_window_operation_completed_dispatch_falls_back_to_state_flow():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._state_flow = SimpleNamespace(on_operation_completed=MagicMock())

    MainWindow._dispatch_operation_completed(
        window,
        True,
        operation="plan_execute",
        source="operations_panel",
    )

    window._state_flow.on_operation_completed.assert_called_once_with(True)


def test_main_window_ai_migration_mode_signal_routes_through_use_case():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._migration_mode_use_case = SimpleNamespace(set_mode=MagicMock())

    MainWindow._request_migration_mode_change(window, True, reason="ai_panel")

    window._migration_mode_use_case.set_mode.assert_called_once_with(
        enabled=True,
        reason="ai_panel",
    )


def test_main_window_migration_mode_dispatch_falls_back_to_existing_handler():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._apply_migration_mode_enabled = MagicMock()

    MainWindow._request_migration_mode_change(window, False, reason="ai_panel")

    window._apply_migration_mode_enabled.assert_called_once_with(False)


def test_main_window_migration_mode_change_forwards_to_operations_panel():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    operations_panel = SimpleNamespace(set_migration_mode_enabled=MagicMock())
    migration_mode_badge = SimpleNamespace(setVisible=MagicMock())
    migration_status_indicator = SimpleNamespace(setVisible=MagicMock())
    window.operations_panel = operations_panel
    window.migration_mode_badge = migration_mode_badge
    window._migration_status_indicator = migration_status_indicator

    MainWindow._apply_migration_mode_enabled(window, True)
    MainWindow._apply_migration_mode_enabled(window, False)

    assert operations_panel.set_migration_mode_enabled.call_args_list[0].args == (True,)
    assert operations_panel.set_migration_mode_enabled.call_args_list[1].args == (False,)
    assert migration_mode_badge.setVisible.call_args_list[0].args == (True,)
    assert migration_mode_badge.setVisible.call_args_list[1].args == (False,)
    assert migration_status_indicator.setVisible.call_args_list[0].args == (True,)
    assert migration_status_indicator.setVisible.call_args_list[1].args == (False,)


def test_main_window_repeated_migration_enable_is_noop():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window._migration_mode_enabled = False
    operations_panel = SimpleNamespace(set_migration_mode_enabled=MagicMock())
    migration_mode_badge = SimpleNamespace(setVisible=MagicMock())
    migration_status_indicator = SimpleNamespace(setVisible=MagicMock())
    window.operations_panel = operations_panel
    window.migration_mode_badge = migration_mode_badge
    window._migration_status_indicator = migration_status_indicator

    MainWindow._apply_migration_mode_enabled(window, True)
    MainWindow._apply_migration_mode_enabled(window, True)

    operations_panel.set_migration_mode_enabled.assert_called_once_with(True)
    migration_mode_badge.setVisible.assert_called_once_with(True)
    migration_status_indicator.setVisible.assert_called_once_with(True)


def test_main_window_migration_mode_change_ignores_missing_operations_panel():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.operations_panel = SimpleNamespace()
    MainWindow._apply_migration_mode_enabled(window, True)


def test_main_window_import_handoff_only_prefills_ai_prompt():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.ai_panel = SimpleNamespace(prepare_import_migration=MagicMock())
    window._request_migration_mode_change = MagicMock()
    window._apply_migration_mode_enabled = MagicMock()

    MainWindow._handoff_import_journey_to_ai(
        window,
        SimpleNamespace(ai_prompt="run staged migration"),
    )

    window.ai_panel.prepare_import_migration.assert_called_once_with(
        "run staged migration",
        focus=True,
    )
    window._request_migration_mode_change.assert_not_called()
    window._apply_migration_mode_enabled.assert_not_called()


def test_main_window_migration_notice_skips_when_suppressed():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.gui_config = {"migration_mode_notice_suppressed": True}
    window._show_nonblocking_dialog = MagicMock()

    with patch("app_gui.main.QMessageBox", _FakeMessageBox), patch(
        "app_gui.main.QCheckBox",
        _FakeCheckBoxWidget,
    ), patch("app_gui.main.save_gui_config") as save_mock:
        MainWindow._show_migration_mode_entry_notice(window)

    window._show_nonblocking_dialog.assert_not_called()
    save_mock.assert_not_called()


def test_main_window_migration_notice_persists_opt_out_when_checked():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.gui_config = {}

    def _show_dialog_and_confirm(msg_box):
        checkbox = msg_box.checkBox()
        assert checkbox is not None
        checkbox.setChecked(True)
        msg_box.finished.emit(0)

    window._show_nonblocking_dialog = MagicMock(side_effect=_show_dialog_and_confirm)

    with patch("app_gui.main.QMessageBox", _FakeMessageBox), patch(
        "app_gui.main.QCheckBox",
        _FakeCheckBoxWidget,
    ), patch("app_gui.main.save_gui_config") as save_mock:
        MainWindow._show_migration_mode_entry_notice(window)

    assert window.gui_config.get("migration_mode_notice_suppressed") is True
    save_mock.assert_called_once_with(window.gui_config)


def test_main_window_migration_notice_does_not_persist_when_unchecked():
    from app_gui.main import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.gui_config = {}

    def _show_dialog_without_opt_out(msg_box):
        msg_box.finished.emit(0)

    window._show_nonblocking_dialog = MagicMock(side_effect=_show_dialog_without_opt_out)

    with patch("app_gui.main.QMessageBox", _FakeMessageBox), patch(
        "app_gui.main.QCheckBox",
        _FakeCheckBoxWidget,
    ), patch("app_gui.main.save_gui_config") as save_mock:
        MainWindow._show_migration_mode_entry_notice(window)

    assert "migration_mode_notice_suppressed" not in window.gui_config
    save_mock.assert_not_called()
