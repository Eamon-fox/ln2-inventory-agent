import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtGui import QValidator
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app_gui.ui.ai_panel import AIPanel
    from app_gui.ui.overview_panel import OverviewPanel, TABLE_ROW_TINT_ROLE
    from app_gui.ui.operations_panel import OperationsPanel, _localized_action
    from app_gui.ui.utils import cell_color
    from app_gui.i18n import tr

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    Qt = None
    QValidator = None
    QApplication = None
    QMessageBox = None
    AIPanel = None
    OverviewPanel = None
    TABLE_ROW_TINT_ROLE = None
    OperationsPanel = None
    cell_color = None
    tr = None
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

    def generate_stats(self, yaml_path):
        return {"ok": True, "result": {"total_records": 0, "total_slots": 405, "occupied_slots": 0, "boxes": {}}}

    def search_records(self, yaml_path, **kwargs):
        return {"ok": True, "result": {"records": [], "count": 0}}

    def collect_timeline(self, yaml_path, **kwargs):
        return {"ok": True, "result": {"events": []}}


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
                    "position": 1,
                    "frozen_at": "2026-02-10",
                }
            }
        )

        record = panel._lookup_record(1)
        self.assertIsInstance(record, dict)
        self.assertEqual(1, int(record.get("id")))

    def test_operations_panel_add_entry_parses_positions_text(self):
        panel = self._new_operations_panel()

        # Simulate effective fields being loaded
        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False}
        ]
        panel._rebuild_custom_add_fields(panel._current_custom_fields)

        panel._add_custom_widgets["short_name"].setText("K562_clone12")
        panel.a_box.setValue(1)
        panel.a_positions.setText("30-32,35")

        panel.on_add_entry()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("add", item["action"])
        self.assertEqual([30, 31, 32, 35], item["payload"]["positions"])
        self.assertEqual("K562_clone12", item["payload"]["fields"].get("short_name"))

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

        # Each form has its own action-specific button
        self.assertEqual(tr("operations.add"), panel.a_apply_btn.text())
        self.assertEqual(tr("overview.takeout"), panel.t_apply_btn.text())
        self.assertEqual(tr("operations.addPlan"), panel.b_apply_btn.text())
        self.assertEqual(tr("operations.move"), panel.m_apply_btn.text())
        self.assertEqual(tr("operations.addPlan"), panel.bm_apply_btn.text())

        self.assertFalse(hasattr(panel, "a_dry_run"))
        self.assertFalse(hasattr(panel, "t_dry_run"))
        self.assertFalse(hasattr(panel, "b_dry_run"))

    def test_operations_panel_action_dropdown_supports_move(self):
        panel = self._new_operations_panel()

        single_actions = [panel.t_action.itemText(i) for i in range(panel.t_action.count())]
        batch_actions = [panel.b_action.itemText(i) for i in range(panel.b_action.count())]

        self.assertEqual(1, len(single_actions))
        self.assertEqual(1, len(batch_actions))
        self.assertEqual(tr("overview.takeout"), single_actions[0])
        self.assertEqual(tr("overview.takeout"), batch_actions[0])
        self.assertNotIn("Move", single_actions)
        self.assertNotIn("Move", batch_actions)

        mode_keys = [panel.op_mode_combo.itemData(i) for i in range(panel.op_mode_combo.count())]
        self.assertIn("move", mode_keys)
        self.assertNotIn("rollback", mode_keys)

    def test_rollback_controls_are_embedded_in_audit_tab(self):
        panel = self._new_operations_panel()

        self.assertEqual(-1, panel.op_mode_combo.findData("rollback"))
        self.assertFalse(hasattr(panel, "audit_backup_toggle_btn"))
        self.assertFalse(hasattr(panel, "audit_backup_panel"))
        self.assertFalse(hasattr(panel, "rb_backup_path"))
        self.assertFalse(hasattr(panel, "backup_table"))

    def test_rollback_staging_is_rejected_when_plan_has_other_items(self):
        panel = self._new_operations_panel()
        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from lib.plan_item_factory import build_rollback_plan_item

        panel.add_plan_items([_make_takeout_item(record_id=1, position=1)])
        panel.add_plan_items([build_rollback_plan_item(backup_path="/tmp/backup_a.bak", source="tests")])

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual("takeout", panel.plan_items[0].get("action"))
        self.assertTrue(any(tr("operations.planRejected") in msg for msg in messages))

    def test_plan_store_queued_refresh_keeps_ui_consistent_after_external_clear(self):
        from PySide6.QtCore import QMetaObject, Qt
        from lib.plan_item_factory import build_rollback_plan_item
        from lib.plan_store import PlanStore

        store = PlanStore()
        panel = OperationsPanel(
            bridge=object(),
            yaml_path_getter=lambda: "/tmp/inventory.yaml",
            plan_store=store,
        )

        def _on_change():
            QMetaObject.invokeMethod(panel, "_on_store_changed", Qt.QueuedConnection)

        store._on_change = _on_change

        store.add([build_rollback_plan_item(backup_path="/tmp/backup_a.bak", source="ai")])
        for _ in range(5):
            self._app.processEvents()

        self.assertEqual(1, store.count())
        self.assertEqual(1, panel.plan_table.rowCount())
        self.assertTrue(panel.plan_clear_btn.isEnabled())

        store.clear()
        for _ in range(5):
            self._app.processEvents()

        self.assertEqual(0, store.count())
        self.assertEqual(0, panel.plan_table.rowCount())
        self.assertFalse(panel.plan_table.isVisible())
        self.assertFalse(panel.plan_clear_btn.isEnabled())

    def test_operations_panel_move_tab_has_from_and_to_position(self):
        panel = self._new_operations_panel()

        self.assertTrue(hasattr(panel, "m_to_position"))
        self.assertTrue(hasattr(panel, "m_to_box"))
        self.assertEqual(4, panel.bm_table.columnCount())
        self.assertEqual(tr("operations.from"), panel.bm_table.horizontalHeaderItem(1).text())
        self.assertEqual(tr("operations.to"), panel.bm_table.horizontalHeaderItem(2).text())
        self.assertEqual(tr("operations.toBox"), panel.bm_table.horizontalHeaderItem(3).text())

    def test_operations_panel_single_move_passes_to_position(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            11: {"id": 11, "parent_cell_line": "K562", "short_name": "K562-move",
                 "box": 2, "position": 5},
        })

        panel.m_id.setValue(11)
        # Source position comes from record, just set target
        panel.m_to_position.setText("8")
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
                 "box": 3, "position": 23},
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
        self.assertEqual(tr("operations.showBatchMove"), panel.m_batch_toggle_btn.text())

        panel.m_batch_toggle_btn.setChecked(True)
        self.assertFalse(panel.m_batch_group.isHidden())
        self.assertEqual(tr("operations.hideBatchMove"), panel.m_batch_toggle_btn.text())

    def test_operations_panel_emits_completion_on_success_without_dry_run_gate(self):
        panel = self._new_operations_panel()
        emitted = []
        panel.operation_completed.connect(lambda success: emitted.append(bool(success)))

        panel._handle_response({"ok": True, "result": {"dry_run": True}}, "Single Operation")

        self.assertEqual([True], emitted)

    def test_operations_panel_prefill_context_hides_status_when_context_valid(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                5: {
                    "id": 5,
                    "parent_cell_line": "K562",
                    "short_name": "K562_RTCB_dTAG_clone12",
                    "box": 1,
                    "position": 30,
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertTrue(panel.t_ctx_status.isHidden())
        self.assertEqual(
            tr("operations.boxSourceText", box=1, position=30),
            panel.t_ctx_source.text(),
        )

    def test_operations_panel_prefill_context_shows_status_when_record_missing(self):
        panel = self._new_operations_panel()

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertFalse(panel.t_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.t_ctx_status.text())

    def test_operations_panel_set_move_prefill_fills_move_form(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            7: {"id": 7, "parent_cell_line": "K562", "short_name": "K562_move",
                "box": 2, "position": 15},
        })

        panel.set_move_prefill({"box": 2, "position": 15, "record_id": 7})

        self.assertEqual(7, panel.m_id.value())
        # from_position is now inferred from record, not a separate widget
        self.assertEqual("move", panel.current_operation_mode)

    def test_operations_panel_batch_section_collapsed_by_default(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual(tr("operations.showBatch"), panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(True)
        self.assertFalse(panel.t_batch_group.isHidden())
        self.assertEqual(tr("operations.hideBatch"), panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(False)
        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual(tr("operations.showBatch"), panel.t_batch_toggle_btn.text())

    def test_operations_panel_export_full_csv_appends_csv_extension(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        from unittest.mock import patch

        with patch(
            "app_gui.ui.operations_panel.QFileDialog.getSaveFileName",
            return_value=("/tmp/full_export", "CSV Files (*.csv)"),
        ):
            panel.on_export_inventory_csv()

        self.assertEqual(
            {
                "yaml_path": "/tmp/inventory.yaml",
                "output_path": "/tmp/full_export.csv",
            },
            bridge.last_export_payload,
        )

    def test_overview_click_prefills_background_only(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "position": 1,
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        emitted_thaw = []
        emitted_move = []
        emitted_add = []
        panel.request_prefill.connect(lambda payload: emitted_thaw.append(payload))
        panel.request_move_prefill.connect(lambda payload: emitted_move.append(payload))
        panel.request_add_prefill.connect(lambda payload: emitted_add.append(payload))

        emitted_bg_add = []
        emitted_bg_thaw = []
        panel.request_add_prefill_background.connect(lambda payload: emitted_bg_add.append(payload))
        panel.request_prefill_background.connect(lambda payload: emitted_bg_thaw.append(payload))

        panel.on_cell_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        # Occupied cell: only emits background thaw prefill, not add
        self.assertEqual([], emitted_bg_add)
        self.assertEqual([{"box": 1, "position": 1, "record_id": 5}], emitted_bg_thaw)
        self.assertEqual([], emitted_thaw)
        self.assertEqual([], emitted_move)
        self.assertEqual([], emitted_add)

    def test_overview_click_empty_slot_prefills_add_background_only(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        panel.overview_pos_map = {}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record=None)

        emitted_add = []
        emitted_bg_add = []
        emitted_bg_thaw = []
        status_messages = []
        panel.request_add_prefill.connect(lambda payload: emitted_add.append(payload))
        panel.request_add_prefill_background.connect(lambda payload: emitted_bg_add.append(payload))
        panel.request_prefill_background.connect(lambda payload: emitted_bg_thaw.append(payload))
        panel.status_message.connect(lambda msg, timeout: status_messages.append((msg, timeout)))

        panel.on_cell_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1}], emitted_bg_add)
        self.assertEqual([], emitted_bg_thaw)
        self.assertEqual([], emitted_add)
        self.assertEqual(1, len(status_messages))
        # Button uses CSS variables for styling; verify it has a stylesheet applied
        self.assertTrue(len(button.styleSheet()) > 0)

    def test_overview_hover_scales_cell_without_shifting_neighbors(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        panel.show()
        self._app.processEvents()

        left = panel.overview_cells[(1, 1)]
        right = panel.overview_cells[(1, 2)]
        left._hover_duration_ms = 0

        left_base = left.geometry()
        right_base = right.geometry()
        self.assertGreater(left_base.width(), 0)
        self.assertGreater(left_base.height(), 0)

        left.start_hover_visual()
        self._app.processEvents()

        left_hover_proxy = left._hover_proxy
        self.assertIsNotNone(left_hover_proxy)
        self.assertTrue(left_hover_proxy.isVisible())
        left_hover = left_hover_proxy.geometry()
        self.assertGreater(left_hover.width(), left_base.width())
        self.assertGreater(left_hover.height(), left_base.height())
        self.assertEqual(right_base, right.geometry())

        left.stop_hover_visual()
        self._app.processEvents()
        self.assertFalse(left_hover_proxy.isVisible())
        self.assertEqual(left_base, left.geometry())

    def test_overview_zoom_resets_cell_hover_geometry(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        panel.show()
        self._app.processEvents()

        button = panel.overview_cells[(1, 1)]
        button._hover_duration_ms = 0
        base_size = button.size()

        button.start_hover_visual()
        self._app.processEvents()
        hover_proxy = button._hover_proxy
        self.assertIsNotNone(hover_proxy)
        self.assertTrue(hover_proxy.isVisible())
        hovered_size = hover_proxy.size()
        self.assertGreater(hovered_size.width(), base_size.width())

        panel._set_zoom(1.2)
        self._app.processEvents()

        expected_size = max(12, int(panel._base_cell_size * panel._zoom_level))
        self.assertFalse(hover_proxy.isVisible())
        self.assertEqual(expected_size, button.width())
        self.assertEqual(expected_size, button.height())

    def test_overview_hover_animation_warmed_after_refresh(self):
        """Verify hover animation system is warmed after initial data load."""
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        panel.show()

        # Before warming, proxy should not exist.
        button = panel.overview_cells[(1, 1)]
        self.assertIsNone(button._hover_proxy)
        self.assertFalse(panel._hover_warmed)

        # Call warm-up directly
        panel._warm_hover_animation()
        self._app.processEvents()

        # Verify warming completed
        self.assertTrue(panel._hover_warmed)

        # Verify the first cell's proxy was created during warm-up
        self.assertIsNotNone(button._hover_proxy)

        # Verify calling warm-up again is idempotent (no error on second call)
        panel._warm_hover_animation()
        self.assertTrue(panel._hover_warmed)

    def test_overview_hover_warm_skipped_when_no_cells(self):
        """Verify warm-up is safely skipped when overview_cells is empty."""
        panel = self._new_overview_panel()
        # No cells built
        self.assertFalse(panel._hover_warmed)

        # Should not crash and should NOT mark as warmed (since no cells exist to warm)
        panel._warm_hover_animation()
        self._app.processEvents()
        # When no cells exist, warm returns early without marking _hover_warmed
        # This is correct behavior: we only mark warmed when we actually warmed something
        self.assertFalse(panel._hover_warmed)

    def test_overview_hover_warm_idempotent(self):
        """Verify warm-up can be called multiple times without errors."""
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        panel.show()

        # Multiple calls should not crash
        panel._warm_hover_animation()
        panel._warm_hover_animation()
        panel._warm_hover_animation()
        self._app.processEvents()

        self.assertTrue(panel._hover_warmed)

    def test_overview_hover_reuses_single_animation_object(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        panel.show()
        self._app.processEvents()

        button = panel.overview_cells[(1, 1)]
        button._hover_duration_ms = 0

        button.start_hover_visual()
        self._app.processEvents()
        button.stop_hover_visual()
        self._app.processEvents()

        proxy = button._hover_proxy
        self.assertIsNotNone(proxy)

        def _animation_count():
            return sum(1 for child in proxy.children() if child.__class__.__name__ == "QPropertyAnimation")

        baseline_count = _animation_count()
        self.assertEqual(1, baseline_count)

        for _ in range(40):
            button.start_hover_visual()
            self._app.processEvents()
            button.stop_hover_visual()
            self._app.processEvents()

        self.assertEqual(baseline_count, _animation_count())

    def test_overview_hover_stop_hides_proxy_immediately(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        panel.show()
        self._app.processEvents()

        button = panel.overview_cells[(1, 1)]
        button._hover_duration_ms = 300

        button.start_hover_visual()
        self._app.processEvents()
        proxy = button._hover_proxy
        self.assertIsNotNone(proxy)
        self.assertTrue(proxy.isVisible())

        button.stop_hover_visual()
        self.assertFalse(proxy.isVisible())

    def test_overview_context_menu_record_stages_takeout_item(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "position": 1,
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        staged_items = []
        panel.plan_items_requested.connect(lambda payload: staged_items.extend(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_takeout = MagicMock()
            mock_menu.addAction.side_effect = [mock_act_takeout]
            mock_menu.exec.return_value = mock_act_takeout
            panel.on_cell_context_menu(1, 1, button.mapToGlobal(button.rect().center()))

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual(1, len(staged_items))
        self.assertEqual("takeout", staged_items[0].get("action"))
        self.assertEqual(5, staged_items[0].get("record_id"))

    def test_overview_context_menu_record_does_not_emit_move_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "position": 1,
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
            mock_act_takeout = MagicMock()
            mock_menu.addAction.side_effect = [mock_act_takeout]
            mock_menu.exec.return_value = mock_act_takeout
            panel.on_cell_context_menu(1, 1, button.mapToGlobal(button.rect().center()))

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([], emitted_move)

    def test_overview_context_menu_empty_slot_emits_add_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        panel.overview_pos_map = {}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record=None)

        emitted_add = []
        panel.request_add_prefill.connect(lambda payload: emitted_add.append(payload))

        from unittest.mock import patch, MagicMock
        with patch("app_gui.ui.overview_panel.QMenu") as MockMenu:
            mock_menu = MagicMock()
            MockMenu.return_value = mock_menu
            mock_act_add = MagicMock()
            mock_menu.addAction.return_value = mock_act_add
            mock_menu.exec.return_value = mock_act_add
            panel.on_cell_context_menu(1, 1, button.mapToGlobal(button.rect().center()))

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1}], emitted_add)

    def test_operations_background_prefill_updates_fields_without_switch_mode(self):
        panel = self._new_operations_panel()
        panel.set_mode("move")

        panel.set_add_prefill_background({"box": 2, "position": 9})
        self.assertEqual(2, panel.a_box.value())
        self.assertEqual("9", panel.a_positions.text())
        # set_add_prefill_background now switches to add mode
        self.assertEqual("add", panel.current_operation_mode)

        panel.set_mode("move")
        panel.set_prefill_background({"record_id": 11, "position": 5})
        self.assertEqual(11, panel.t_id.value())
        # set_prefill_background switches to thaw mode
        self.assertEqual("thaw", panel.current_operation_mode)

    # --- Plan tab tests ---

    def test_plan_tab_exists_in_mode_selector(self):
        panel = self._new_operations_panel()
        mode_keys = [panel.op_mode_combo.itemData(i) for i in range(panel.op_mode_combo.count())]
        # "plan" is no longer a separate mode; plan table is always visible below forms
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
        # Column 0 now shows merged action with ID
        action_text = panel.plan_table.item(0, 0).text()
        self.assertIn("takeout", action_text.lower())
        self.assertIn("10", action_text)  # ID should be in the text
        # Column 1 now shows position (box:position)
        pos_text = panel.plan_table.item(0, 1).text()
        self.assertEqual("1:5", pos_text)

        # Badge should show count
        idx = panel.op_mode_combo.findData("plan")
        if idx >= 0:
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
                "source": "human",
                "payload": {},
            },
        ]
        panel.add_plan_items(invalid_items)

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(any("rejected" in m.lower() for m in messages))
        self.assertFalse(panel.plan_feedback_label.isHidden())
        self.assertTrue(panel.plan_feedback_label.text().strip())

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
                "box": 2, "position": 10},
        })

        panel.t_id.setValue(5)
        # position combo is auto-populated by refresh; select position 10
        idx = panel.t_position.findData(10)
        if idx >= 0:
            panel.t_position.setCurrentIndex(idx)
        # Select Takeout action by data value
        action_idx = panel.t_action.findData("Takeout")
        if action_idx >= 0:
            panel.t_action.setCurrentIndex(action_idx)
        panel.on_record_thaw()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(2, item["box"])
        self.assertEqual(10, item["position"])
        self.assertEqual(5, item["record_id"])

    def test_ai_panel_append_chat_falls_back_when_insert_markdown_missing(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel._append_chat("You", "hello")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("append", call_names)

    def test_ai_panel_defaults_model_to_deepseek_chat(self):
        panel = self._new_ai_panel()

        # ai_model and ai_thinking_enabled are now managed via Settings
        self.assertIsNotNone(panel.ai_model)
        self.assertIsNotNone(panel.ai_thinking_enabled)
        self.assertFalse(panel.ai_stream_has_thought)

    def test_ai_panel_thought_chunk_renders_inline_with_answer_stream(self):
        panel = self._new_ai_panel()
        panel.ai_stream_render_interval_sec = 0.0

        panel.on_progress({"event": "run_start", "trace_id": "trace-thought"})
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-thought",
                "data": "model thought",
                "meta": {"channel": "thought"},
            }
        )
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-thought",
                "data": " final answer",
                "meta": {"channel": "answer"},
            }
        )

        rendered = panel.ai_chat.toPlainText()
        self.assertIn("model thought", rendered)
        self.assertIn("final answer", rendered)
        self.assertIn("\n", rendered)
        self.assertTrue(panel.ai_stream_has_thought)

    def test_ai_panel_append_chat_prefers_insert_markdown_when_available(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatWithMarkdown()

        panel._append_chat("Agent", "**bold**")

        call_names = [name for name, _value in panel.ai_chat.calls]
        # _append_chat now combines header+body HTML and uses append()
        self.assertIn("append", call_names)
        # Verify bold was converted to HTML (mistune uses <strong>)
        appended_values = [v for n, v in panel.ai_chat.calls if n == "append"]
        self.assertTrue(any("<strong>" in str(v) or "<b>" in str(v) for v in appended_values))

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

    def test_ai_panel_finished_renders_markdown_for_thought_and_answer(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-md-thought"})
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-md-thought",
                "data": "**plan**",
                "meta": {"channel": "thought"},
            }
        )
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-md-thought",
                "data": "**final**",
                "meta": {"channel": "answer"},
            }
        )
        panel.on_finished({"ok": True, "result": {"final": "**final**", "trace_id": "trace-md-thought"}})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("plan", rendered_text)
        self.assertIn("final", rendered_text)
        self.assertNotIn("**plan**", rendered_text)
        self.assertNotIn("**final**", rendered_text)

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

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
        self.assertIn("query_thaw_events", merged)
        self.assertIn("OK", merged)

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

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
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
    """Test that AgentToolRunner stages write operations when plan_store is set."""

    def setUp(self):
        from lib.plan_store import PlanStore
        self.store = PlanStore()

    def _make_runner(self, yaml_path="/tmp/inventory.yaml"):
        from agent.tool_runner import AgentToolRunner
        return AgentToolRunner(
            yaml_path=yaml_path,
            plan_store=self.store,
        )

    def test_read_tool_not_intercepted(self):
        runner = self._make_runner()
        result = runner.run("query_inventory", {"cell": "K562"})
        # Should execute normally (may fail if YAML not found, but not staged)
        self.assertEqual(0, self.store.count())

    def test_add_entry_staged(self):
        runner = self._make_runner()
        result = runner.run("add_entry", {
            "box": 1,
            "positions": [30],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": "K562",
                "short_name": "K562_test",
            },
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, self.store.count())
        item = self.store.list_items()[0]
        self.assertEqual("add", item["action"])
        self.assertEqual("ai", item["source"])
        self.assertEqual(1, item["box"])

    def test_record_thaw_staged(self):
        runner = self._make_runner()
        result = runner.run("record_thaw", {
            "record_id": 5,
            "position": 10,
            "date": "2026-02-10",
            "action": "Takeout",
        })
        self.assertTrue(result.get("staged"))
        self.assertEqual(1, self.store.count())
        item = self.store.list_items()[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(5, item["record_id"])
        self.assertEqual(10, item["position"])

    def test_without_plan_sink_executes_normally(self):
        from agent.tool_runner import AgentToolRunner
        runner = AgentToolRunner(
            yaml_path="/tmp/inventory.yaml",
        )
        # Without plan_store, add_entry should attempt execution (may error but not stage)
        result = runner.run("add_entry", {
            "box": 1,
            "positions": [1],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": "K562",
                "short_name": "test",
            },
        })
        self.assertFalse(result.get("staged", False))
        self.assertEqual(0, self.store.count())


