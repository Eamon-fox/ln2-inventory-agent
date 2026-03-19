"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsOverviewTests(GuiPanelsBaseCase):
    def test_overview_export_button_emits_request_signal(self):
        panel = self._new_overview_panel()
        emitted = []
        panel.request_export_inventory_csv.connect(lambda: emitted.append(True))

        panel.ov_export_csv_btn.click()

        self.assertEqual([True], emitted)

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
        emitted_add = []
        panel.request_prefill.connect(lambda payload: emitted_thaw.append(payload))
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

    def test_overview_plan_markers_render_badge_and_border(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        record = {
            "id": 5,
            "cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "position": 1,
            "frozen_at": "2026-02-10",
        }
        panel._current_records = [record]
        panel.overview_pos_map = {(1, 1): record}

        panel._set_plan_markers_from_items([_make_takeout_item(record_id=5, position=1, box=1)])

        button = panel.overview_cells[(1, 1)]
        self.assertEqual("takeout", str(button.property("operation_marker")))
        self.assertEqual("OUT", str(button.property("operation_badge_text")))
        self.assertIn("#ef4444", button.styleSheet())

    def test_overview_plan_markers_clear_when_plan_empty(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        record = {
            "id": 7,
            "cell_line": "HeLa",
            "short_name": "HeLa_test",
            "box": 1,
            "position": 1,
            "frozen_at": "2026-02-10",
        }
        panel._current_records = [record]
        panel.overview_pos_map = {(1, 1): record}

        panel._set_plan_markers_from_items([_make_takeout_item(record_id=7, position=1, box=1)])
        button = panel.overview_cells[(1, 1)]
        self.assertEqual("takeout", str(button.property("operation_marker")))

        panel._set_plan_markers_from_items([])
        self.assertIn(button.property("operation_marker"), ("", None))
        self.assertIn(button.property("operation_badge_text"), ("", None))

    def test_overview_plan_markers_repaint_keeps_occupied_when_slot_values_are_strings(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        record = {
            "id": 9,
            "cell_line": "A375",
            "short_name": "A375_test",
            "box": "1",
            "position": "1",
            "frozen_at": "2026-02-10",
        }
        panel._current_records = [record]
        # Simulate stale/missing pos-map cache before marker repaint.
        panel.overview_pos_map = {}

        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)
        self.assertFalse(bool(button.property("is_empty")))

        panel._set_plan_markers_from_items([_make_takeout_item(record_id=9, position=1, box=1)])

        self.assertFalse(bool(button.property("is_empty")))
        self.assertEqual("takeout", str(button.property("operation_marker")))

    def test_overview_add_plan_markers_cover_all_payload_positions(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=3, box_numbers=[1])
        panel._current_records = []
        panel.overview_pos_map = {}

        add_item = {
            "action": "add",
            "box": 1,
            "position": 1,
            "record_id": None,
            "payload": {
                "positions": [1, 3],
                "fields": {"short_name": "clone-x"},
            },
        }
        panel._set_plan_markers_from_items([add_item])

        button_1 = panel.overview_cells[(1, 1)]
        button_2 = panel.overview_cells[(1, 2)]
        button_3 = panel.overview_cells[(1, 3)]
        self.assertEqual("add", str(button_1.property("operation_marker")))
        self.assertEqual("ADD", str(button_1.property("operation_badge_text")))
        self.assertIn(button_2.property("operation_marker"), ("", None))
        self.assertEqual("add", str(button_3.property("operation_marker")))

    def test_overview_edit_plan_marker_uses_edit_badge_and_color(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        record = {
            "id": 21,
            "cell_line": "A549",
            "short_name": "A549-x",
            "box": 1,
            "position": 1,
            "frozen_at": "2026-02-10",
        }
        panel._current_records = [record]
        panel.overview_pos_map = {(1, 1): record}

        edit_item = {
            "action": "edit",
            "box": 1,
            "position": 1,
            "record_id": 21,
            "payload": {"fields": {"note": "updated"}},
        }
        panel._set_plan_markers_from_items([edit_item])

        button = panel.overview_cells[(1, 1)]
        self.assertEqual("edit", str(button.property("operation_marker")))
        self.assertEqual("EDT", str(button.property("operation_badge_text")))
        self.assertIn("#06b6d4", button.styleSheet())

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

    def test_overview_missing_yaml_uses_warning_hint_style(self):
        original_language = get_language()
        set_language("en")
        try:
            missing_yaml_path = os.path.join(
                os.path.dirname(__file__),
                "__missing_overview_panel_inventory__.yaml",
            )
            if os.path.exists(missing_yaml_path):
                os.remove(missing_yaml_path)

            panel = OverviewPanel(bridge=object(), yaml_path_getter=lambda: missing_yaml_path)
            panel.refresh()

            expected_message = t("main.fileNotFound", path=missing_yaml_path)
            self.assertEqual(expected_message, panel.ov_status.text())
            self.assertEqual(expected_message, panel.ov_hover_hint.text())
            self.assertEqual("warning", panel.ov_hover_hint.property("state"))
        finally:
            set_language(original_language)

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

    def test_overview_context_menu_record_does_not_add_move_plan_item(self):
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

    def test_overview_drag_drop_record_adds_move_plan_item(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1, 2])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_test",
            "box": 1,
            "position": 1,
        }
        panel.overview_pos_map = {(1, 1): record}
        source_button = panel.overview_cells[(1, 1)]
        panel._paint_cell(source_button, 1, 1, record)

        staged_items = []
        status_messages = []
        panel.plan_items_requested.connect(lambda payload: staged_items.extend(payload))
        panel.status_message.connect(lambda msg, timeout: status_messages.append((str(msg), int(timeout))))

        panel._on_cell_drop(1, 1, 2, 2, 5)

        self.assertEqual(1, len(staged_items))
        item = staged_items[0]
        self.assertEqual("move", item.get("action"))
        self.assertEqual(5, item.get("record_id"))
        self.assertEqual(1, item.get("box"))
        self.assertEqual(1, item.get("position"))
        self.assertEqual(2, item.get("to_box"))
        self.assertEqual(2, item.get("to_position"))
        self.assertTrue(status_messages)
        self.assertEqual(
            tr(
                "overview.moveAdded",
                id=5,
                from_box=1,
                from_pos=1,
                to_box=2,
                to_pos=2,
            ),
            status_messages[-1][0],
        )

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

    def test_overview_set_box_tag_emits_system_notice_event(self):
        panel = self._new_overview_panel()
        panel.bridge = SimpleNamespace(
            set_box_tag=MagicMock(return_value={"ok": True, "result": {"box": 1, "tag_after": "virus"}})
        )
        panel.refresh = MagicMock()
        events = []
        panel.operation_event.connect(lambda payload: events.append(payload))

        with patch("app_gui.ui.overview_panel.QMenu") as menu_cls, patch(
            "PySide6.QtWidgets.QInputDialog.getText",
            return_value=("virus", True),
        ):
            menu = MagicMock()
            menu_cls.return_value = menu
            act_set = MagicMock()
            act_clear = MagicMock()
            menu.addAction.side_effect = [act_set, act_clear]
            menu.exec.return_value = act_set
            panel.on_box_context_menu(1, panel.mapToGlobal(panel.rect().center()))

        self.assertEqual(1, len(events))
        self.assertEqual("system_notice", events[0].get("type"))
        self.assertEqual("box.tag.updated", events[0].get("code"))
        self.assertEqual("success", events[0].get("level"))
        self.assertEqual(1, int((events[0].get("data") or {}).get("box")))

    def test_overview_clear_box_tag_failure_emits_error_system_notice(self):
        panel = self._new_overview_panel()
        panel.bridge = SimpleNamespace(
            set_box_tag=MagicMock(return_value={"ok": False, "error_code": "write_failed", "message": "boom"})
        )
        panel.refresh = MagicMock()
        events = []
        panel.operation_event.connect(lambda payload: events.append(payload))

        with patch("app_gui.ui.overview_panel.QMenu") as menu_cls:
            menu = MagicMock()
            menu_cls.return_value = menu
            act_set = MagicMock()
            act_clear = MagicMock()
            menu.addAction.side_effect = [act_set, act_clear]
            menu.exec.return_value = act_clear
            panel.on_box_context_menu(1, panel.mapToGlobal(panel.rect().center()))

        self.assertEqual(1, len(events))
        self.assertEqual("system_notice", events[0].get("type"))
        self.assertEqual("box.tag.cleared", events[0].get("code"))
        self.assertEqual("error", events[0].get("level"))
        self.assertEqual("write_failed", (events[0].get("data") or {}).get("error_code"))

    def test_overview_arrow_keys_move_selection_within_box_and_stop_at_edges(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=2, cols=2, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            for position in range(1, 5):
                record = {
                    "id": position,
                    "cell_line": f"cell-{position}",
                    "short_name": f"clone-{position}",
                    "box": 1,
                    "position": position,
                    "frozen_at": "2026-02-10",
                }
                panel.overview_pos_map[(1, position)] = record
                panel._paint_cell(panel.overview_cells[(1, position)], 1, position, record)

            self.assertTrue(panel._select_grid_cell(1, 1))

            QTest.keyClick(panel.overview_cells[(1, 1)], Qt.Key_Right)
            self._app.processEvents()
            self.assertEqual((1, 2), panel.overview_selected_key)
            self.assertEqual((1, 2), panel.overview_hover_key)

            QTest.keyClick(panel.overview_cells[(1, 2)], Qt.Key_Down)
            self._app.processEvents()
            self.assertEqual((1, 4), panel.overview_selected_key)
            self.assertEqual((1, 4), panel.overview_hover_key)

            QTest.keyClick(panel.overview_cells[(1, 4)], Qt.Key_Right)
            self._app.processEvents()
            self.assertEqual((1, 4), panel.overview_selected_key)

            QTest.keyClick(panel.overview_cells[(1, 4)], Qt.Key_Down)
            self._app.processEvents()
            self.assertEqual((1, 4), panel.overview_selected_key)
        finally:
            panel.hide()

    def test_overview_arrow_keys_select_first_visible_cell_when_none_selected(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=3, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            panel.overview_cells[(1, 1)].hide()

            QTest.keyClick(panel.ov_scroll.viewport(), Qt.Key_Right)
            self._app.processEvents()

            self.assertEqual((1, 2), panel.overview_selected_key)
            self.assertEqual((1, 2), panel.overview_hover_key)
        finally:
            panel.hide()

    def test_overview_arrow_keys_skip_hidden_cells(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=3, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            panel.overview_cells[(1, 2)].hide()
            self.assertTrue(panel._select_grid_cell(1, 1))

            QTest.keyClick(panel.overview_cells[(1, 1)], Qt.Key_Right)
            self._app.processEvents()

            self.assertEqual((1, 3), panel.overview_selected_key)
            self.assertEqual((1, 3), panel.overview_hover_key)
        finally:
            panel.hide()

    def test_overview_arrow_keys_prefill_operation_panel_for_target_cell(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            record = {
                "id": 11,
                "cell_line": "K562",
                "short_name": "clone-11",
                "box": 1,
                "position": 1,
                "frozen_at": "2026-02-10",
            }
            panel.overview_pos_map = {(1, 1): record}
            panel._paint_cell(panel.overview_cells[(1, 1)], 1, 1, record)
            panel._paint_cell(panel.overview_cells[(1, 2)], 1, 2, record=None)

            emitted_add = []
            emitted_add_bg = []
            emitted_takeout = []
            emitted_takeout_bg = []
            panel.request_add_prefill.connect(lambda payload: emitted_add.append(payload))
            panel.request_add_prefill_background.connect(lambda payload: emitted_add_bg.append(payload))
            panel.request_prefill.connect(lambda payload: emitted_takeout.append(payload))
            panel.request_prefill_background.connect(lambda payload: emitted_takeout_bg.append(payload))

            self.assertTrue(panel._select_grid_cell(1, 1))
            QTest.keyClick(panel.overview_cells[(1, 1)], Qt.Key_Right)
            self._app.processEvents()

            self.assertEqual((1, 2), panel.overview_selected_key)
            self.assertEqual([], emitted_add)
            self.assertEqual([{"box": 1, "position": 2}], emitted_add_bg)
            self.assertEqual([], emitted_takeout)
            self.assertEqual([], emitted_takeout_bg)

            QTest.keyClick(panel.overview_cells[(1, 2)], Qt.Key_Left)
            self._app.processEvents()

            self.assertEqual((1, 1), panel.overview_selected_key)
            self.assertEqual(
                [{"box": 1, "position": 1, "record_id": 11}],
                emitted_takeout_bg,
            )

            QTest.keyClick(panel.overview_cells[(1, 1)], Qt.Key_Left)
            self._app.processEvents()

            self.assertEqual((1, 1), panel.overview_selected_key)
            self.assertEqual(
                [{"box": 1, "position": 1, "record_id": 11}],
                emitted_takeout_bg,
            )
        finally:
            panel.hide()

    def test_overview_arrow_keys_do_not_override_filter_keyword_input(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            self.assertTrue(panel._select_grid_cell(1, 1))
            panel.ov_filter_keyword.setFocus()
            panel.ov_filter_keyword.setText("abc")
            panel.ov_filter_keyword.setCursorPosition(3)
            self._app.processEvents()

            QTest.keyClick(panel.ov_filter_keyword, Qt.Key_Left)
            self._app.processEvents()

            self.assertEqual(2, panel.ov_filter_keyword.cursorPosition())
            self.assertEqual((1, 1), panel.overview_selected_key)
        finally:
            panel.hide()

    def test_overview_arrow_keys_do_not_run_grid_navigation_in_table_view(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=2, box_numbers=[1])
        panel.show()
        try:
            self._app.processEvents()
            self.assertTrue(panel._select_grid_cell(1, 1))
            panel.ov_table.setColumnCount(1)
            panel.ov_table.setRowCount(1)
            panel.ov_table.setItem(0, 0, self._make_table_item("row-1"))
            panel._on_view_mode_changed("table")
            panel.ov_table.setFocus()
            self._app.processEvents()

            QTest.keyClick(panel.ov_table, Qt.Key_Right)
            self._app.processEvents()

            self.assertEqual((1, 1), panel.overview_selected_key)
        finally:
            panel.hide()
