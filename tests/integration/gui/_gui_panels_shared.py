"""Shared fixtures and helpers for split GUI panel integration tests."""

"""
Module: test_gui_panels
Layer: integration/gui
Covers: app_gui/ui/overview_panel.py, app_gui/ui/operations_panel.py, app_gui/ui/ai_panel.py

概览、操作、表格面板行为测试
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path
from tests.managed_paths import ManagedPathTestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QDate, Qt, QEvent, QPointF
    from PySide6.QtGui import QValidator, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QMessageBox,
        QCompleter,
        QPushButton,
        QLineEdit,
        QPlainTextEdit,
    )

    from app_gui.ui.ai_panel import AIPanel
    from app_gui.ui.overview_panel import OverviewPanel, TABLE_ROW_TINT_ROLE
    from app_gui.ui.operations_panel import OperationsPanel
    from app_gui.ui.utils import cell_color
    from app_gui.error_localizer import localize_error_payload
    from app_gui.i18n import get_language, set_language, t, tr

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    Qt = None
    QEvent = None
    QPointF = None
    QValidator = None
    QMouseEvent = None
    QTest = None
    QApplication = None
    QMessageBox = None
    QCompleter = None
    QPushButton = None
    QLineEdit = None
    QPlainTextEdit = None
    AIPanel = None
    OverviewPanel = None
    TABLE_ROW_TINT_ROLE = None
    OperationsPanel = None
    cell_color = None
    localize_error_payload = None
    get_language = None
    set_language = None
    t = None
    tr = None
    PYSIDE_AVAILABLE = False


def _validate_stage_request_without_preflight(*args, **kwargs):
    from app_gui.plan_gate import validate_stage_request as _validate_stage_request

    params = dict(kwargs)
    params["run_preflight"] = False
    return _validate_stage_request(*args, **params)


class _NoStagePreflightMixin:
    """Disable staging preflight so UI behavior tests stay data-shape focused."""

    def setUp(self):
        super().setUp()
        self._patch_stage_gate_ui = patch(
            "app_gui.ui.operations_panel_plan_store.validate_stage_request",
            side_effect=_validate_stage_request_without_preflight,
        )
        self._patch_stage_gate_ui.start()
        self.addCleanup(self._patch_stage_gate_ui.stop)

        self._patch_stage_gate_agent = patch(
            "agent.tool_runner_staging.validate_stage_request",
            side_effect=_validate_stage_request_without_preflight,
        )
        self._patch_stage_gate_agent.start()
        self.addCleanup(self._patch_stage_gate_agent.stop)


class _FakeChatNoMarkdown:
    def __init__(self):
        self.calls = []

    def append(self, text):
        self.calls.append(("append", text))

    def insertPlainText(self, text):
        self.calls.append(("insertPlainText", text))


class _FakeChatWithMarkdown:
    def __init__(self):
        self.calls = []

    def append(self, text):
        self.calls.append(("append", text))

    def insertMarkdown(self, text):
        self.calls.append(("insertMarkdown", text))


class _FakeOperationsBridge:
    def __init__(self):
        self.last_add_payload = None
        self.last_export_payload = None
        self.last_record_payload = None
        self.last_batch_payload = None
        self.add_response = {"ok": True, "result": {"new_id": 99}}
        self.export_response = {
            "ok": True,
            "result": {
                "path": "/tmp/export.csv",
                "count": 1,
                "columns": ["id", "cell_line"],
            },
        }

    def add_entry(self, yaml_path, **payload):
        self.last_add_payload = {"yaml_path": yaml_path, **payload}
        return self.add_response

    def export_inventory_csv(self, yaml_path, output_path):
        self.last_export_payload = {"yaml_path": yaml_path, "output_path": output_path}
        return self.export_response

    def record_takeout(self, yaml_path, **payload):
        self.last_record_payload = {"yaml_path": yaml_path, **payload}
        return {"ok": True, "preview": payload, "result": {"record_id": payload.get("record_id")}}

    def batch_takeout(self, yaml_path, **payload):
        self.last_batch_payload = {"yaml_path": yaml_path, **payload}
        entries = payload.get("entries") or []
        record_ids = []
        for entry in entries:
            if isinstance(entry, dict):
                record_ids.append(entry.get("record_id"))
            elif isinstance(entry, (list, tuple)) and entry:
                record_ids.append(entry[0])
        return {
            "ok": True,
            "preview": {"count": len(entries), "operations": []},
            "result": {"count": len(entries), "record_ids": record_ids},
        }

    def batch_move(self, yaml_path, **payload):
        return self.batch_takeout(yaml_path, **payload)

    def takeout(self, yaml_path, **payload):
        return self.batch_takeout(yaml_path, **payload)

    def move(self, yaml_path, **payload):
        return self.batch_move(yaml_path, **payload)

    def generate_stats(self, yaml_path, box=None, include_inactive=False):
        return {"ok": True, "result": {"total_records": 0, "total_slots": 405, "occupied_slots": 0, "boxes": {}}}

    def search_records(self, yaml_path, **kwargs):
        return {"ok": True, "result": {"records": [], "count": 0}}

    def collect_timeline(self, yaml_path, **kwargs):
        return {"ok": True, "result": {"events": []}}


def _make_move_item(record_id, position, to_position, to_box=None, label="test"):
    """Helper to create a valid move plan item."""
    item = {
        "action": "move",
        "box": 1,
        "position": position,
        "to_position": to_position,
        "record_id": record_id,
        "source": "ai",
        "payload": {
            "record_id": record_id,
            "position": position,
            "to_position": to_position,
            "date_str": "2026-02-10",
            "action": "Move",
            "note": None,
        },
    }
    if to_box is not None:
        item["to_box"] = to_box
        item["payload"]["to_box"] = to_box
    return item


def _make_takeout_item(record_id, position, box=1, label="test"):
    """Helper to create a valid takeout plan item."""
    return {
        "action": "takeout",
        "box": box,
        "position": position,
        "record_id": record_id,
        "source": "ai",
        "payload": {
            "record_id": record_id,
            "position": position,
            "date_str": "2026-02-10",
            "action": "Takeout",
            "note": None,
        },
    }


def _make_add_item(box, position, cell_line="K562", short_name="add-test"):
    """Helper to create a valid add plan item."""
    return {
        "action": "add",
        "box": box,
        "position": position,
        "record_id": None,
        "source": "ai",
        "payload": {
            "box": box,
            "positions": [position],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": cell_line,
                "short_name": short_name,
            },
        },
    }


def _make_edit_item(record_id, position, fields, box=1):
    """Helper to create a valid edit plan item."""
    return {
        "action": "edit",
        "box": box,
        "position": position,
        "record_id": record_id,
        "source": "ai",
        "payload": {
            "record_id": record_id,
            "fields": dict(fields),
        },
    }




@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsBaseCase(_NoStagePreflightMixin, ManagedPathTestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_operations_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    def _new_ai_panel(self):
        return AIPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    def _new_overview_panel(self):
        return OverviewPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    @staticmethod
    def _make_table_item(text):
        from PySide6.QtWidgets import QTableWidgetItem

        return QTableWidgetItem(text)


__all__ = [name for name in globals() if not name.startswith("__")]