# ── Regression tests: plan dedup + execute fallback ──────────────


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

    def rollback(self, yaml_path, backup_path=None, execution_mode=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        _ = execution_mode
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
        """When batch_thaw fails for moves, items are marked blocked (no individual fallback)."""
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

        # batch_thaw called once (failed), no individual fallback
        self.assertEqual(1, len(bridge.batch_thaw_calls))
        self.assertEqual(0, len(bridge.record_thaw_calls))
        # Plan preserved on failure
        self.assertEqual(2, len(panel.plan_items))

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
        """Phase 3: batch failure for takeout marks items blocked (no individual fallback)."""
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

        # batch failed, no individual fallback; plan preserved
        self.assertEqual(0, len(bridge.record_thaw_calls))
        self.assertEqual(2, len(panel.plan_items))

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
        panel.clear_plan()
        
        # Now execute again — this time all succeed
        bridge.batch_should_fail = False
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

    def rollback(self, yaml_path, backup_path=None, execution_mode=None):
        self.rollback_called = True
        self.rollback_backup_path = backup_path
        _ = execution_mode
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
class RollbackConfirmationDialogTests(unittest.TestCase):
    """Regression: rollback confirmations should show complete backup context."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml_and_backup(self):
        import tempfile
        from lib.yaml_ops import create_yaml_backup, write_yaml

        tmpdir = tempfile.mkdtemp(prefix="ln2_rb_confirm_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {
                "meta": {"box_layout": {"rows": 9, "cols": 9}},
                "inventory": [
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "A",
                        "box": 1,
                        "position": 5,
                        "frozen_at": "2025-01-01",
                    }
                ],
            },
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        backup_path = str(create_yaml_backup(yaml_path))
        return yaml_path, tmpdir, backup_path

    def _cleanup_yaml(self, tmpdir):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_plan_rollback_confirmation_includes_full_paths_and_source(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_FakeOperationsBridge(), yaml_path_getter=lambda: yaml_path)
            panel.add_plan_items(
                [
                    {
                        "action": "rollback",
                        "box": 0,
                        "position": 1,
                        "record_id": None,
                        "source": "human",
                        "payload": {
                            "backup_path": backup_path,
                            "source_event": {
                                "timestamp": "2026-02-12T09:00:00",
                                "action": "record_thaw",
                                "trace_id": "trace-audit-1",
                            },
                        },
                    }
                ]
            )

            captured = {}

            def _capture_info(_self, text):
                captured["info"] = text

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr), patch.object(
                QMessageBox,
                "setInformativeText",
                new=_capture_info,
            ), patch.object(QMessageBox, "exec", return_value=QMessageBox.No):
                panel.execute_plan()

            info = str(captured.get("info") or "")
            self.assertIn(os.path.abspath(yaml_path), info)
            self.assertIn(os.path.abspath(backup_path), info)
            self.assertIn("trace-audit-1", info)
            self.assertIn("record_thaw", info)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_undo_confirmation_includes_backup_and_yaml_paths(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_UndoBridge(), yaml_path_getter=lambda: yaml_path)
            panel._last_operation_backup = backup_path

            captured = {}

            def _capture_info(_self, text):
                captured["info"] = text

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr), patch.object(
                QMessageBox,
                "setInformativeText",
                new=_capture_info,
            ), patch.object(QMessageBox, "exec", return_value=QMessageBox.No):
                panel.on_undo_last()

            info = str(captured.get("info") or "")
            self.assertIn(os.path.abspath(yaml_path), info)
            self.assertIn(os.path.abspath(backup_path), info)
            self.assertIn(os.path.basename(backup_path), info)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_plan_table_rollback_row_shows_dense_context(self):
        yaml_path, tmpdir, backup_path = self._seed_yaml_and_backup()
        try:
            panel = OperationsPanel(bridge=_FakeOperationsBridge(), yaml_path_getter=lambda: yaml_path)

            rollback_item = {
                "action": "rollback",
                "box": 0,
                "position": 1,
                "record_id": None,
                "source": "human",
                "payload": {
                    "backup_path": backup_path,
                    "source_event": {
                        "timestamp": "2026-02-12T09:00:00",
                        "action": "record_thaw",
                        "trace_id": "trace-audit-1",
                    },
                },
            }

            def _fake_tr(key, **kwargs):
                if kwargs:
                    detail = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
                    return f"{key}|{detail}"
                return key

            from unittest.mock import patch

            with patch("app_gui.ui.operations_panel.tr", side_effect=_fake_tr):
                panel.add_plan_items([rollback_item])

            self.assertEqual(1, panel.plan_table.rowCount())
            headers = [
                panel.plan_table.horizontalHeaderItem(i).text()
                for i in range(panel.plan_table.columnCount())
            ]
            note_col = headers.index(_fake_tr("operations.colNote"))
            note_item = panel.plan_table.item(0, note_col)

            self.assertIsNotNone(note_item)
            # Note contains rollback info with trace_id
            self.assertIn("trace-audit-1", note_item.text())

            # Tooltip has full details
            tooltip = note_item.toolTip()
            self.assertIn(os.path.abspath(yaml_path), tooltip)
            self.assertIn(os.path.abspath(backup_path), tooltip)
            self.assertIn("record_thaw", tooltip)
        finally:
            self._cleanup_yaml(tmpdir)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class PrintPlanRegressionTests(unittest.TestCase):
    """Regression: printing should support recently executed plans."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self, bridge):
        return OperationsPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_print_last_executed_uses_recent_execution(self):
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
        self.assertEqual(2, len(panel._last_executed_plan))

        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_last_executed()

        open_url.assert_called_once()

    def test_print_plan_does_not_fallback_to_last_executed(self):
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
        self.assertEqual(2, len(panel._last_executed_plan))

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_plan()

        open_url.assert_not_called()
        self.assertTrue(any(tr("operations.noCurrentPlanToPrint") in msg for msg in messages))

    def test_print_last_executed_errors_without_recent_execution(self):
        bridge = _UndoBridge()
        panel = self._new_panel(bridge)

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from unittest.mock import patch
        with patch("app_gui.ui.operations_panel.QDesktopServices.openUrl", return_value=True) as open_url:
            panel.print_last_executed()

        open_url.assert_not_called()
        self.assertTrue(any(tr("operations.noLastExecutedToPrint") in msg for msg in messages))


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
@unittest.skip("Audit functionality has been refactored/removed from OperationsPanel")
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

        self.assertTrue(any(tr("operations.selectAuditRowsFirst") in msg for msg in messages))

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

    def test_stage_rollback_from_selected_audit_requires_single_row(self):
        panel = self._new_panel()
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_thaw",
                "status": "success",
                "backup_path": "/tmp/inventory.yaml.20260212-090000.bak",
            },
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "batch_thaw",
                "status": "success",
                "backup_path": "/tmp/inventory.yaml.20260212-090100.bak",
            },
        ]
        self._seed_audit_rows(panel, events)
        panel.audit_table.selectAll()

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))
        panel.on_stage_rollback_from_selected_audit()

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(any(tr("operations.selectSingleAuditRow") in msg for msg in messages))

    def test_stage_rollback_from_selected_audit_requires_backup_path(self):
        panel = self._new_panel()
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_thaw",
                "status": "success",
                "backup_path": "",
            }
        ]
        self._seed_audit_rows(panel, events)
        panel.audit_table.selectRow(0)

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))
        panel.on_stage_rollback_from_selected_audit()

        self.assertEqual(0, len(panel.plan_items))
        self.assertTrue(any(tr("operations.selectedAuditNoBackup") in msg for msg in messages))

    def test_stage_rollback_from_selected_audit_stages_plan_item(self):
        panel = self._new_panel()
        backup_path = "/tmp/inventory.yaml.20260212-090000.bak"
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_thaw",
                "status": "success",
                "trace_id": "trace-audit-1",
                "session_id": "session-audit-1",
                "actor_id": "gui-user",
                "channel": "gui",
                "backup_path": backup_path,
            }
        ]
        self._seed_audit_rows(panel, events)
        panel.audit_table.selectRow(0)

        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))
        panel.on_stage_rollback_from_selected_audit()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("rollback", item.get("action"))
        payload = item.get("payload") or {}
        self.assertEqual(backup_path, payload.get("backup_path"))

        source_event = payload.get("source_event") or {}
        self.assertEqual("2026-02-12T09:00:00", source_event.get("timestamp"))
        self.assertEqual("record_thaw", source_event.get("action"))
        self.assertEqual("trace-audit-1", source_event.get("trace_id"))

        expected = tr("operations.auditRollbackStaged", backup=os.path.basename(backup_path))
        self.assertTrue(any(expected in msg for msg in messages))


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
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_add_items_triggers_preflight(self):
        """Adding items to plan should trigger preflight validation."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
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
        """Blocked items should be rejected at staging time."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            self.assertEqual(0, panel.plan_table.rowCount())
            self.assertEqual(0, len(panel.plan_items))
            self.assertFalse(panel.plan_exec_btn.isEnabled())
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_button_disabled_when_blocked(self):
        """Execute button should be disabled when plan has blocked items."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
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
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
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
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup_yaml(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_execute_blocked_does_not_call_bridge(self):
        """When staging rejects invalid items, execute remains a no-op."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            items = [_make_takeout_item(record_id=999, position=5)]
            panel.add_plan_items(items)

            messages = []
            panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

            panel.execute_plan()

            self.assertTrue(messages)
            self.assertIsNone(bridge.last_batch_payload)
        finally:
            self._cleanup_yaml(tmpdir)

    def test_execute_blocked_emits_operation_event(self):
        """Execute with empty plan emits a normalized system notice."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
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
            self.assertEqual("system_notice", events[0].get("type"))
            self.assertEqual("plan.execute.empty", events[0].get("code"))
        finally:
            self._cleanup_yaml(tmpdir)

    def test_stage_blocked_emits_system_notice_event(self):
        """Staging rejection should emit a system notice with blocked details."""
        records = [{"id": 1, "parent_cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"}]
        yaml_path, tmpdir = self._seed_yaml(records)

        try:
            bridge = _FakeOperationsBridge()
            panel = OperationsPanel(bridge=bridge, yaml_path_getter=lambda: yaml_path)

            events = []
            panel.operation_event.connect(lambda ev: events.append(ev))

            # record_id=999 does not exist; staging must be blocked.
            panel.add_plan_items([_make_takeout_item(record_id=999, position=5)])

            self.assertTrue(events)
            latest = events[-1]
            self.assertEqual("system_notice", latest.get("type"))
            self.assertEqual("plan.stage.blocked", latest.get("code"))
            self.assertTrue((latest.get("data") or {}).get("blocked_items"))
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
        """AI panel should normalize operation events to system notices."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_executed",
            "timestamp": "2026-02-12T10:00:00",
            "ok": True,
            "stats": {"total": 1, "ok": 1, "blocked": 0},
            "summary": "All 1 operation(s) succeeded.",
        })

        self.assertEqual(1, len(panel.ai_operation_events))
        self.assertEqual("system_notice", panel.ai_operation_events[0].get("type"))
        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("succeeded", chat_text)
        self.assertIn("plan.execute.result", chat_text)

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
        """Failed plan_executed event should surface summary and raw details."""
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
        self.assertIn("blocked: 1/3", chat_text)
        self.assertTrue(panel.ai_collapsible_blocks)
        details_text = str(panel.ai_collapsible_blocks[-1].get("content", "")).lower()
        self.assertIn("record 2 failed", details_text)
        self.assertIn("rollback", details_text)

    def test_ai_panel_system_notice_prefers_compact_operation_details(self):
        """System notices should show concise operation lines, not raw JSON dumps."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "system_notice",
            "code": "plan.execute.result",
            "level": "success",
            "text": "已应用：1/1 个操作。",
            "data": {
                "stats": {"total": 1, "applied": 1, "failed": 0, "blocked": 0, "remaining": 0},
                "sample": ["OK: takeout 18 @ Box 1:18 | cell_line=U2OS, short_name=U2OS_backup_stock"],
                "report": {
                    "backup_path": "/tmp/demo.bak",
                    "items": [{"ok": True, "item": {"action": "takeout", "record_id": 18, "box": 1, "position": 18}}],
                },
            },
        })

        self.assertTrue(panel.ai_collapsible_blocks)
        details_text = str(panel.ai_collapsible_blocks[-1].get("content", ""))
        self.assertIn("Operations (1)", details_text)
        self.assertIn("takeout 18", details_text.lower())
        self.assertNotIn('"report"', details_text)


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
        """When batch fails, all items are blocked — no partial success, no rollback needed."""
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

        # With new executor, batch failure marks all items blocked — no partial success
        # so no rollback is attempted (no backup_path from any OK item)
        self.assertFalse(bridge.rollback_called)
        # Plan is preserved on failure
        self.assertEqual(2, len(panel.plan_items))

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


# ===========================================================================
# cell_line dropdown and color_key filter tests
# ===========================================================================

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class CellLineDropdownTests(unittest.TestCase):
    """Tests for cell_line QComboBox in operations panel."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_cell_line_combo_exists(self):
        """Operations panel should have a cell_line combo box."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        self.assertTrue(hasattr(panel, "a_cell_line"))
        from PySide6.QtWidgets import QComboBox
        self.assertIsInstance(panel.a_cell_line, QComboBox)

    def test_cell_line_combo_starts_with_empty(self):
        """Cell line combo should start with an empty option."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        self.assertEqual("", panel.a_cell_line.itemText(0))

    def test_refresh_cell_line_options_populates_combo(self):
        """_refresh_cell_line_options should populate from meta."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        meta = {"cell_line_options": ["K562", "HeLa", "NCCIT"]}
        panel._refresh_cell_line_options(meta)
        # 1 empty + 3 options
        self.assertEqual(4, panel.a_cell_line.count())
        self.assertEqual("K562", panel.a_cell_line.itemText(1))
        self.assertEqual("HeLa", panel.a_cell_line.itemText(2))
        self.assertEqual("NCCIT", panel.a_cell_line.itemText(3))

    def test_refresh_cell_line_options_preserves_selection(self):
        """Refreshing options should preserve the current selection."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        meta = {"cell_line_options": ["K562", "HeLa"]}
        panel._refresh_cell_line_options(meta)
        panel.a_cell_line.setCurrentIndex(2)  # HeLa
        self.assertEqual("HeLa", panel.a_cell_line.currentText())

        # Refresh again with same options
        panel._refresh_cell_line_options(meta)
        self.assertEqual("HeLa", panel.a_cell_line.currentText())

    def test_refresh_cell_line_options_defaults_when_no_meta(self):
        """Without meta options, should use DEFAULT_CELL_LINE_OPTIONS."""
        from lib.custom_fields import DEFAULT_CELL_LINE_OPTIONS
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        panel._refresh_cell_line_options({})
        # 1 empty + len(defaults)
        self.assertEqual(1 + len(DEFAULT_CELL_LINE_OPTIONS), panel.a_cell_line.count())

    def test_apply_meta_update_switches_required_mode_immediately(self):
        """Changing cell_line_required should update add-form combo immediately."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

        panel.apply_meta_update({
            "cell_line_required": True,
            "cell_line_options": ["K562", "HeLa"],
            "custom_fields": [],
        })
        self.assertEqual(2, panel.a_cell_line.count())
        self.assertEqual("K562", panel.a_cell_line.itemText(0))

        panel.apply_meta_update({
            "cell_line_required": False,
            "cell_line_options": ["K562", "HeLa"],
            "custom_fields": [],
        })
        self.assertEqual(3, panel.a_cell_line.count())
        self.assertEqual("", panel.a_cell_line.itemText(0))
        self.assertEqual("K562", panel.a_cell_line.itemText(1))

    def test_context_cell_line_uses_lockable_edit_fields(self):
        """Thaw/move cell_line context should support lock-based inline editing."""
        from PySide6.QtWidgets import QLineEdit

        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        self.assertIsInstance(panel.t_ctx_cell_line, QLineEdit)
        self.assertIsInstance(panel.m_ctx_cell_line, QLineEdit)
        self.assertTrue(panel.t_ctx_cell_line.isReadOnly())
        self.assertTrue(panel.m_ctx_cell_line.isReadOnly())

    def test_context_cell_line_prefix_validator_and_completer(self):
        """Cell line edit should allow only option prefixes and exact option values."""
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        panel.apply_meta_update({
            "cell_line_required": True,
            "cell_line_options": ["K562", "HeLa", "NCCIT"],
            "custom_fields": [],
        })

        validator = panel.t_ctx_cell_line.validator()
        self.assertIsInstance(validator, QValidator)

        state, _, _ = validator.validate("K", 1)
        self.assertIn(state, (QValidator.Intermediate, QValidator.Acceptable))

        state, _, _ = validator.validate("X", 1)
        self.assertEqual(QValidator.Invalid, state)

        state, _, _ = validator.validate("hela", 4)
        self.assertEqual(QValidator.Acceptable, state)

        completer = panel.t_ctx_cell_line.completer()
        self.assertIsNotNone(completer)
        self.assertEqual(Qt.MatchStartsWith, completer.filterMode())

    def test_add_cell_line_combo_limits_popup_height(self):
        panel = OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")
        opts = [f"Cell-{i:02d}" for i in range(30)]
        panel._refresh_cell_line_options({
            "cell_line_required": True,
            "cell_line_options": opts,
        })

        self.assertEqual(10, panel.a_cell_line.maxVisibleItems())
        view = panel.a_cell_line.view()
        self.assertIsNotNone(view)
        self.assertEqual(240, view.maximumHeight())


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class OverviewColorKeyFilterTests(unittest.TestCase):
    """Tests for overview panel filtering by color_key."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records, meta_extra=None):
        import tempfile, shutil
        tmpdir = tempfile.mkdtemp(prefix="ln2_ov_ck_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        meta = {"box_layout": {"rows": 9, "cols": 9}}
        if meta_extra:
            meta.update(meta_extra)
        from lib.yaml_ops import write_yaml
        write_yaml(
            {"meta": meta, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup(self, tmpdir):
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_filter_dropdown_uses_color_key_values(self):
        """Filter dropdown should show unique values of the color_key field."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
            {"id": 3, "cell_line": "K562", "short_name": "C", "box": 1, "position": 3, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            items = [panel.ov_filter_cell.itemText(i) for i in range(panel.ov_filter_cell.count())]
            self.assertIn(tr("overview.allCells"), items)
            self.assertIn("K562", items)
            self.assertIn("HeLa", items)
        finally:
            self._cleanup(tmpdir)

    def test_filter_by_color_key_hides_non_matching(self):
        """Selecting a color_key value should filter the dropdown correctly."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "B", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            # Verify pos_map is populated
            self.assertIn((1, 1), panel.overview_pos_map)
            self.assertIn((1, 2), panel.overview_pos_map)

            # Verify color_key_value property is set on buttons
            btn_1 = panel.overview_cells.get((1, 1))
            btn_2 = panel.overview_cells.get((1, 2))
            self.assertIsNotNone(btn_1)
            self.assertIsNotNone(btn_2)
            self.assertEqual("K562", btn_1.property("color_key_value"))
            self.assertEqual("HeLa", btn_2.property("color_key_value"))
        finally:
            self._cleanup(tmpdir)

    def test_color_key_custom_field(self):
        """color_key can be set to a user field like short_name."""
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "Alpha", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "K562", "short_name": "Beta", "box": 1, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "short_name"})
        try:
            from app_gui.tool_bridge import GuiToolBridge
            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            items = [panel.ov_filter_cell.itemText(i) for i in range(panel.ov_filter_cell.count())]
            self.assertIn("Alpha", items)
            self.assertIn("Beta", items)
        finally:
            self._cleanup(tmpdir)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 not available")
class OverviewTableViewTests(unittest.TestCase):
    """Tests for Overview table view and shared live filters."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _seed_yaml(self, records, meta_extra=None):
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="ln2_ov_table_")
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        meta = {"box_layout": {"rows": 9, "cols": 9}}
        if meta_extra:
            meta.update(meta_extra)
        from lib.yaml_ops import write_yaml

        write_yaml(
            {"meta": meta, "inventory": records},
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path, tmpdir

    def _cleanup(self, tmpdir):
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def _switch_to_table(self, panel):
        if hasattr(panel, "ov_view_mode"):
            idx = panel.ov_view_mode.findData("table")
            self.assertGreaterEqual(idx, 0)
            panel.ov_view_mode.setCurrentIndex(idx)
        else:
            panel._on_view_mode_changed("table")

    def _switch_to_grid(self, panel):
        if hasattr(panel, "ov_view_mode"):
            idx = panel.ov_view_mode.findData("grid")
            self.assertGreaterEqual(idx, 0)
            panel.ov_view_mode.setCurrentIndex(idx)
        else:
            panel._on_view_mode_changed("grid")

    def test_table_view_uses_export_columns(self):
        records = [
            {
                "id": 1,
                "cell_line": "K562",
                "short_name": "A",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "passage_number": 3,
            },
            {
                "id": 2,
                "cell_line": "HeLa",
                "short_name": "B",
                "box": 2,
                "position": 2,
                "frozen_at": "2025-01-01",
                "passage_number": 7,
            },
        ]
        meta_extra = {
            "custom_fields": [{"key": "passage_number", "label": "Passage #", "type": "int"}],
            "color_key": "cell_line",
        }
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = [
                panel.ov_table.horizontalHeaderItem(i).text()
                for i in range(panel.ov_table.columnCount())
            ]
            self.assertIn("id", headers)
            self.assertIn("cell_line", headers)
            self.assertIn("location", headers)  # Changed from "position" to "location"
            self.assertIn("passage_number", headers)
            self.assertEqual(2, panel.ov_table.rowCount())
        finally:
            self._cleanup(tmpdir)

    def test_table_view_shares_live_filters(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra={"color_key": "cell_line"})
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)
            self.assertEqual(2, panel.ov_table.rowCount())

            panel.ov_filter_keyword.setText("hela")
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("2", panel.ov_table.item(0, 0).text())

            panel.ov_filter_keyword.clear()
            box_idx = panel.ov_filter_box.findData(1)
            self.assertGreaterEqual(box_idx, 0)
            panel.ov_filter_box.setCurrentIndex(box_idx)
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("1", panel.ov_table.item(0, 0).text())

            panel.ov_filter_box.setCurrentIndex(0)
            cell_idx = panel.ov_filter_cell.findData("K562")
            self.assertGreaterEqual(cell_idx, 0)
            panel.ov_filter_cell.setCurrentIndex(cell_idx)
            self.assertEqual(1, panel.ov_table.rowCount())
            self.assertEqual("1", panel.ov_table.item(0, 0).text())
        finally:
            self._cleanup(tmpdir)

    def test_table_view_row_color_matches_grid_palette(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "clone-A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
            {"id": 2, "cell_line": "HeLa", "short_name": "clone-B", "box": 2, "position": 2, "frozen_at": "2025-01-01"},
        ]
        meta_extra = {"color_key": "cell_line", "cell_line_options": ["K562", "HeLa"]}
        yaml_path, tmpdir = self._seed_yaml(records, meta_extra=meta_extra)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            headers = [panel.ov_table.horizontalHeaderItem(i).text() for i in range(panel.ov_table.columnCount())]
            id_col = headers.index("id")

            row_bg_by_id = {}
            tint_role = int(TABLE_ROW_TINT_ROLE)
            for row in range(panel.ov_table.rowCount()):
                rid = panel.ov_table.item(row, id_col).text()
                first_color = str(panel.ov_table.item(row, 0).data(tint_role) or "").lower()
                for col in range(panel.ov_table.columnCount()):
                    item_color = str(panel.ov_table.item(row, col).data(tint_role) or "").lower()
                    self.assertEqual(first_color, item_color)
                row_bg_by_id[rid] = first_color

            self.assertEqual(cell_color("K562").lower(), row_bg_by_id.get("1"))
            self.assertEqual(cell_color("HeLa").lower(), row_bg_by_id.get("2"))
        finally:
            self._cleanup(tmpdir)

    def test_table_mode_disables_show_empty_toggle(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 1, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()

            self.assertTrue(panel.ov_filter_show_empty.isEnabled())
            self._switch_to_table(panel)
            self.assertFalse(panel.ov_filter_show_empty.isEnabled())

            self._switch_to_grid(panel)
            self.assertTrue(panel.ov_filter_show_empty.isEnabled())
        finally:
            self._cleanup(tmpdir)

    def test_table_click_prefills_takeout_context(self):
        records = [
            {"id": 1, "cell_line": "K562", "short_name": "A", "box": 1, "position": 5, "frozen_at": "2025-01-01"},
        ]
        yaml_path, tmpdir = self._seed_yaml(records)
        try:
            from app_gui.tool_bridge import GuiToolBridge

            panel = OverviewPanel(bridge=GuiToolBridge(), yaml_path_getter=lambda: yaml_path)
            panel.refresh()
            self._switch_to_table(panel)

            emitted = []
            panel.request_prefill_background.connect(lambda payload: emitted.append(payload))
            panel.on_table_row_double_clicked(0, 0)

            self.assertEqual(
                [{"box": 1, "position": 5, "record_id": 1}],
                emitted,
            )
        finally:
            self._cleanup(tmpdir)
