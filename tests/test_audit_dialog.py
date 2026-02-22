import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import QApplication, QTableWidgetItem, QWidget

    from app_gui.ui import audit_dialog as audit_dialog_module
    from app_gui.ui.audit_dialog import AuditLogDialog
    from lib.yaml_ops import get_audit_log_paths, write_yaml

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    Qt = None
    QApplication = None
    QTableWidgetItem = None
    QWidget = None
    AuditLogDialog = None
    get_audit_log_paths = None
    write_yaml = None
    audit_dialog_module = None
    PYSIDE_AVAILABLE = False


class _Bridge:
    pass


class _TimelineBridge:
    def __init__(self, events):
        self._events = list(events or [])

    def list_audit_timeline(
        self,
        yaml_path,
        limit=50,
        offset=0,
        action_filter=None,
        status_filter=None,
        start_date=None,
        end_date=None,
    ):
        _ = (yaml_path, limit, offset, action_filter, status_filter, start_date, end_date)
        return {
            "ok": True,
            "result": {
                "items": list(self._events),
                "total": len(self._events),
                "limit": limit,
                "offset": offset,
            },
        }


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class AuditDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_dialog(self, yaml_path):
        parent = QWidget()
        dialog = AuditLogDialog(parent=parent, yaml_path_getter=lambda: str(yaml_path), bridge=_Bridge())
        dialog._test_parent_ref = parent
        return dialog

    def _new_dialog_with_bridge(self, yaml_path, bridge):
        parent = QWidget()
        dialog = AuditLogDialog(parent=parent, yaml_path_getter=lambda: str(yaml_path), bridge=bridge)
        dialog._test_parent_ref = parent
        return dialog

    def test_on_load_audit_reads_canonical_log_only(self):
        with tempfile.TemporaryDirectory(prefix="ln2_audit_dialog_merge_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                {
                    "meta": {"box_layout": {"rows": 9, "cols": 9}},
                    "inventory": [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "seed",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2025-01-01",
                        }
                    ],
                },
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            dialog = self._new_dialog(yaml_path)
            dialog.audit_start_date.setDate(QDate(2000, 1, 1))
            dialog.audit_end_date.setDate(QDate(2099, 12, 31))
            dialog.on_load_audit()

            actions = [dialog.audit_table.item(row, 1).text() for row in range(dialog.audit_table.rowCount())]
            self.assertIn("seed", actions)

    def test_on_load_audit_shows_newest_events_first(self):
        with tempfile.TemporaryDirectory(prefix="ln2_audit_dialog_sort_") as temp_dir:
            yaml_path = Path(temp_dir) / "sort_case.yaml"
            yaml_path.write_text(
                "\n".join(
                    [
                        "meta:",
                        "  inventory_instance_id: sort-test",
                        "  box_layout:",
                        "    rows: 9",
                        "    cols: 9",
                        "inventory: []",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            audit_path = Path(get_audit_log_paths(str(yaml_path))[0])
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            older = {
                "timestamp": "2026-02-20T09:00:00",
                "action": "takeout",
                "status": "success",
            }
            newer = {
                "timestamp": "2026-02-21T09:00:00",
                "action": "move",
                "status": "success",
            }
            audit_path.write_text(
                "\n".join(
                    [
                        json.dumps(older, ensure_ascii=False),
                        json.dumps(newer, ensure_ascii=False),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            dialog = self._new_dialog(yaml_path)
            dialog.audit_start_date.setDate(QDate(2000, 1, 1))
            dialog.audit_end_date.setDate(QDate(2099, 12, 31))
            dialog.on_load_audit()

            self.assertGreaterEqual(dialog.audit_table.rowCount(), 2)
            self.assertEqual("2026-02-21T09:00:00", dialog.audit_table.item(0, 0).text())
            self.assertEqual("move", dialog.audit_table.item(0, 1).text())

    def test_on_load_audit_prefers_audit_seq_over_timestamp(self):
        bridge = _TimelineBridge(
            [
                {
                    "timestamp": "2026-02-21T09:00:00",
                    "action": "higher_ts_lower_seq",
                    "status": "success",
                    "audit_seq": 10,
                },
                {
                    "timestamp": "2026-02-20T09:00:00",
                    "action": "lower_ts_higher_seq",
                    "status": "success",
                    "audit_seq": 11,
                },
            ]
        )
        dialog = self._new_dialog_with_bridge("D:/tmp/inventory.yaml", bridge)
        dialog.audit_start_date.setDate(QDate(2000, 1, 1))
        dialog.audit_end_date.setDate(QDate(2099, 12, 31))
        dialog.on_load_audit()

        self.assertGreaterEqual(dialog.audit_table.rowCount(), 2)
        self.assertEqual("lower_ts_higher_seq", dialog.audit_table.item(0, 1).text())
        self.assertEqual("higher_ts_lower_seq", dialog.audit_table.item(1, 1).text())

    def test_click_row_uses_source_index_after_sort(self):
        dialog = self._new_dialog("D:/tmp/inventory.yaml")
        dialog._audit_events = [
            {
                "timestamp": "2026-02-10T09:00:00",
                "action": "older-event",
                "status": "success",
            },
            {
                "timestamp": "2026-02-20T09:00:00",
                "action": "newer-event",
                "status": "success",
            },
        ]
        dialog._setup_table(
            dialog.audit_table,
            ["timestamp", "action", "status", "details"],
            sortable=True,
        )
        for idx, event in enumerate(dialog._audit_events):
            dialog.audit_table.insertRow(idx)
            ts_item = QTableWidgetItem(event.get("timestamp", ""))
            ts_item.setData(Qt.UserRole, idx)
            dialog.audit_table.setItem(idx, 0, ts_item)
            dialog.audit_table.setItem(idx, 1, QTableWidgetItem(event.get("action", "")))
            dialog.audit_table.setItem(idx, 2, QTableWidgetItem(event.get("status", "")))
            dialog.audit_table.setItem(idx, 3, QTableWidgetItem(""))

        dialog.audit_table.sortItems(0, Qt.DescendingOrder)
        displayed_action = dialog.audit_table.item(0, 1).text()
        dialog._on_audit_row_clicked(0, 0)

        self.assertIn(displayed_action, dialog.event_detail.text())

    def test_event_detail_escapes_html_in_details(self):
        dialog = self._new_dialog("D:/tmp/inventory.yaml")
        dialog._audit_events = [
            {
                "timestamp": "2026-02-20T09:00:00",
                "action": "takeout",
                "status": "success",
                "details": {"note": "<script>alert(1)</script>"},
            }
        ]
        dialog._setup_table(
            dialog.audit_table,
            ["timestamp", "action", "status", "details"],
            sortable=True,
        )
        dialog.audit_table.insertRow(0)
        ts_item = QTableWidgetItem("2026-02-20T09:00:00")
        ts_item.setData(Qt.UserRole, 0)
        dialog.audit_table.setItem(0, 0, ts_item)
        dialog.audit_table.setItem(0, 1, QTableWidgetItem("takeout"))
        dialog.audit_table.setItem(0, 2, QTableWidgetItem("success"))
        dialog.audit_table.setItem(0, 3, QTableWidgetItem(""))

        dialog._on_audit_row_clicked(0, 0)
        detail_html = dialog.event_detail.text()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", detail_html)
        self.assertNotIn("<script>alert(1)</script>", detail_html)

    def test_backup_path_rows_bold_with_subtle_bg_and_rollback_button_requires_backup_path(self):
        events = [
            {
                "timestamp": "2026-02-20T09:00:00",
                "action": "takeout",
                "status": "success",
                "details": {},
            },
            {
                "timestamp": "2026-02-21T09:00:00",
                "action": "backup",
                "status": "success",
                "backup_path": "/tmp/eligible.bak",
                "audit_seq": 12,
                "details": {},
            },
        ]
        dialog = self._new_dialog_with_bridge("D:/tmp/inventory.yaml", _TimelineBridge(events))
        dialog.audit_start_date.setDate(QDate(2000, 1, 1))
        dialog.audit_end_date.setDate(QDate(2099, 12, 31))
        dialog.on_load_audit()

        self.assertFalse(dialog.audit_rollback_selected_btn.isEnabled())
        self.assertEqual(2, dialog.audit_table.rowCount())

        backup_row = None
        non_backup_row = None
        for row in range(dialog.audit_table.rowCount()):
            action = dialog.audit_table.item(row, 1).text()
            if action == "backup":
                backup_row = row
            else:
                non_backup_row = row

        self.assertIsNotNone(backup_row)
        self.assertIsNotNone(non_backup_row)

        self.assertTrue(dialog.audit_table.item(backup_row, 0).font().bold())
        self.assertFalse(dialog.audit_table.item(non_backup_row, 0).font().bold())
        self.assertTrue(
            bool(dialog.audit_table.item(backup_row, 0).data(audit_dialog_module._AUDIT_BACKUP_ROW_ROLE))
        )
        self.assertFalse(
            bool(dialog.audit_table.item(non_backup_row, 0).data(audit_dialog_module._AUDIT_BACKUP_ROW_ROLE))
        )
        self.assertIsInstance(
            dialog.audit_table.itemDelegate(),
            audit_dialog_module._AuditBackupTintDelegate,
        )

        dialog.audit_table.clearSelection()
        dialog.audit_table.selectRow(non_backup_row)
        self.assertFalse(dialog.audit_rollback_selected_btn.isEnabled())

        dialog.audit_table.clearSelection()
        dialog.audit_table.selectRow(backup_row)
        self.assertTrue(dialog.audit_rollback_selected_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
