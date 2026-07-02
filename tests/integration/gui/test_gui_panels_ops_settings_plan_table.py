"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from lib.plan_store import PlanStore
from PySide6.QtWidgets import QSizePolicy


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsPlanTableTests(GuiPanelsBaseCase):
    def test_plan_store_queued_refresh_keeps_ui_consistent_after_external_clear(self):
        from PySide6.QtCore import QMetaObject, Qt
        from lib.plan_item_factory import build_rollback_plan_item
        from lib.plan_store import PlanStore

        store = PlanStore()
        panel = OperationsPanel(
            bridge=object(),
            yaml_path_getter=lambda: self.fake_yaml_path,
            plan_store=store,
        )
        self.assertFalse(panel.plan_print_btn.isEnabled())

        def _on_change():
            QMetaObject.invokeMethod(panel, "_on_store_changed", Qt.QueuedConnection)

        store._on_change = _on_change

        store.add([build_rollback_plan_item(backup_path="/tmp/backup_a.bak", source="ai")])
        for _ in range(5):
            self._app.processEvents()

        self.assertEqual(1, store.count())
        self.assertEqual(1, panel.plan_table.rowCount())
        self.assertTrue(panel.plan_print_btn.isEnabled())
        self.assertTrue(panel.plan_clear_btn.isEnabled())

        store.clear()
        for _ in range(5):
            self._app.processEvents()

        self.assertEqual(0, store.count())
        self.assertEqual(0, panel.plan_table.rowCount())
        self.assertFalse(panel.plan_table.isVisible())
        self.assertFalse(panel.plan_print_btn.isEnabled())
        self.assertFalse(panel.plan_clear_btn.isEnabled())

    def test_plan_table_scroll_uses_precise_pixel_steps(self):
        from PySide6.QtWidgets import QAbstractItemView

        panel = self._new_operations_panel()

        self.assertEqual(QAbstractItemView.ScrollPerPixel, panel.plan_table.verticalScrollMode())
        self.assertEqual(QAbstractItemView.ScrollPerPixel, panel.plan_table.horizontalScrollMode())
        self.assertLessEqual(panel.plan_table.verticalScrollBar().singleStep(), 12)
        self.assertLessEqual(panel.plan_table.horizontalScrollBar().singleStep(), 16)

    def test_plan_table_context_menu_remove_deletes_clicked_row(self):
        panel = self._new_operations_panel()
        panel.add_plan_items([
            _make_takeout_item(record_id=101, position=1),
            _make_takeout_item(record_id=102, position=2),
        ])
        self.assertEqual(2, panel._plan_store.count())

        row_item = panel.plan_table.item(0, 0)
        row_center = panel.plan_table.visualItemRect(row_item).center()

        with patch("app_gui.ui.operations_panel.QMenu") as menu_cls:
            fake_menu = menu_cls.return_value
            remove_action = object()
            fake_menu.addAction.return_value = remove_action
            fake_menu.exec.return_value = remove_action

            panel.on_plan_table_context_menu(row_center)

        self.assertEqual(1, panel._plan_store.count())
        self.assertEqual(102, panel.plan_items[0]["record_id"])

    def test_plan_table_context_menu_click_unselected_row_switches_selection(self):
        panel = self._new_operations_panel()
        panel.add_plan_items([
            _make_takeout_item(record_id=201, position=1),
            _make_takeout_item(record_id=202, position=2),
        ])

        panel.plan_table.clearSelection()
        panel.plan_table.selectRow(0)
        from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

        self.assertEqual([0], _ops_plan_toolbar._get_selected_plan_rows(panel))

        row_item = panel.plan_table.item(1, 0)
        row_center = panel.plan_table.visualItemRect(row_item).center()

        with patch("app_gui.ui.operations_panel.QMenu") as menu_cls:
            fake_menu = menu_cls.return_value
            remove_action = object()
            fake_menu.addAction.return_value = remove_action
            fake_menu.exec.return_value = None

            panel.on_plan_table_context_menu(row_center)

        self.assertEqual([1], _ops_plan_toolbar._get_selected_plan_rows(panel))
        self.assertEqual(2, panel._plan_store.count())

    def test_plan_table_selecting_add_row_prefills_full_form_and_locks_inputs(self):
        panel = self._new_operations_panel()
        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
        ]
        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._rebuild_custom_add_fields(panel, panel._current_custom_fields)

        item = {
            "action": "add",
            "box": 2,
            "position": 9,
            "record_id": None,
            "source": "human",
            "payload": {
                "box": 2,
                "positions": [9, 10],
                "stored_at": "2026-02-11",
                "fields": {
                    "short_name": "clone-910",
                },
            },
        }
        panel.add_plan_items([item])

        panel.plan_table.selectRow(0)
        self._app.processEvents()

        self.assertEqual("add", panel.current_operation_mode)
        self.assertEqual(2, panel.a_box.value())
        self.assertEqual("9,10", panel.a_positions.text())
        self.assertEqual("2026-02-11", panel.a_date.date().toString("yyyy-MM-dd"))
        self.assertEqual("clone-910", panel._add_custom_widgets["short_name"].text())
        self.assertFalse(panel.a_box.isEnabled())
        self.assertFalse(panel.a_positions.isEnabled())
        self.assertFalse(panel._add_custom_widgets["short_name"].isEnabled())
        self.assertFalse(panel.a_apply_btn.isEnabled())

    def test_plan_table_clearing_add_selection_unlocks_form_but_keeps_values(self):
        panel = self._new_operations_panel()
        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
        ]
        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._rebuild_custom_add_fields(panel, panel._current_custom_fields)

        item = {
            "action": "add",
            "box": 2,
            "position": 9,
            "record_id": None,
            "source": "human",
            "payload": {
                "box": 2,
                "positions": [9, 10],
                "stored_at": "2026-02-11",
                "fields": {
                    "short_name": "clone-910",
                },
            },
        }
        panel.add_plan_items([item])

        panel.plan_table.selectRow(0)
        self._app.processEvents()
        panel.plan_table.clearSelection()
        self._app.processEvents()

        self.assertTrue(panel.a_box.isEnabled())
        self.assertTrue(panel.a_positions.isEnabled())
        self.assertTrue(panel._add_custom_widgets["short_name"].isEnabled())
        self.assertTrue(panel.a_apply_btn.isEnabled())
        self.assertEqual("9,10", panel.a_positions.text())
        self.assertEqual("clone-910", panel._add_custom_widgets["short_name"].text())

    def test_plan_store_removing_locked_staged_add_unlocks_form(self):
        panel = self._new_operations_panel()
        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
        ]
        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._rebuild_custom_add_fields(panel, panel._current_custom_fields)

        item = {
            "action": "add",
            "box": 3,
            "position": 7,
            "record_id": None,
            "source": "human",
            "payload": {
                "box": 3,
                "positions": [7, 8],
                "stored_at": "2026-02-12",
                "fields": {
                    "short_name": "clone-78",
                },
            },
        }
        panel.add_plan_items([item])
        panel.plan_table.selectRow(0)
        self._app.processEvents()

        panel._plan_store.clear()
        panel._on_store_changed()
        self._app.processEvents()

        self.assertTrue(panel.a_box.isEnabled())
        self.assertTrue(panel.a_positions.isEnabled())
        self.assertTrue(panel._add_custom_widgets["short_name"].isEnabled())
        self.assertTrue(panel.a_apply_btn.isEnabled())
        self.assertEqual("7,8", panel.a_positions.text())
        self.assertEqual("clone-78", panel._add_custom_widgets["short_name"].text())

    def test_plan_tab_exists_in_mode_selector(self):
        panel = self._new_operations_panel()
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
        # Column 1 now shows identity-first location text
        pos_text = panel.plan_table.item(0, 1).text()
        self.assertEqual("Box 1·5", pos_text)

        # Badge should show count
        idx = panel.op_mode_combo.findData("plan")
        if idx >= 0:
            self.assertIn("1", panel.op_mode_combo.itemText(idx))

    def test_add_plan_items_move_target_text_includes_box_prefix(self):
        panel = self._new_operations_panel()
        items = [
            {
                "action": "move",
                "box": 1,
                "position": 5,
                "to_box": 2,
                "to_position": 8,
                "record_id": 10,
                "source": "human",
                "payload": {
                    "record_id": 10,
                    "position": 5,
                    "to_position": 8,
                    "to_box": 2,
                    "date_str": "2026-02-10",
                    "action": "Move",
                },
            },
        ]
        panel.add_plan_items(items)

        self.assertEqual(1, panel.plan_table.rowCount())
        pos_text = panel.plan_table.item(0, 1).text()
        self.assertEqual("Box 1·5 → Box 2·8", pos_text)

    def test_add_plan_items_target_text_includes_box_tag_when_available(self):
        panel = self._new_operations_panel()
        panel._current_layout = {
            "rows": 9,
            "cols": 9,
            "box_tags": {"1": "virus stock", "2": "backup shelf"},
        }
        items = [
            {
                "action": "move",
                "box": 1,
                "position": 5,
                "to_box": 2,
                "to_position": 8,
                "record_id": 10,
                "source": "human",
                "payload": {
                    "record_id": 10,
                    "position": 5,
                    "to_position": 8,
                    "to_box": 2,
                    "date_str": "2026-02-10",
                    "action": "Move",
                },
            },
        ]

        panel.add_plan_items(items)

        self.assertEqual(
            "Box 1 (virus stock)·5 → Box 2 (backup shelf)·8",
            panel.plan_table.item(0, 1).text(),
        )

    def test_add_plan_items_move_same_box_target_repeats_box_prefix(self):
        panel = self._new_operations_panel()
        items = [
            {
                "action": "move",
                "box": 1,
                "position": 5,
                "to_position": 8,
                "record_id": 10,
                "source": "human",
                "payload": {
                    "record_id": 10,
                    "position": 5,
                    "to_position": 8,
                    "date_str": "2026-02-10",
                    "action": "Move",
                },
            },
        ]
        panel.add_plan_items(items)

        self.assertEqual(1, panel.plan_table.rowCount())
        pos_text = panel.plan_table.item(0, 1).text()
        self.assertEqual("Box 1·5 → Box 1·8", pos_text)

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
        panel.yaml_path_getter = lambda: self.fake_yaml_path

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
        self.assertNotIn("action", bridge.last_batch_payload)
        self.assertEqual(10, bridge.last_batch_payload["entries"][0]["record_id"])
        self.assertEqual(1, bridge.last_batch_payload["entries"][0]["from"]["box"])
        self.assertEqual("5", bridge.last_batch_payload["entries"][0]["from"]["position"])
        self.assertEqual(0, len(panel.plan_items))
        self.assertEqual([True], emitted)

    def test_execute_plan_delegates_run_to_plan_run_use_case(self):
        panel = self._new_operations_panel()
        panel.yaml_path_getter = lambda: self.fake_yaml_path
        item = _make_takeout_item(record_id=10, position=5)
        panel.add_plan_items([item])

        fake_report = {
            "ok": True,
            "items": [
                {
                    "ok": True,
                    "item": item,
                    "response": {"backup_path": "/tmp/bak_10.yaml"},
                }
            ],
            "backup_path": "/tmp/bak_10.yaml",
            "stats": {},
            "remaining_items": [],
        }
        fake_run_result = SimpleNamespace(
            report=fake_report,
            results=[("OK", item, {"backup_path": "/tmp/bak_10.yaml"})],
        )
        panel._plan_run_use_case = SimpleNamespace(
            execute=MagicMock(return_value=fake_run_result),
            summarize=MagicMock(
                return_value={
                    "ok_count": 1,
                    "fail_count": 0,
                    "applied_count": 1,
                    "total_count": 1,
                    "rollback_ok": False,
                }
            ),
        )

        with patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes):
            panel.execute_plan()

        panel._plan_run_use_case.execute.assert_called_once_with(
            yaml_path=self.fake_yaml_path,
            plan_items=[item],
            bridge=panel.bridge,
            mode="execute",
        )
        panel._plan_run_use_case.summarize.assert_called_once()

