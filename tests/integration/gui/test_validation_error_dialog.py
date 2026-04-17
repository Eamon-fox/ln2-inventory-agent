"""
Module: test_validation_error_dialog
Layer: integration/gui
Covers: app_gui/ui/dialogs/validation_error_dialog.py,
        app_gui/ui/operations_panel.py,
        app_gui/ui/operations_panel_execution.py

锁定结构化校验错误在 GUI 层的展示契约：当 plan 执行失败的 info 字典带
``errors_detail`` 时，OperationsPanel 必须：

- 记录到 ``_last_validation_errors_detail`` / ``_last_validation_summary``；
- 让 ``view_validation_details_btn`` 可见；
- 点击按钮能构造 ``ValidationErrorDialog`` 并以 table 展示每一条结构化详情。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication
    from app_gui.ui.operations_panel import OperationsPanel
    from app_gui.ui.operations_panel_execution import _show_plan_result
    from app_gui.ui.dialogs.validation_error_dialog import ValidationErrorDialog

    PYSIDE_AVAILABLE = True
except Exception:  # pragma: no cover - exercised in non-Qt envs
    QApplication = None
    OperationsPanel = None
    _show_plan_result = None
    ValidationErrorDialog = None
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class ValidationErrorDialogGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/x.yaml")

    def _fail_result(self, errors_detail):
        return [
            (
                "FAIL",
                {"action": "edit", "record_id": 1},
                {
                    "ok": False,
                    "error_code": "integrity_validation_failed",
                    "message": "Write blocked: integrity validation failed",
                    "errors": ["id=1 box=out of range"],
                    "errors_detail": errors_detail,
                },
            )
        ]

    def test_fail_with_errors_detail_populates_panel_state(self):
        panel = self._make_panel()
        details = [
            {
                "record_id": 1,
                "record_index": 0,
                "box": 99,
                "field": "box",
                "value": 99,
                "rule": "box_out_of_range",
                "expected": [1, 2, 3, 4, 5],
                "message": "box 99 out of range",
            }
        ]
        _show_plan_result(
            panel,
            self._fail_result(details),
            report={"ok": False, "stats": {}},
            rollback_info=None,
            execution_stats={
                "ok_count": 0,
                "fail_count": 1,
                "applied_count": 0,
                "total_count": 1,
            },
        )
        self.assertEqual(panel._last_validation_errors_detail, details)
        self.assertTrue(panel._last_validation_summary)
        self.assertFalse(panel.view_validation_details_btn.isHidden())
        self.assertTrue(panel.view_validation_details_btn.isEnabled())

    def test_fail_without_errors_detail_hides_button(self):
        panel = self._make_panel()
        _show_plan_result(
            panel,
            [
                (
                    "FAIL",
                    {"action": "edit", "record_id": 1},
                    {"ok": False, "error_code": "other", "message": "nope"},
                )
            ],
            report={"ok": False, "stats": {}},
            rollback_info=None,
            execution_stats={
                "ok_count": 0,
                "fail_count": 1,
                "applied_count": 0,
                "total_count": 1,
            },
        )
        self.assertIsNone(panel._last_validation_errors_detail)
        self.assertTrue(panel.view_validation_details_btn.isHidden())

    def test_success_clears_previous_validation_state(self):
        panel = self._make_panel()
        panel._last_validation_errors_detail = [{"rule": "stale", "message": "old"}]
        panel._last_validation_summary = "old"
        _show_plan_result(
            panel,
            [("OK", {"action": "edit", "record_id": 1}, {"ok": True})],
            report={"ok": True, "stats": {}},
            rollback_info=None,
            execution_stats={
                "ok_count": 1,
                "fail_count": 0,
                "applied_count": 1,
                "total_count": 1,
            },
        )
        self.assertIsNone(panel._last_validation_errors_detail)
        self.assertEqual(panel._last_validation_summary, "")
        self.assertTrue(panel.view_validation_details_btn.isHidden())

    def test_dialog_renders_rows_from_errors_detail(self):
        details = [
            {
                "record_id": 7,
                "box": 1,
                "position": 3,
                "field": "position",
                "value": 3,
                "rule": "position_conflict",
                "expected": None,
                "message": "position conflict at box 1 pos 3",
            },
            {
                "record_id": 8,
                "box": 2,
                "field": "cell_line",
                "value": "BAD",
                "rule": "invalid_option",
                "expected": ["K562", "HeLa"],
                "message": "invalid option",
            },
        ]
        dialog = ValidationErrorDialog(
            parent=None,
            errors_detail=details,
            summary_message="Write blocked",
        )
        try:
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.columnCount(), 6)
            row0 = [
                dialog.table.item(0, col).text() for col in range(dialog.table.columnCount())
            ]
            self.assertIn("7", row0[0])
            self.assertIn("1", row0[1])
            self.assertIn("position", row0[2])
            self.assertIn("position_conflict", row0[4])
            row1 = [
                dialog.table.item(1, col).text() for col in range(dialog.table.columnCount())
            ]
            self.assertIn("invalid_option", row1[4])
            self.assertIn("K562", row1[5])
        finally:
            dialog.deleteLater()

    def test_dialog_skipped_when_no_details(self):
        from app_gui.ui.dialogs.validation_error_dialog import show_validation_error_dialog

        show_validation_error_dialog(None, errors_detail=[])
        show_validation_error_dialog(None, errors_detail=None)


if __name__ == "__main__":
    unittest.main()
