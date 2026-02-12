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
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app_gui.ui.ai_panel import AIPanel
    from app_gui.ui.overview_panel import OverviewPanel
    from app_gui.ui.operations_panel import OperationsPanel

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    QApplication = None
    QMessageBox = None
    AIPanel = None
    OverviewPanel = None
    OperationsPanel = None
    PYSIDE_AVAILABLE = False


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
        self.last_query_filters = None
        self.last_empty_box = None
        self.last_record_payload = None
        self.last_batch_payload = None
        self.add_response = {"ok": True, "result": {"new_id": 99}}
        self.query_response = {
            "ok": True,
            "result": {
                "records": [
                    {
                        "id": 5,
                        "parent_cell_line": "K562",
                        "short_name": "K562_clone12",
                        "box": 2,
                        "positions": [10],
                        "frozen_at": "2026-02-10",
                        "plasmid_id": "P-001",
                        "note": "demo",
                    }
                ],
                "count": 1,
            },
        }
        self.empty_response = {
            "ok": True,
            "result": {
                "boxes": [
                    {
                        "box": "2",
                        "empty_count": 80,
                        "total_slots": 81,
                        "empty_positions": [1, 2, 3],
                    }
                ]
            },
        }

    def add_entry(self, yaml_path, **payload):
        self.last_add_payload = {"yaml_path": yaml_path, **payload}
        return self.add_response

    def query_inventory(self, yaml_path, **filters):
        self.last_query_filters = {"yaml_path": yaml_path, **filters}
        return self.query_response

    def list_empty_positions(self, yaml_path, box=None):
        self.last_empty_box = box
        return self.empty_response

    def record_thaw(self, yaml_path, **payload):
        self.last_record_payload = {"yaml_path": yaml_path, **payload}
        return {"ok": True, "preview": payload, "result": {"record_id": payload.get("record_id")}}

    def batch_thaw(self, yaml_path, **payload):
        self.last_batch_payload = {"yaml_path": yaml_path, **payload}
        entries = payload.get("entries") or []
        record_ids = []
        for entry in entries:
            if isinstance(entry, (list, tuple)) and entry:
                record_ids.append(entry[0])
        return {
            "ok": True,
            "preview": {"count": len(entries), "operations": []},
            "result": {"count": len(entries), "record_ids": record_ids},
        }


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_operations_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def _new_ai_panel(self):
        return AIPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def _new_overview_panel(self):
        return OverviewPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    @staticmethod
    def _make_table_item(text):
        from PySide6.QtWidgets import QTableWidgetItem

        return QTableWidgetItem(text)

    def test_operations_panel_refreshes_stale_default_dates(self):
        panel = self._new_operations_panel()
        today = QDate.currentDate()
        yesterday = today.addDays(-1)

        panel._default_date_anchor = yesterday
        panel.a_date.setDate(yesterday)
        panel.t_date.setDate(yesterday)
        panel.b_date.setDate(yesterday)

        panel.set_mode("add")

        self.assertEqual(today, panel.a_date.date())
        self.assertEqual(today, panel.t_date.date())
        self.assertEqual(today, panel.b_date.date())

    def test_operations_panel_does_not_override_user_selected_date(self):
        panel = self._new_operations_panel()
        today = QDate.currentDate()
        yesterday = today.addDays(-1)
        custom_date = today.addDays(-3)

        panel._default_date_anchor = yesterday
        panel.a_date.setDate(custom_date)
        panel.t_date.setDate(yesterday)
        panel.b_date.setDate(yesterday)

        panel._ensure_today_defaults()

        self.assertEqual(custom_date, panel.a_date.date())
        self.assertEqual(today, panel.t_date.date())
        self.assertEqual(today, panel.b_date.date())

    def test_operations_panel_cache_normalizes_string_keys(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                "1": {
                    "id": 1,
                    "parent_cell_line": "K562",
                    "short_name": "k562-a",
                    "box": 1,
                    "positions": [1],
                    "frozen_at": "2026-02-10",
                }
            }
        )

        record = panel._lookup_record(1)
        self.assertIsInstance(record, dict)
        self.assertEqual(1, int(record.get("id")))

    def test_operations_panel_add_entry_parses_positions_text(self):
        panel = self._new_operations_panel()

        panel.a_parent.setText("K562")
        panel.a_short.setText("K562_clone12")
        panel.a_box.setValue(1)
        panel.a_positions.setText("30-32,35")

        panel.on_add_entry()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("add", item["action"])
        self.assertEqual([30, 31, 32, 35], item["payload"]["positions"])
        self.assertEqual("K562_clone12", item["label"])

    def test_operations_panel_add_entry_rejects_invalid_positions_text(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        messages = []
        panel.status_message.connect(lambda msg, timeout, level: messages.append((msg, timeout, level)))

        panel.a_positions.setText("33x")
        panel.on_add_entry()

        self.assertIsNone(bridge.last_add_payload)
        self.assertTrue(messages)
        self.assertIn("位置格式错误", messages[-1][0])

    def test_operations_panel_uses_add_to_plan_buttons(self):
        panel = self._new_operations_panel()

        self.assertEqual("Add to Plan", panel.a_apply_btn.text())
        self.assertEqual("Add to Plan", panel.t_apply_btn.text())
        self.assertEqual("Add to Plan", panel.b_apply_btn.text())
        self.assertEqual("Add to Plan", panel.m_apply_btn.text())
        self.assertEqual("Add to Plan", panel.bm_apply_btn.text())

        self.assertFalse(hasattr(panel, "a_dry_run"))
        self.assertFalse(hasattr(panel, "t_dry_run"))
        self.assertFalse(hasattr(panel, "b_dry_run"))

    def test_operations_panel_action_dropdown_supports_move(self):
        panel = self._new_operations_panel()

        single_actions = [panel.t_action.itemText(i) for i in range(panel.t_action.count())]
        batch_actions = [panel.b_action.itemText(i) for i in range(panel.b_action.count())]

        self.assertNotIn("Move", single_actions)
        self.assertNotIn("Move", batch_actions)

        mode_keys = [panel.op_mode_combo.itemData(i) for i in range(panel.op_mode_combo.count())]
        self.assertIn("move", mode_keys)

    def test_operations_panel_move_tab_has_from_and_to_position(self):
        panel = self._new_operations_panel()

        self.assertTrue(hasattr(panel, "m_from_position"))
        self.assertTrue(hasattr(panel, "m_to_position"))
        self.assertTrue(hasattr(panel, "m_to_box"))
        self.assertEqual(4, panel.bm_table.columnCount())
        self.assertEqual("From", panel.bm_table.horizontalHeaderItem(1).text())
        self.assertEqual("To", panel.bm_table.horizontalHeaderItem(2).text())
        self.assertEqual("To Box", panel.bm_table.horizontalHeaderItem(3).text())

    def test_operations_panel_single_move_passes_to_position(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            11: {"id": 11, "parent_cell_line": "K562", "short_name": "K562-move",
                 "box": 2, "positions": [5, 8]},
        })

        panel.m_id.setValue(11)
        panel.m_from_position.setValue(5)
        panel.m_to_position.setValue(8)
        panel.on_record_move()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("move", item["action"])
        self.assertEqual(8, item["to_position"])
        self.assertEqual(5, item["position"])
        self.assertEqual(8, item["payload"]["to_position"])

    def test_operations_panel_batch_move_table_collects_triples(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            12: {"id": 12, "parent_cell_line": "K562", "short_name": "K562-bm",
                 "box": 3, "positions": [23, 31]},
        })

        panel.bm_table.setRowCount(1)
        panel.bm_table.setItem(0, 0, self._make_table_item("12"))
        panel.bm_table.setItem(0, 1, self._make_table_item("23"))
        panel.bm_table.setItem(0, 2, self._make_table_item("31"))

        panel.on_batch_move()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("move", item["action"])
        self.assertEqual(12, item["record_id"])
        self.assertEqual(23, item["position"])
        self.assertEqual(31, item["to_position"])

    def test_operations_panel_move_batch_section_collapsed_by_default(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel.m_batch_group.isHidden())
        self.assertEqual("Show Batch Move", panel.m_batch_toggle_btn.text())

        panel.m_batch_toggle_btn.setChecked(True)
        self.assertFalse(panel.m_batch_group.isHidden())
        self.assertEqual("Hide Batch Move", panel.m_batch_toggle_btn.text())

    def test_operations_panel_emits_completion_on_success_without_dry_run_gate(self):
        panel = self._new_operations_panel()
        emitted = []
        panel.operation_completed.connect(lambda success: emitted.append(bool(success)))

        panel._handle_response({"ok": True, "result": {"dry_run": True}}, "Single Operation")

        self.assertEqual([True], emitted)

    def test_operations_panel_prefill_context_shows_autofill_status(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                5: {
                    "id": 5,
                    "parent_cell_line": "K562",
                    "short_name": "K562_RTCB_dTAG_clone12",
                    "box": 1,
                    "positions": [30, 31],
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertEqual("Record loaded - form auto-filled.", panel.t_ctx_status.text())
        self.assertEqual("Box 1:30", panel.t_ctx_source.text())

    def test_operations_panel_set_move_prefill_fills_move_form(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            7: {"id": 7, "parent_cell_line": "K562", "short_name": "K562_move",
                "box": 2, "positions": [15, 20]},
        })

        panel.set_move_prefill({"box": 2, "position": 15, "record_id": 7})

        self.assertEqual(7, panel.m_id.value())
        self.assertEqual(15, panel.m_from_position.value())
        self.assertEqual("move", panel.current_operation_mode)

    def test_operations_panel_set_query_prefill_fills_query_and_runs(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        panel.set_query_prefill({"box": 3, "position": 25, "record_id": 10})

        self.assertEqual(3, panel.q_box.value())
        self.assertEqual(25, panel.q_position.value())
        self.assertEqual("query", panel.current_operation_mode)
        self.assertEqual(3, bridge.last_query_filters.get("box"))
        self.assertEqual(25, bridge.last_query_filters.get("position"))

    def test_operations_panel_batch_section_collapsed_by_default(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual("Show Batch Operation", panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(True)
        self.assertFalse(panel.t_batch_group.isHidden())
        self.assertEqual("Hide Batch Operation", panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(False)
        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual("Show Batch Operation", panel.t_batch_toggle_btn.text())

    def test_operations_panel_query_uses_backend_filter_names(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        panel.q_cell.setText("K562")
        panel.q_short.setText("clone12")
        panel.q_plasmid.setText("EGFP")
        panel.q_plasmid_id.setText("P-001")
        panel.q_box.setValue(2)
        panel.q_position.setValue(10)

        panel.on_query_records()

        self.assertEqual(
            {
                "yaml_path": "/tmp/inventory.yaml",
                "cell": "K562",
                "short": "clone12",
                "plasmid": "EGFP",
                "plasmid_id": "P-001",
                "box": 2,
                "position": 10,
            },
            bridge.last_query_filters,
        )
        self.assertEqual(1, panel.query_table.rowCount())
        self.assertEqual("5", panel.query_table.item(0, 0).text())

    def test_operations_panel_list_empty_reads_boxes_payload(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        panel.q_box.setValue(2)
        panel.on_list_empty()

        self.assertEqual(2, bridge.last_empty_box)
        self.assertEqual(1, panel.query_table.rowCount())
        self.assertEqual("2", panel.query_table.item(0, 0).text())

    def test_overview_double_click_shows_menu_and_emits_thaw_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_RTCB_dTAG_clone12",
            "box": 1,
            "positions": [1],
            "frozen_at": "2026-02-10",
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        emitted_thaw = []
        emitted_move = []
        emitted_query = []
        panel.request_prefill.connect(lambda payload: emitted_thaw.append(payload))
        panel.request_move_prefill.connect(lambda payload: emitted_move.append(payload))
        panel.request_query_prefill.connect(lambda payload: emitted_query.append(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_thaw = MagicMock()
            mock_act_move = MagicMock()
            mock_act_query = MagicMock()
            mock_menu.addAction.side_effect = [mock_act_thaw, mock_act_move, mock_act_query]
            mock_menu.exec.return_value = mock_act_thaw
            panel.on_cell_double_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1, "record_id": 5}], emitted_thaw)
        self.assertEqual([], emitted_move)
        self.assertEqual([], emitted_query)

    def test_overview_double_click_menu_emits_move_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "positions": [1],
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        emitted_move = []
        panel.request_move_prefill.connect(lambda payload: emitted_move.append(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_thaw = MagicMock()
            mock_act_move = MagicMock()
            mock_act_query = MagicMock()
            mock_menu.addAction.side_effect = [mock_act_thaw, mock_act_move, mock_act_query]
            mock_menu.exec.return_value = mock_act_move
            panel.on_cell_double_clicked(1, 1)

        self.assertEqual([{"box": 1, "position": 1, "record_id": 5}], emitted_move)

    def test_overview_double_click_menu_emits_query_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "positions": [1],
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        emitted_query = []
        panel.request_query_prefill.connect(lambda payload: emitted_query.append(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_thaw = MagicMock()
            mock_act_move = MagicMock()
            mock_act_query = MagicMock()
            mock_menu.addAction.side_effect = [mock_act_thaw, mock_act_move, mock_act_query]
            mock_menu.exec.return_value = mock_act_query
            panel.on_cell_double_clicked(1, 1)

        self.assertEqual([{"box": 1, "position": 1, "record_id": 5}], emitted_query)

    def test_overview_double_click_empty_slot_shows_menu_and_emits_add_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        panel.overview_pos_map = {}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record=None)

        emitted = []
        panel.request_add_prefill.connect(lambda payload: emitted.append(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_add = MagicMock()
            mock_menu.addAction.return_value = mock_act_add
            mock_menu.exec.return_value = mock_act_add
            panel.on_cell_double_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1}], emitted)
        self.assertIn("#16a34a", button.styleSheet())

    def test_overview_select_mode_toggle(self):
        panel = self._new_overview_panel()
        self.assertFalse(panel.select_mode)
        panel.ov_select_btn.setChecked(True)
        self.assertTrue(panel.select_mode)
        self.assertEqual(panel.ov_select_btn.text(), "Exit Select")
        panel.ov_select_btn.setChecked(False)
        self.assertFalse(panel.select_mode)
        self.assertEqual(panel.ov_select_btn.text(), "Select")

    def test_overview_multi_select_toggle_cell(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        rec1 = {"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [1]}
        rec2 = {"id": 2, "parent_cell_line": "K562", "short_name": "B", "box": 1, "positions": [2]}
        panel.overview_pos_map = {(1, 1): rec1, (1, 2): rec2}
        for key, rec in panel.overview_pos_map.items():
            panel._paint_cell(panel.overview_cells[key], key[0], key[1], rec)

        panel.ov_select_btn.setChecked(True)

        # Select cell (1,1)
        panel.on_cell_clicked(1, 1)
        self.assertIn((1, 1), panel.overview_selected_keys)
        self.assertIn("#16a34a", panel.overview_cells[(1, 1)].styleSheet())

        # Select cell (1,2)
        panel.on_cell_clicked(1, 2)
        self.assertIn((1, 2), panel.overview_selected_keys)
        self.assertEqual(len(panel.overview_selected_keys), 2)

        # Toggle off cell (1,1)
        panel.on_cell_clicked(1, 1)
        self.assertNotIn((1, 1), panel.overview_selected_keys)
        self.assertEqual(len(panel.overview_selected_keys), 1)

        # Empty cell should not be selectable
        panel.overview_pos_map.pop((1, 2))
        panel.on_cell_clicked(1, 2)
        # (1,2) was toggled off since no record
        # It was already in the set; _toggle_cell_selection checks for record
        # After pop, clicking (1,2) should be ignored since no record

    def test_overview_selection_bar_visibility(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        rec = {"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [1]}
        panel.overview_pos_map = {(1, 1): rec}
        panel._paint_cell(panel.overview_cells[(1, 1)], 1, 1, rec)

        self.assertTrue(panel.ov_selection_bar.isHidden())

        panel.ov_select_btn.setChecked(True)
        panel.on_cell_clicked(1, 1)
        self.assertFalse(panel.ov_selection_bar.isHidden())
        self.assertIn("1 selected", panel.ov_sel_count.text())

        panel._clear_all_selections()
        self.assertTrue(panel.ov_selection_bar.isHidden())
        self.assertIn("0 selected", panel.ov_sel_count.text())

    def test_overview_quick_action_emits_plan_items(self):
        bridge = _FakeOperationsBridge()
        panel = OverviewPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        rec1 = {"id": 10, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [1]}
        rec2 = {"id": 11, "parent_cell_line": "K562", "short_name": "B", "box": 1, "positions": [2]}
        panel.overview_pos_map = {(1, 1): rec1, (1, 2): rec2}

        panel.ov_select_btn.setChecked(True)
        panel.on_cell_clicked(1, 1)
        panel.on_cell_clicked(1, 2)
        self.assertEqual(len(panel.overview_selected_keys), 2)

        emitted = []
        panel.plan_items_requested.connect(lambda items: emitted.append(items))
        panel._on_quick_action("Takeout")

        self.assertEqual(1, len(emitted))
        items = emitted[0]
        self.assertEqual(2, len(items))
        ids = sorted([it["record_id"] for it in items])
        self.assertEqual([10, 11], ids)
        for it in items:
            self.assertEqual("takeout", it["action"])
            self.assertEqual("human", it["source"])
        self.assertEqual(len(panel.overview_selected_keys), 0)

    def test_overview_clear_selections(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        rec1 = {"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [1]}
        rec2 = {"id": 2, "parent_cell_line": "K562", "short_name": "B", "box": 1, "positions": [2]}
        panel.overview_pos_map = {(1, 1): rec1, (1, 2): rec2}
        for key, rec in panel.overview_pos_map.items():
            panel._paint_cell(panel.overview_cells[key], key[0], key[1], rec)

        panel.ov_select_btn.setChecked(True)
        panel.on_cell_clicked(1, 1)
        panel.on_cell_clicked(1, 2)
        self.assertEqual(len(panel.overview_selected_keys), 2)

        panel._clear_all_selections()
        self.assertEqual(len(panel.overview_selected_keys), 0)
        self.assertNotIn("#16a34a", panel.overview_cells[(1, 1)].styleSheet())
        self.assertNotIn("#16a34a", panel.overview_cells[(1, 2)].styleSheet())

    # --- Plan tab tests ---

    def test_plan_tab_exists_in_mode_selector(self):
        panel = self._new_operations_panel()
        mode_keys = [panel.op_mode_combo.itemData(i) for i in range(panel.op_mode_combo.count())]
        self.assertIn("plan", mode_keys)
        self.assertTrue(hasattr(panel, "plan_table"))
        self.assertTrue(hasattr(panel, "plan_exec_btn"))

    def test_add_plan_items_populates_table(self):
        panel = self._new_operations_panel()
        items = [
            {
                "action": "takeout",
                "box": 1,
                "position": 5,
                "record_id": 10,
                "label": "K562_A",
                "source": "human",
                "payload": {
                    "record_id": 10,
                    "position": 5,
                    "date_str": "2026-02-10",
                    "action": "Takeout",
                    "note": "test",
                },
            },
        ]
        panel.add_plan_items(items)

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual(1, panel.plan_table.rowCount())
        self.assertEqual("human", panel.plan_table.item(0, 0).text())
        self.assertEqual("Takeout", panel.plan_table.item(0, 1).text())
        self.assertEqual("plan", panel.current_operation_mode)

        # Badge should show count
        idx = panel.op_mode_combo.findData("plan")
        self.assertIn("1", panel.op_mode_combo.itemText(idx))

    def test_add_plan_items_validates_and_rejects_invalid(self):
        panel = self._new_operations_panel()
        messages = []
        panel.status_message.connect(lambda msg, timeout, level: messages.append(msg))

        invalid_items = [
            {
                "action": "takeout",
                "box": -1,  # invalid: must be >= 0
                "position": 5,
                "record_id": 10,
                "label": "test",
                "source": "human",
                "payload": {},
            },
        ]
        panel.add_plan_items(invalid_items)

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(any("rejected" in m.lower() for m in messages))

    def test_execute_plan_calls_bridge_and_clears(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        panel.yaml_path_getter = lambda: "/tmp/inventory.yaml"

        items = [
            {
                "action": "takeout",
                "box": 1,
                "position": 5,
                "record_id": 10,
                "label": "K562_A",
                "source": "human",
                "payload": {
                    "record_id": 10,
                    "position": 5,
                    "date_str": "2026-02-10",
                    "action": "Takeout",
                    "note": "test",
                },
            },
        ]
        panel.add_plan_items(items)
        self.assertEqual(1, len(panel.plan_items))

        emitted = []
        panel.operation_completed.connect(lambda ok: emitted.append(ok))

        # Mock QMessageBox to auto-confirm
        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertIsNotNone(bridge.last_batch_payload)
        self.assertEqual("Takeout", bridge.last_batch_payload["action"])
        self.assertEqual(0, len(panel.plan_items))
        self.assertEqual([True], emitted)

    def test_operations_panel_record_thaw_creates_plan_item(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            5: {"id": 5, "parent_cell_line": "K562", "short_name": "K562_test",
                "box": 2, "positions": [10]},
        })

        panel.t_id.setValue(5)
        panel.t_position.setValue(10)
        panel.t_action.setCurrentText("Takeout")
        panel.on_record_thaw()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(2, item["box"])
        self.assertEqual(10, item["position"])
        self.assertEqual(5, item["record_id"])
        self.assertEqual("K562_test", item["label"])

    def test_ai_panel_append_chat_falls_back_when_insert_markdown_missing(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel._append_chat("You", "hello")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("insertPlainText", call_names)

    def test_ai_panel_defaults_model_to_deepseek_chat(self):
        panel = self._new_ai_panel()

        self.assertEqual("deepseek-chat", panel.ai_model.text())

    def test_ai_panel_append_chat_prefers_insert_markdown_when_available(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatWithMarkdown()

        panel._append_chat("Agent", "**bold**")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("insertMarkdown", call_names)

    def test_ai_panel_stream_chunk_updates_chat_incrementally(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-stream"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-stream", "data": "hello"})

        chunk_calls = [
            value for name, value in panel.ai_chat.calls
            if name == "insertPlainText"
        ]
        self.assertIn("hello", chunk_calls)

    def test_ai_panel_stream_chunk_rerenders_markdown_incrementally(self):
        panel = self._new_ai_panel()
        panel.ai_stream_render_interval_sec = 0.0
        panel.ai_stream_render_min_delta = 1

        panel.on_progress({"event": "run_start", "trace_id": "trace-md-live"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-md-live", "data": "**bold**"})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("bold", rendered_text)
        self.assertNotIn("**bold**", rendered_text)

    def test_ai_panel_finished_does_not_duplicate_streamed_final(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-stream"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-stream", "data": "hello"})
        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-stream"}})

        chunk_calls = [
            value for name, value in panel.ai_chat.calls
            if name == "insertPlainText"
        ]
        self.assertEqual(1, chunk_calls.count("hello"))

    def test_ai_panel_shows_tool_progress_in_chat(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-tool"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-tool",
                "data": {"name": "query_thaw_events"},
            }
        )
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-tool",
                "step": 1,
                "data": {"name": "query_thaw_events"},
                "observation": {"ok": True},
            }
        )

        text_calls = [value for name, value in panel.ai_chat.calls if name == "insertPlainText"]
        merged = "\n".join(text_calls)
        self.assertIn("Running `query_thaw_events`...", merged)
        self.assertIn("finished: **OK**", merged)

    def test_ai_panel_renders_blocked_items_from_tool_result(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-blocked"})
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-blocked",
                "step": 1,
                "data": {"name": "record_thaw"},
                "observation": {
                    "ok": False,
                    "error_code": "plan_preflight_failed",
                    "message": "Validation blocked",
                    "blocked_items": [
                        {
                            "action": "takeout",
                            "record_id": 999,
                            "box": 1,
                            "position": 5,
                            "error_code": "record_not_found",
                            "message": "Record does not exist",
                        }
                    ],
                },
            }
        )

        text_calls = [value for name, value in panel.ai_chat.calls if name == "insertPlainText"]
        merged = "\n".join(text_calls)
        self.assertIn("Tool blocked", merged)
        self.assertIn("ID 999", merged)
        self.assertIn("Record does not exist", merged)

    def test_ai_panel_rewrites_streamed_markdown_on_finish(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-md"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-md", "data": "**bold**"})
        panel.on_finished({"ok": True, "result": {"final": "**bold**", "trace_id": "trace-md"}})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("bold", rendered_text)
        self.assertNotIn("**bold**", rendered_text)

    def test_ai_panel_separates_multiple_runs_without_merging_messages(self):
        panel = self._new_ai_panel()

        panel._append_chat("You", "hi")
        panel.on_progress({"event": "run_start", "trace_id": "trace-a"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-a", "data": "hello"})
        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-a"}})

        panel._append_chat("You", "overview")
        panel.on_progress({"event": "run_start", "trace_id": "trace-b"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-b", "data": "summary"})
        panel.on_finished({"ok": True, "result": {"final": "summary", "trace_id": "trace-b"}})

        text = panel.ai_chat.toPlainText()
        self.assertGreaterEqual(text.count("You"), 2)
        self.assertIn("hi", text)
        self.assertIn("overview", text)
        self.assertNotIn("hioverview", text)

    def test_ai_panel_tool_start_breaks_stream_text_boundary(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-boundary"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-boundary", "data": "hello"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-boundary",
                "data": {"name": "generate_stats"},
            }
        )

        text = panel.ai_chat.toPlainText()
        self.assertIn("hello", text)
        self.assertIn("Running generate_stats", text)
        self.assertNotIn("helloRunning", text)

    def test_ai_panel_finished_uses_wrapped_result_shape(self):
        panel = self._new_ai_panel()

        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-test"}})

        self.assertGreaterEqual(len(panel.ai_history), 1)
        self.assertEqual("assistant", panel.ai_history[-1]["role"])
        self.assertEqual("hello", panel.ai_history[-1]["content"])

    def test_ai_panel_finished_flags_protocol_error_without_result(self):
        panel = self._new_ai_panel()

        panel.on_finished({"ok": True, "result": None})

        self.assertGreaterEqual(len(panel.ai_history), 1)
        self.assertEqual("assistant", panel.ai_history[-1]["role"])
        self.assertIn("protocol error", panel.ai_history[-1]["content"].lower())

    def test_ai_panel_finished_emits_status_for_missing_api_key(self):
        panel = self._new_ai_panel()
        messages = []
        panel.status_message.connect(lambda msg, timeout: messages.append((msg, timeout)))

        panel.on_finished({"ok": False, "error_code": "api_key_required", "result": None})

        self.assertTrue(messages)
        self.assertIn("api key", messages[-1][0].lower())


if __name__ == "__main__":
    unittest.main()


class ToolRunnerPlanSinkTests(unittest.TestCase):
    """Test that AgentToolRunner stages write operations when plan_sink is set."""

    def setUp(self):
        self.staged = []
        self.sink = lambda item: self.staged.append(item)

    def _make_runner(self, yaml_path="/tmp/inventory.yaml"):
        from agent.tool_runner import AgentToolRunner
        return AgentToolRunner(
            yaml_path=yaml_path,
            actor_id="test-agent",
            plan_sink=self.sink,
        )

    def test_read_tool_not_intercepted(self):
        runner = self._make_runner()
        result = runner.run("query_inventory", {"cell": "K562"})
        # Should execute normally (may fail if YAML not found, but not staged)
        self.assertEqual(0, len(self.staged))

    def test_add_entry_staged(self):
        runner = self._make_runner()
        result = runner.run("add_entry", {
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "positions": [30],
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.staged))
        item = self.staged[0]
        self.assertEqual("add", item["action"])
        self.assertEqual("ai", item["source"])
        self.assertEqual(1, item["box"])

    def test_record_thaw_staged(self):
        runner = self._make_runner()
        result = runner.run("record_thaw", {
            "record_id": 5,
            "position": 10,
            "action": "Takeout",
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, len(self.staged))
        item = self.staged[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(5, item["record_id"])
        self.assertEqual(10, item["position"])

    def test_without_plan_sink_executes_normally(self):
        from agent.tool_runner import AgentToolRunner
        runner = AgentToolRunner(
            yaml_path="/tmp/inventory.yaml",
            actor_id="test-agent",
        )
        # Without plan_sink, add_entry should attempt execution (may error but not stage)
        result = runner.run("add_entry", {
            "parent_cell_line": "K562",
            "short_name": "test",
            "box": 1,
            "positions": [1],
        })
        self.assertFalse(result.get("staged", False))
        self.assertEqual(0, len(self.staged))


# ── Regression tests: plan dedup + execute fallback ──────────────


def _make_move_item(record_id, position, to_position, to_box=None, label="test"):
    """Helper to create a valid move plan item."""
    item = {
        "action": "move",
        "box": 1,
        "position": position,
        "to_position": to_position,
        "record_id": record_id,
        "label": label,
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
        "label": label,
        "source": "ai",
        "payload": {
            "record_id": record_id,
            "position": position,
            "date_str": "2026-02-10",
            "action": "Takeout",
            "note": None,
        },
    }


class _ConfigurableBridge(_FakeOperationsBridge):
    """Bridge that can be configured to fail specific calls."""

    def __init__(self):
        super().__init__()
        self.batch_should_fail = False
        self.record_thaw_fail_ids = set()
        self.record_thaw_calls = []
        self.batch_thaw_calls = []

    def batch_thaw(self, yaml_path, **payload):
        self.batch_thaw_calls.append(payload)
        if self.batch_should_fail:
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": "批量操作参数校验失败",
                "errors": ["第1条: mock error"],
            }
        return super().batch_thaw(yaml_path, **payload)

    def record_thaw(self, yaml_path, **payload):
        self.record_thaw_calls.append(payload)
        rid = payload.get("record_id")
        if rid in self.record_thaw_fail_ids:
            return {
                "ok": False,
                "error_code": "validation_failed",
                "message": f"Record {rid} failed",
            }
        return super().record_thaw(yaml_path, **payload)


class _RollbackAwareBridge(_ConfigurableBridge):
    """Configurable bridge with rollback tracking and per-record backups."""

    def __init__(self):
        super().__init__()
        self.rollback_called = False
        self.rollback_backup_path = None

    def record_thaw(self, yaml_path, **payload):
        response = super().record_thaw(yaml_path, **payload)
        if response.get("ok"):
            rid = payload.get("record_id")
            response = dict(response)
            response["backup_path"] = f"/tmp/bak_{rid}.yaml"
        return response

    def rollback(self, yaml_path, backup_path=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        return {"ok": True, "message": "Rolled back", "backup_path": backup_path}


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PlanDedupRegressionTests(unittest.TestCase):
    """Regression: add_plan_items should deduplicate by (action, record_id, position)."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_duplicate_item_replaces_existing(self):
        """Staging same (action, record_id, position) should replace, not append."""
        panel = self._new_panel()
        item1 = _make_move_item(record_id=4, position=5, to_position=10)
        item2 = _make_move_item(record_id=4, position=5, to_position=20)  # same key, diff target

        panel.add_plan_items([item1])
        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual(10, panel.plan_items[0]["to_position"])

        panel.add_plan_items([item2])
        self.assertEqual(1, len(panel.plan_items))  # still 1, not 2
        self.assertEqual(20, panel.plan_items[0]["to_position"])  # updated

    def test_different_positions_are_not_deduped(self):
        """Items with different positions should NOT be considered duplicates."""
        panel = self._new_panel()
        item1 = _make_move_item(record_id=4, position=5, to_position=10)
        item2 = _make_move_item(record_id=4, position=6, to_position=11)

        panel.add_plan_items([item1, item2])
        self.assertEqual(2, len(panel.plan_items))

    def test_different_actions_are_not_deduped(self):
        """Same record+position but different action should NOT be deduped."""
        panel = self._new_panel()
        move_item = _make_move_item(record_id=4, position=5, to_position=10)
        takeout_item = _make_takeout_item(record_id=4, position=5)

        panel.add_plan_items([move_item, takeout_item])
        self.assertEqual(2, len(panel.plan_items))

    def test_mass_restage_same_items_no_growth(self):
        """Simulates AI re-staging 10 items — plan should not grow past 10."""
        panel = self._new_panel()
        items = [_make_move_item(record_id=i, position=i, to_position=i + 10) for i in range(1, 11)]

        panel.add_plan_items(items)
        self.assertEqual(10, len(panel.plan_items))

        # AI re-stages same 10 items (possibly with tweaked targets)
        items_v2 = [_make_move_item(record_id=i, position=i, to_position=i + 20) for i in range(1, 11)]
        panel.add_plan_items(items_v2)
        self.assertEqual(10, len(panel.plan_items))  # no duplicates


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecutePlanFallbackRegressionTests(unittest.TestCase):
    """Regression: batch failure should fallback to individual execution."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")
        return panel

    def test_move_batch_fails_falls_back_to_individual(self):
        """When batch_thaw fails, each move should be tried individually via record_thaw."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1, to_box=1),
            _make_move_item(record_id=2, position=10, to_position=2, to_box=1),
        ]
        panel.add_plan_items(items)
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # batch_thaw called once (failed), then 2 individual record_thaw calls
        self.assertEqual(1, len(bridge.batch_thaw_calls))
        self.assertEqual(2, len(bridge.record_thaw_calls))
        # All items should succeed individually → plan cleared
        self.assertEqual(0, len(panel.plan_items))

    def test_move_individual_fallback_partial_failure_preserves_entire_plan(self):
        """When 1 of 3 individual moves fails, entire plan should be preserved for retry."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {2}  # record_id=2 will fail
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # Entire plan should be preserved (all 3 items)
        self.assertEqual(3, len(panel.plan_items))
        preserved_ids = sorted([item["record_id"] for item in panel.plan_items])
        self.assertEqual([1, 2, 3], preserved_ids)

    def test_takeout_batch_fails_falls_back_to_individual(self):
        """Phase 3: batch failure for takeout also falls back to individual."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # batch failed, 2 individual calls succeeded
        self.assertEqual(2, len(bridge.record_thaw_calls))
        self.assertEqual(0, len(panel.plan_items))

    def test_batch_success_no_fallback(self):
        """When batch_thaw succeeds, no individual fallback should be triggered."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = False  # batch succeeds
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # batch called once, no individual calls
        self.assertEqual(1, len(bridge.batch_thaw_calls))
        self.assertEqual(0, len(bridge.record_thaw_calls))
        self.assertEqual(0, len(panel.plan_items))

    def test_phases_continue_after_earlier_failure_preserves_plan(self):
        """Phase 3 should execute even if Phase 2 had failures, but plan is preserved on failure."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {1}  # move for record_id=1 fails
        panel = self._new_panel(bridge)

        # Phase 2 item (move) + Phase 3 item (takeout)
        move = _make_move_item(record_id=1, position=5, to_position=1)
        takeout = _make_takeout_item(record_id=3, position=20)
        panel.add_plan_items([move, takeout])
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # On failure, entire plan is preserved
        self.assertEqual(2, len(panel.plan_items))
        actions = sorted([item["action"] for item in panel.plan_items])
        self.assertEqual(["move", "takeout"], actions)

    def test_all_fail_keeps_all_in_plan(self):
        """If every item fails, all should remain in the plan."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {1, 2}
        panel = self._new_panel(bridge)

        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(2, len(panel.plan_items))

    def test_dedup_then_execute_end_to_end_with_preserved_plan(self):
        """Full scenario: stage → execute partial fail (plan preserved) → use undo + re-stage → execute succeeds."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {2}
        panel = self._new_panel(bridge)

        # First stage: 3 items
        items = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=2),
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items)
        self.assertEqual(3, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # On failure, entire plan is preserved (all 3 items)
        self.assertEqual(3, len(panel.plan_items))
        preserved_ids = sorted([item["record_id"] for item in panel.plan_items])
        self.assertEqual([1, 2, 3], preserved_ids)

        # User can use undo to rollback, then re-execute
        # For this test, just clear and re-add with fix
        panel.plan_items.clear()
        
        # Now execute again — this time all succeed
        bridge.record_thaw_fail_ids.clear()
        bridge.batch_thaw_calls.clear()
        bridge.record_thaw_calls.clear()

        items_v2 = [
            _make_move_item(record_id=1, position=5, to_position=1),
            _make_move_item(record_id=2, position=10, to_position=4),  # different target
            _make_move_item(record_id=3, position=15, to_position=3),
        ]
        panel.add_plan_items(items_v2)
        self.assertEqual(3, len(panel.plan_items))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        # All succeeded, plan cleared
        self.assertEqual(0, len(panel.plan_items))


class _UndoBridge(_FakeOperationsBridge):
    """Bridge that supports rollback for undo tests."""

    def __init__(self):
        super().__init__()
        self.rollback_called = False
        self.rollback_backup_path = None

    def rollback(self, yaml_path, backup_path=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        return {"ok": True, "message": "Rolled back", "backup_path": backup_path}

    def batch_thaw(self, yaml_path, **payload):
        result = super().batch_thaw(yaml_path, **payload)
        result["backup_path"] = "/tmp/backup_test.yaml"
        return result


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class UndoRestoresPlanRegressionTests(unittest.TestCase):
    """Regression: undo should restore executed items back to plan."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_undo_restores_executed_plan_items(self):
        """After executing plan and undoing, items should return to plan."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)
        self.assertEqual(2, len(panel.plan_items))

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(panel.undo_btn.isEnabled())
        self.assertEqual(2, len(panel._last_executed_plan))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertTrue(bridge.rollback_called)
        self.assertEqual(2, len(panel.plan_items))
        self.assertEqual("takeout", panel.plan_items[0]["action"])
        self.assertEqual("plan", panel.current_operation_mode)

    def test_undo_clears_last_executed_plan(self):
        """After undo, _last_executed_plan should be cleared."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [_make_takeout_item(record_id=1, position=5)]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(1, len(panel._last_executed_plan))

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertEqual(0, len(panel._last_executed_plan))

    def test_execute_plan_saves_backup_and_executed_items(self):
        """execute_plan should save backup_path and executed items for undo."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [_make_move_item(record_id=1, position=5, to_position=10)]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual("/tmp/backup_test.yaml", panel._last_operation_backup)
        self.assertEqual(1, len(panel._last_executed_plan))
        self.assertEqual(1, panel._last_executed_plan[0]["record_id"])

    def test_undo_without_executed_plan_does_not_add_items(self):
        """If no plan was executed (e.g., single operation undo), plan stays empty."""
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        panel._last_operation_backup = "/tmp/backup.yaml"
        panel._enable_undo(timeout_sec=30)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.on_undo_last()

        self.assertTrue(bridge.rollback_called)
        self.assertEqual(0, len(panel.plan_items))


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PrintPlanRegressionTests(unittest.TestCase):
    """Regression: printing should support recently executed plans."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_print_plan_uses_last_executed_when_plan_empty(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
        self.assertEqual(2, len(panel._last_printable_plan))

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_plan()

        open_url.assert_called_once()
        self.assertTrue(any("Printing last executed" in msg for msg in messages))

    def test_print_plan_errors_without_current_or_last_plan(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from unittest.mock import patch
        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_plan()

        open_url.assert_not_called()
        self.assertTrue(any("No plan or recent execution to print" in msg for msg in messages))


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class AuditGuideSelectionRegressionTests(unittest.TestCase):
    """Regression: selected audit rows can generate one merged guide."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        return OperationsPanel(bridge=_FakeOperationsBridge(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def _seed_audit_rows(self, panel, events):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTableWidgetItem

        panel._audit_events = list(events)
        panel._setup_table(
            panel.audit_table,
            ["Timestamp", "Action", "Actor", "Status", "Channel", "Details"],
            sortable=True,
        )
        for row, event in enumerate(events):
            panel.audit_table.insertRow(row)
            ts_item = QTableWidgetItem(event.get("timestamp", ""))
            ts_item.setData(Qt.UserRole, row)
            panel.audit_table.setItem(row, 0, ts_item)
            panel.audit_table.setItem(row, 1, QTableWidgetItem(event.get("action", "")))
            panel.audit_table.setItem(row, 2, QTableWidgetItem(event.get("actor_id", "gui-user")))
            panel.audit_table.setItem(row, 3, QTableWidgetItem(event.get("status", "")))
            panel.audit_table.setItem(row, 4, QTableWidgetItem(event.get("channel", "gui")))
            panel.audit_table.setItem(row, 5, QTableWidgetItem(""))

    def test_generate_audit_guide_requires_selection(self):
        panel = self._new_panel()

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))
        panel.on_generate_audit_guide()

        self.assertTrue(any("Select one or more audit rows" in msg for msg in messages))

    def test_selected_audit_rows_generate_merged_printable_guide(self):
        panel = self._new_panel()

        events = [
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "record_thaw",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 9,
                    "box": 1,
                    "position": 20,
                    "to_position": 30,
                },
                "tool_input": {
                    "record_id": 9,
                    "position": 20,
                    "to_position": 30,
                    "action": "Move",
                },
            },
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_thaw",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 9,
                    "box": 1,
                    "position": 10,
                    "to_position": 20,
                },
                "tool_input": {
                    "record_id": 9,
                    "position": 10,
                    "to_position": 20,
                    "action": "Move",
                },
            },
        ]
        self._seed_audit_rows(panel, events)
        panel.audit_table.selectAll()

        panel.on_generate_audit_guide()

        self.assertEqual(1, len(panel._last_printable_plan))
        item = panel._last_printable_plan[0]
        self.assertEqual("move", item["action"])
        self.assertEqual(10, item["position"])
        self.assertEqual(30, item["to_position"])

        from unittest.mock import patch
        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.on_print_selected_audit_guide()

        open_url.assert_called_once()


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PlanPreflightGuardTests(unittest.TestCase):
    """Regression: preflight should block execution of invalid plans."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records):
        import tempfile
        from lib.yaml_ops import write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_preflight_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {"meta": {"box_layout": {"rows": 9, "cols": 9}}, "inventory": records},
            path=yaml_path,
            auto_html=False,
            auto_server=False,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_add_items_triggers_preflight(self):
        """Adding items to plan should trigger preflight validation."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=1, position=5)]
            panel.add_plan_items(items)

            self.assertIsNotNone(panel._plan_preflight_report)
            self.assertEqual(1, len(panel._plan_validation_by_key))
        finally:
            self._cleanup_yaml(tmpdir)

    def test_preflight_marks_blocked_items_in_table(self):
        """Blocked items should show BLOCKED status in table."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            self.assertEqual(1, panel.plan_table.rowCount())
            status_item = panel.plan_table.item(0, 8)
            self.assertIsNotNone(status_item)
            self.assertEqual("BLOCKED", status_item.text())
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_button_disabled_when_blocked(self):
        """Execute button should be disabled when plan has blocked items."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            self.assertFalse(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_button_enabled_when_valid(self):
        """Execute button should be enabled when all items are valid."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _ConfigurableBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_move_item(record_id=1, position=5, to_position=10)]
            panel.add_plan_items(items)

            self.assertTrue(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecuteInterceptTests(unittest.TestCase):
    """Regression: execute should be intercepted when plan is blocked."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records):
        import tempfile
        from lib.yaml_ops import write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_intercept_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {"meta": {"box_layout": {"rows": 9, "cols": 9}}, "inventory": records},
            path=yaml_path,
            auto_html=False,
            auto_server=False,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_blocked_does_not_call_bridge(self):
        """When plan is blocked, execute should not call bridge methods."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            messages = []
            panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

            panel.execute_plan()

            self.assertTrue(any("blocked" in m.lower() for m in messages))
            self.assertIsNone(bridge.last_batch_payload)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_blocked_emits_operation_event(self):
        """Blocked execution should emit operation_event."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "positions": [5], "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            events = []
            panel.operation_event.connect(lambda ev: events.append(ev))

            panel.execute_plan()

            self.assertEqual(1, len(events))
            self.assertEqual("plan_execute_blocked", events[0]["type"])
        finally:
            self._cleanup_yaml(tmpdir)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class OperationEventFeedTests(unittest.TestCase):
    """Regression: operation events should flow to AI panel."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_ai_panel(self):
        from app_gui.ui.ai_panel import AIPanel
        return AIPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_ai_panel_receives_operation_events(self):
        """AI panel should store and display operation events."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_executed",
            "timestamp": "2026-02-12T10:00:00",
            "ok": True,
            "stats": {"total": 1, "ok": 1, "blocked": 0},
            "summary": "All 1 operation(s) succeeded.",
        })

        self.assertEqual(1, len(panel.ai_operation_events))
        self.assertIn("succeeded", panel.ai_chat.toPlainText().lower())

    def test_ai_panel_limits_operation_events(self):
        """AI panel should limit stored operation events to prevent memory growth."""
        panel = self._new_ai_panel()

        for i in range(30):
            panel.on_operation_event({
                "type": "plan_executed",
                "timestamp": f"2026-02-12T10:{i:02d}:00",
                "ok": True,
                "stats": {"total": 1, "ok": 1},
                "summary": f"Event {i}",
            })

        self.assertLessEqual(len(panel.ai_operation_events), 20)

    def test_ai_panel_shows_blocked_events(self):
        """AI panel should show blocked execution events."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_execute_blocked",
            "timestamp": "2026-02-12T10:00:00",
            "blocked_count": 2,
        })

        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("blocked", chat_text)
        self.assertIn("2", chat_text)

    def test_ai_panel_shows_plan_executed_failure_details(self):
        """Failed plan_executed event should surface blocked details and rollback."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_executed",
            "timestamp": "2026-02-12T10:00:00",
            "ok": False,
            "stats": {"total": 3, "ok": 2, "blocked": 1},
            "summary": "Blocked: 1/3 items cannot execute.",
            "report": {
                "items": [
                    {
                        "blocked": True,
                        "message": "Record 2 failed",
                        "item": {"record_id": 2},
                    }
                ]
            },
            "rollback": {"attempted": True, "ok": True},
        })

        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("rejected atomically", chat_text)
        self.assertIn("record 2 failed", chat_text)
        self.assertIn("rollback", chat_text)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ExecuteFailurePreservesPlanTests(unittest.TestCase):
    """Regression: execute failure should preserve original plan for retry."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_execute_failure_preserves_entire_original_plan(self):
        """When execution fails, the entire original plan should be preserved."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {1}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
            _make_takeout_item(record_id=3, position=15),
        ]
        panel.add_plan_items(items)
        original_count = len(panel.plan_items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(original_count, len(panel.plan_items))
        record_ids = [item["record_id"] for item in panel.plan_items]
        self.assertEqual([1, 2, 3], record_ids)

    def test_execute_partial_failure_preserves_entire_plan(self):
        """Even if some items succeed before failure, entire plan should be preserved."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {2}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)
        original_ids = [item["record_id"] for item in panel.plan_items]

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(2, len(panel.plan_items))
        preserved_ids = [item["record_id"] for item in panel.plan_items]
        self.assertEqual(original_ids, preserved_ids)

    def test_execute_partial_failure_attempts_atomic_rollback(self):
        """Partial execute failure should rollback to first successful backup."""
        bridge = _RollbackAwareBridge()
        bridge.batch_should_fail = True
        bridge.record_thaw_fail_ids = {2}
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertTrue(bridge.rollback_called)
        self.assertEqual("/tmp/bak_1.yaml", bridge.rollback_backup_path)

    def test_execute_success_clears_plan(self):
        """When all items succeed, plan should be cleared."""
        bridge = _ConfigurableBridge()
        bridge.batch_should_fail = False
        panel = self._new_panel(bridge)

        items = [
            _make_takeout_item(record_id=1, position=5),
            _make_takeout_item(record_id=2, position=10),
        ]
        panel.add_plan_items(items)

        from unittest.mock import patch
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        self.assertEqual(0, len(panel.plan_items))
