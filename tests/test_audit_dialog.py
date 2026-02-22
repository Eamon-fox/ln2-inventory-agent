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
    PYSIDE_AVAILABLE = False


class _Bridge:
    def list_backups(self, _yaml_path):
        return {"ok": True, "result": {"count": 0, "backups": []}}


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

    def test_on_load_audit_merges_instance_and_legacy_shared_logs(self):
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

            candidate_paths = get_audit_log_paths(str(yaml_path))
            legacy_shared_path = Path(candidate_paths[-1])
            legacy_shared_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_event = {
                "timestamp": "2026-02-20T09:00:00",
                "action": "record_takeout",
                "status": "success",
                "channel": "gui",
                "details": {"note": "legacy"},
            }
            legacy_shared_path.write_text(json.dumps(legacy_event, ensure_ascii=False) + "\n", encoding="utf-8")

            dialog = self._new_dialog(yaml_path)
            dialog.audit_start_date.setDate(QDate(2000, 1, 1))
            dialog.audit_end_date.setDate(QDate(2099, 12, 31))
            dialog.on_load_audit()

            actions = [dialog.audit_table.item(row, 1).text() for row in range(dialog.audit_table.rowCount())]
            self.assertIn("seed", actions)
            self.assertIn("record_takeout", actions)

    def test_click_row_uses_source_index_after_sort(self):
        dialog = self._new_dialog("D:/tmp/inventory.yaml")
        dialog._audit_events = [
            {
                "timestamp": "2026-02-10T09:00:00",
                "action": "older-event",
                "status": "success",
                "actor_id": "u1",
                "channel": "gui",
            },
            {
                "timestamp": "2026-02-20T09:00:00",
                "action": "newer-event",
                "status": "success",
                "actor_id": "u2",
                "channel": "gui",
            },
        ]
        dialog._setup_table(
            dialog.audit_table,
            ["timestamp", "action", "actor", "status", "channel", "details"],
            sortable=True,
        )
        for idx, event in enumerate(dialog._audit_events):
            dialog.audit_table.insertRow(idx)
            ts_item = QTableWidgetItem(event.get("timestamp", ""))
            ts_item.setData(Qt.UserRole, idx)
            dialog.audit_table.setItem(idx, 0, ts_item)
            dialog.audit_table.setItem(idx, 1, QTableWidgetItem(event.get("action", "")))
            dialog.audit_table.setItem(idx, 2, QTableWidgetItem(event.get("actor_id", "")))
            dialog.audit_table.setItem(idx, 3, QTableWidgetItem(event.get("status", "")))
            dialog.audit_table.setItem(idx, 4, QTableWidgetItem(event.get("channel", "")))
            dialog.audit_table.setItem(idx, 5, QTableWidgetItem(""))

        dialog.audit_table.sortItems(0, Qt.DescendingOrder)
        displayed_action = dialog.audit_table.item(0, 1).text()
        dialog._on_audit_row_clicked(0, 0)

        self.assertIn(displayed_action, dialog.event_detail.text())

    def test_event_detail_escapes_html_in_details(self):
        dialog = self._new_dialog("D:/tmp/inventory.yaml")
        dialog._audit_events = [
            {
                "timestamp": "2026-02-20T09:00:00",
                "action": "record_takeout",
                "status": "success",
                "actor_id": "u1",
                "channel": "gui",
                "details": {"note": "<script>alert(1)</script>"},
            }
        ]
        dialog._setup_table(
            dialog.audit_table,
            ["timestamp", "action", "actor", "status", "channel", "details"],
            sortable=True,
        )
        dialog.audit_table.insertRow(0)
        ts_item = QTableWidgetItem("2026-02-20T09:00:00")
        ts_item.setData(Qt.UserRole, 0)
        dialog.audit_table.setItem(0, 0, ts_item)
        dialog.audit_table.setItem(0, 1, QTableWidgetItem("record_takeout"))
        dialog.audit_table.setItem(0, 2, QTableWidgetItem("u1"))
        dialog.audit_table.setItem(0, 3, QTableWidgetItem("success"))
        dialog.audit_table.setItem(0, 4, QTableWidgetItem("gui"))
        dialog.audit_table.setItem(0, 5, QTableWidgetItem(""))

        dialog._on_audit_row_clicked(0, 0)
        detail_html = dialog.event_detail.text()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", detail_html)
        self.assertNotIn("<script>alert(1)</script>", detail_html)


if __name__ == "__main__":
    unittest.main()
