import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    from app_gui.ui.operations_panel import OperationsPanel
    from app_gui.i18n import tr

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    QApplication = None
    OperationsPanel = None
    tr = None
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class BoxPositionLookupTests(unittest.TestCase):
    """Tests for Box + Position record lookup (replacing ID input)."""

    @classmethod
    def setUpClass(cls):
        if PYSIDE_AVAILABLE and QApplication.instance() is None:
            cls.app = QApplication([])

    def _new_operations_panel(self):
        panel = OperationsPanel(
            bridge=None,
            yaml_path_getter=lambda: "/tmp/test.yaml",
        )
        panel._plan_store.clear()
        return panel

    def test_move_form_looks_up_record_by_box_position(self):
        """Move form should find record by box + position, not ID."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            42: {"id": 42, "cell_line": "K562", "short_name": "test",
                 "box": 2, "position": 15, "frozen_at": "2025-01-01"},
        })

        # User enters box 2, position 15
        panel.m_from_box.setValue(2)
        panel.m_from_position.setText("15")

        # Internal ID should be auto-filled
        self.assertEqual(42, panel.m_id.value())
        # Context should show record info
        self.assertEqual("K562", panel.m_ctx_cell_line.text())

    def test_thaw_form_looks_up_record_by_box_position(self):
        """Thaw form should find record by box + position, not ID."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            99: {"id": 99, "cell_line": "HeLa", "short_name": "test",
                 "box": 3, "position": 7, "frozen_at": "2025-02-01"},
        })

        # User enters box 3, position 7
        panel.t_from_box.setValue(3)
        panel.t_from_position.setText("7")

        # Internal ID should be auto-filled
        self.assertEqual(99, panel.t_id.value())
        # Context should show record info
        self.assertEqual("HeLa", panel.t_ctx_cell_line.text())

    def test_move_prefill_sets_source_and_target(self):
        """Move prefill should set both source and target box/position."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            10: {"id": 10, "cell_line": "K562", "box": 1, "position": 5},
        })

        panel.set_move_prefill({
            "box": 1,
            "position": 5,
            "to_box": 2,
            "to_position": 8,
        })

        self.assertEqual(1, panel.m_from_box.value())
        self.assertEqual("5", panel.m_from_position.text())
        self.assertEqual(2, panel.m_to_box.value())
        self.assertEqual("8", panel.m_to_position.text())

    def test_move_drag_target_box_not_overwritten(self):
        """Dragging to different box should preserve target box."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            20: {"id": 20, "cell_line": "K562", "box": 2, "position": 10},
        })

        # Simulate drag from Box 2 to Box 1
        panel.set_move_prefill({
            "box": 2,
            "position": 10,
            "to_box": 1,
            "to_position": 15,
        })

        # Target box should remain 1, not be overwritten to 2
        self.assertEqual(1, panel.m_to_box.value())
        self.assertEqual("15", panel.m_to_position.text())

    def test_move_manual_source_change_resets_target_box(self):
        """Manually changing source should allow target box auto-fill."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            30: {"id": 30, "cell_line": "K562", "box": 3, "position": 5},
        })

        # First, drag sets user-specified flag
        panel.set_move_prefill({
            "box": 2,
            "position": 1,
            "to_box": 1,
            "to_position": 10,
        })
        self.assertEqual(1, panel.m_to_box.value())

        # Then user manually changes source
        panel.m_from_box.setValue(3)
        panel.m_from_position.setText("5")

        # Target box should auto-fill to source box (3)
        self.assertEqual(3, panel.m_to_box.value())


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class PlanTableColumnsTests(unittest.TestCase):
    """Tests for plan table displaying all necessary columns."""

    @classmethod
    def setUpClass(cls):
        if PYSIDE_AVAILABLE and QApplication.instance() is None:
            cls.app = QApplication([])

    def _new_operations_panel(self):
        panel = OperationsPanel(
            bridge=None,
            yaml_path_getter=lambda: "/tmp/test.yaml",
        )
        panel._plan_store.clear()
        return panel

    def test_plan_table_has_fixed_columns(self):
        """Plan table should use unified fixed columns for mixed operations."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            1: {"id": 1, "cell_line": "K562", "box": 1, "position": 5, "frozen_at": "2025-01-01"},
        })

        # Add a move item to plan
        panel.add_plan_items([{
            "action": "move",
            "record_id": 1,
            "box": 1,
            "position": 5,
            "to_position": 8,
            "payload": {"date_str": "2025-02-19"},
        }])

        # Check table has expected columns
        headers = [panel.plan_table.horizontalHeaderItem(i).text()
                   for i in range(panel.plan_table.columnCount())]

        self.assertIn(tr("operations.colAction"), headers)
        self.assertIn(tr("operations.colPosition"), headers)
        self.assertIn(tr("operations.date"), headers)
        self.assertIn(tr("operations.colChanges"), headers)
        self.assertIn(tr("operations.colNote"), headers)
        self.assertIn(tr("operations.colStatus"), headers)

    def test_plan_table_shows_changes_summary_for_thaw_item(self):
        """Plan table should summarize record metadata in Changes column."""
        panel = self._new_operations_panel()
        panel.update_records_cache({
            2: {"id": 2, "cell_line": "HeLa", "box": 2, "position": 10, "frozen_at": "2024-12-25"},
        })

        panel.add_plan_items([{
            "action": "thaw",
            "record_id": 2,
            "box": 2,
            "position": 10,
            "payload": {"date_str": "2025-02-19", "action": "Takeout"},
        }])

        # Find date and changes column indices
        headers = [panel.plan_table.horizontalHeaderItem(i).text()
                   for i in range(panel.plan_table.columnCount())]
        date_col = headers.index(tr("operations.date"))
        changes_col = headers.index(tr("operations.colChanges"))

        self.assertEqual("2025-02-19", panel.plan_table.item(0, date_col).text())
        self.assertIn("HeLa", panel.plan_table.item(0, changes_col).text())

    def test_plan_table_shows_edit_field_diff(self):
        """Edit rows should display changed fields in Changes column."""
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                7: {
                    "id": 7,
                    "cell_line": "K562",
                    "short_name": "old-name",
                    "box": 1,
                    "position": 9,
                    "frozen_at": "2025-01-01",
                }
            }
        )

        panel.add_plan_items(
            [
                {
                    "action": "edit",
                    "record_id": 7,
                    "box": 1,
                    "position": 9,
                    "payload": {"record_id": 7, "fields": {"short_name": "new-name", "cell_line": "HeLa"}},
                }
            ]
        )

        headers = [
            panel.plan_table.horizontalHeaderItem(i).text()
            for i in range(panel.plan_table.columnCount())
        ]
        changes_col = headers.index(tr("operations.colChanges"))
        cell_text = panel.plan_table.item(0, changes_col).text()
        self.assertIn("Short Name", cell_text)
        self.assertIn("new-name", cell_text)
        self.assertIn("HeLa", cell_text)


if __name__ == "__main__":
    unittest.main()
