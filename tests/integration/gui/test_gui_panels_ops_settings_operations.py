"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from lib.plan_store import PlanStore
from PySide6.QtWidgets import QSizePolicy


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsOperationsTests(GuiPanelsBaseCase):
    def test_operations_panel_apply_meta_update_without_args_loads_yaml_meta(self):
        from lib.yaml_ops import write_yaml

        panel = self._new_operations_panel()
        write_yaml(
            {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [
                        {"key": "sample_type", "label": "Sample Type", "type": "str"},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "sample_type": "PBMC",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ],
            },
            path=self.fake_yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )

        panel.apply_meta_update()

        custom_keys = [
            field.get("key")
            for field in panel._current_custom_fields
            if isinstance(field, dict)
        ]
        self.assertIn("sample_type", custom_keys)
        self.assertEqual("sample_type", panel._current_meta["custom_fields"][0]["key"])
        self.assertEqual("PBMC", panel._current_inventory[0]["sample_type"])

    def test_operations_panel_migration_lock_disables_write_controls(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel.op_mode_combo.isEnabled())
        self.assertTrue(panel.op_stack.isEnabled())
        panel.plan_exec_btn.setEnabled(True)
        panel.plan_clear_btn.setEnabled(True)
        panel.undo_btn.setEnabled(True)

        panel.set_migration_mode_enabled(True)

        self.assertFalse(panel.op_mode_combo.isEnabled())
        self.assertFalse(panel.op_stack.isEnabled())
        self.assertFalse(panel.plan_exec_btn.isEnabled())
        self.assertFalse(panel.plan_clear_btn.isEnabled())
        self.assertFalse(panel.undo_btn.isEnabled())

    def test_operations_panel_migration_banner_visibility_tracks_mode(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel._migration_mode_banner.isHidden())
        self.assertTrue(panel._migration_lock_overlay.isHidden())
        panel.set_migration_mode_enabled(True)
        self.assertTrue(panel._migration_mode_banner.isHidden())
        self.assertFalse(panel._migration_lock_overlay.isHidden())
        panel.set_migration_mode_enabled(False)
        self.assertTrue(panel._migration_mode_banner.isHidden())
        self.assertTrue(panel._migration_lock_overlay.isHidden())

    def test_operations_panel_repeated_migration_mode_value_is_noop(self):
        panel = self._new_operations_panel()

        with patch.object(panel, "_apply_migration_mode_ui_state") as apply_state:
            panel.set_migration_mode_enabled(True)
            panel.set_migration_mode_enabled(True)

        apply_state.assert_called_once_with()

    def test_operations_panel_migration_lock_blocks_staging_writes(self):
        panel = self._new_operations_panel()
        notices = []
        panel.status_message.connect(lambda msg, timeout, level: notices.append((msg, timeout, level)))
        panel.set_migration_mode_enabled(True)

        panel.add_plan_items(
            [
                {
                    "action": "add",
                    "box": 1,
                    "positions": [1],
                    "fields": {"cell_line": "K562"},
                }
            ]
        )

        self.assertEqual(0, panel._plan_store.count())
        self.assertTrue(notices)
        self.assertEqual(tr("operations.migrationWriteLocked"), notices[-1][0])

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

    def test_operations_panel_cell_line_context_visibility_tracks_effective_schema(self):
        panel = self._new_operations_panel()

        panel.apply_meta_update(
            {
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "sample_type", "label": "Sample Type", "type": "str"},
                ]
            }
        )
        self.assertFalse(panel._t_ctx_cell_line_label.isHidden())
        self.assertFalse(panel._t_ctx_cell_line_container.isHidden())
        self.assertFalse(panel._m_ctx_cell_line_label.isHidden())
        self.assertFalse(panel._m_ctx_cell_line_container.isHidden())

    def test_operations_panel_context_fields_follow_schema_order_before_history(self):
        panel = self._new_operations_panel()

        panel.apply_meta_update(
            {
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "sample_type", "label": "Sample Type", "type": "str"},
                    {"key": "note", "label": "Note", "type": "str"},
                ]
            }
        )

        takeout_sample_container, _takeout_sample_widget = panel._takeout_ctx_widgets["sample_type"]
        move_sample_container, _move_sample_widget = panel._move_ctx_widgets["sample_type"]

        t_cell_line_row, _ = panel._takeout_ctx_form.getWidgetPosition(panel._t_ctx_cell_line_container)
        t_sample_row, _ = panel._takeout_ctx_form.getWidgetPosition(takeout_sample_container)
        t_note_row, _ = panel._takeout_ctx_form.getWidgetPosition(panel._t_ctx_note_container)
        t_history_row, _ = panel._takeout_ctx_form.getWidgetPosition(panel._t_ctx_history_container)

        m_cell_line_row, _ = panel._move_ctx_form.getWidgetPosition(panel._m_ctx_cell_line_container)
        m_sample_row, _ = panel._move_ctx_form.getWidgetPosition(move_sample_container)
        m_note_row, _ = panel._move_ctx_form.getWidgetPosition(panel._m_ctx_note_container)
        m_history_row, _ = panel._move_ctx_form.getWidgetPosition(panel._m_ctx_history_container)

        self.assertLess(t_cell_line_row, t_sample_row)
        self.assertLess(t_sample_row, t_note_row)
        self.assertLess(t_note_row, t_history_row)

        self.assertLess(m_cell_line_row, m_sample_row)
        self.assertLess(m_sample_row, m_note_row)
        self.assertLess(m_note_row, m_history_row)

    def test_operations_panel_apply_meta_update_blocks_legacy_box_fields(self):
        panel = self._new_operations_panel()
        notices = []
        panel.status_message.connect(lambda msg, timeout, level: notices.append((str(msg), timeout, level)))

        panel.apply_meta_update(
            {
                "box_layout": {"rows": 9, "cols": 9},
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
                "box_fields": {
                    "1": [
                        {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                    ]
                },
            }
        )

        self.assertEqual([], panel._current_custom_fields)
        self.assertTrue(notices)
        self.assertIn("meta.box_fields", notices[-1][0])

        panel.apply_meta_update(
            {
                "custom_fields": [
                    {"key": "sample_type", "label": "Sample Type", "type": "str"},
                ]
            }
        )
        self.assertTrue(panel._t_ctx_cell_line_label.isHidden())
        self.assertTrue(panel._t_ctx_cell_line_container.isHidden())
        self.assertTrue(panel._m_ctx_cell_line_label.isHidden())
        self.assertTrue(panel._m_ctx_cell_line_container.isHidden())

        # Legacy keys still reactivate the compatibility cell_line field.
        panel.apply_meta_update(
            {
                "custom_fields": [
                    {"key": "sample_type", "label": "Sample Type", "type": "str"},
                ],
                "cell_line_required": False,
            }
        )
        self.assertFalse(panel._t_ctx_cell_line_label.isHidden())
        self.assertFalse(panel._t_ctx_cell_line_container.isHidden())
        self.assertFalse(panel._m_ctx_cell_line_label.isHidden())
        self.assertFalse(panel._m_ctx_cell_line_container.isHidden())

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

        record = panel.records_cache.get(1)
        self.assertIsInstance(record, dict)
        self.assertEqual(1, int(record.get("id")))
        self.assertEqual("2026-02-10", record.get("stored_at"))
        self.assertEqual("2026-02-10", record.get("frozen_at"))

    def test_operations_panel_cache_expands_canonical_stored_at_aliases(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                "1": {
                    "id": 1,
                    "parent_cell_line": "K562",
                    "short_name": "k562-a",
                    "box": 1,
                    "position": 1,
                    "stored_at": "2026-02-10",
                }
            }
        )

        record = panel.records_cache.get(1)
        self.assertIsInstance(record, dict)
        self.assertEqual("2026-02-10", record.get("stored_at"))
        self.assertEqual("2026-02-10", record.get("frozen_at"))

    def test_operations_panel_cache_normalizes_alphanumeric_positions(self):
        panel = self._new_operations_panel()
        panel._refresh_custom_fields = lambda: None
        panel._current_layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        panel.update_records_cache(
            {
                "1": {
                    "id": 1,
                    "parent_cell_line": "K562",
                    "short_name": "k562-a",
                    "box": 1,
                    "position": "B4",
                    "frozen_at": "2026-02-10",
                }
            }
        )

        record = panel.records_cache.get(1)
        self.assertIsInstance(record, dict)
        self.assertEqual(1, record.get("box"))
        self.assertEqual(13, record.get("position"))

    def test_operations_panel_takeout_accepts_alphanumeric_position_without_crash(self):
        panel = self._new_operations_panel()
        panel._refresh_custom_fields = lambda: None
        panel._current_layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        panel.update_records_cache(
            {
                "1": {
                    "id": 1,
                    "parent_cell_line": "K562",
                    "short_name": "k562-a",
                    "box": 1,
                    "position": "B4",
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.t_id.setValue(1)
        panel.t_from_box.setValue(1)
        panel.t_from_position.setText("B4")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        self.assertEqual(13, panel.t_position.currentData())

        panel.on_record_takeout()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual(13, item.get("position"))
        self.assertEqual(13, (item.get("payload") or {}).get("position"))

    def test_operations_panel_add_entry_parses_positions_text(self):
        panel = self._new_operations_panel()

        # Simulate effective fields being loaded
        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False}
        ]
        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._rebuild_custom_add_fields(panel, panel._current_custom_fields)

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
        self.assertTrue(
            ("Invalid position format" in messages[-1][0]) or ("浣嶇疆鏍煎紡" in messages[-1][0])
        )

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

    def test_operations_panel_primary_action_buttons_have_unified_style(self):
        panel = self._new_operations_panel()

        primary_buttons = (panel.a_apply_btn, panel.t_apply_btn, panel.m_apply_btn)
        for btn in primary_buttons:
            self.assertEqual("primary", btn.property("variant"))
            self.assertGreaterEqual(btn.minimumWidth(), 96)
            self.assertGreaterEqual(btn.minimumHeight(), 28)

    def test_operations_panel_watermark_is_click_through(self):
        panel = self._new_operations_panel()

        self.assertTrue(hasattr(panel, "_op_watermark"))
        self.assertTrue(panel._op_watermark.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertIs(panel.plan_panel, panel._op_watermark_host)

    def test_operations_panel_watermark_geometry_clamps_to_ratio_limits(self):
        panel = self._new_operations_panel()
        host = panel._op_watermark_host
        watermark = panel._op_watermark

        # target_ratio=0.36 clamped to [140, 240]
        host.setGeometry(0, 0, 500, 420)
        panel._update_operation_watermark_geometry()
        self.assertEqual(180, watermark.width())
        self.assertEqual((500 - watermark.width()) // 2, watermark.x())
        self.assertEqual((420 - watermark.height()) // 2, watermark.y())

        host.setGeometry(0, 0, 300, 420)
        panel._update_operation_watermark_geometry()
        self.assertEqual(140, watermark.width())
        self.assertEqual((300 - watermark.width()) // 2, watermark.x())

        host.setGeometry(0, 0, 1200, 700)
        panel._update_operation_watermark_geometry()
        self.assertEqual(240, watermark.width())

    def test_operations_panel_logo_path_prefers_assets_then_root_fallback(self):
        panel = self._new_operations_panel()

        with patch("app_gui.ui.operations_panel.os.path.isfile") as is_file:
            def _both_exist(path):
                norm = str(path).replace("\\", "/")
                return norm.endswith("/app_gui/assets/logo.svg") or norm.endswith("/logo.svg")

            is_file.side_effect = _both_exist
            preferred = panel._resolve_operation_logo_path()

            def _only_root(path):
                norm = str(path).replace("\\", "/")
                return norm.endswith("/logo.svg") and not norm.endswith("/app_gui/assets/logo.svg")

            is_file.side_effect = _only_root
            fallback = panel._resolve_operation_logo_path()

        preferred_norm = preferred.replace("\\", "/")
        fallback_norm = fallback.replace("\\", "/")
        self.assertTrue(preferred_norm.endswith("/app_gui/assets/logo.svg"))
        self.assertTrue(fallback_norm.endswith("/logo.svg"))
        self.assertFalse(fallback_norm.endswith("/app_gui/assets/logo.svg"))

    def test_operations_panel_inline_edit_lock_toggle_controls_confirm_visibility(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            1: {
                "id": 1,
                "parent_cell_line": "K562",
                "short_name": "K562_note",
                "box": 1,
                "position": 1,
                "note": "old-note",
            },
        })
        panel.t_id.setValue(1)
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        container = panel.t_ctx_note.parentWidget()
        lock_btn = container.findChild(QPushButton, "inlineLockBtn")
        confirm_btn = container.findChild(QPushButton, "inlineConfirmBtn")

        self.assertTrue(confirm_btn.isHidden())
        lock_btn.click()
        self.assertFalse(confirm_btn.isHidden())
        lock_btn.click()
        self.assertTrue(confirm_btn.isHidden())

    def test_operations_panel_note_fields_use_multiline_editors(self):
        panel = self._new_operations_panel()

        self.assertIsInstance(panel.a_note, QPlainTextEdit)
        self.assertIsInstance(panel.t_ctx_note, QPlainTextEdit)
        self.assertIsInstance(panel.m_ctx_note, QPlainTextEdit)

        self.assertGreater(panel.a_note.minimumHeight(), panel.a_positions.minimumHeight())
        self.assertGreater(panel.t_ctx_note.minimumHeight(), panel.t_from_position.minimumHeight())
        self.assertGreater(panel.m_ctx_note.minimumHeight(), panel.m_from_position.minimumHeight())

    def test_operations_panel_add_staging_preserves_multiline_note(self):
        panel = self._new_operations_panel()

        panel.a_box.setValue(1)
        panel.a_positions.setText("1")
        panel.a_note.setPlainText("first line\nsecond line")

        panel.on_add_entry()

        self.assertEqual(1, panel._plan_store.count())
        item = panel._plan_store.list_items()[0]
        payload = item.get("payload") or {}
        fields = payload.get("fields") or {}
        self.assertEqual("first line\nsecond line", fields.get("note"))

    def test_operations_panel_inline_edit_confirm_executes_immediately(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            1: {
                "id": 1,
                "parent_cell_line": "K562",
                "short_name": "K562_note",
                "box": 1,
                "position": 1,
                "note": "old-note",
            },
        })
        panel.t_id.setValue(1)
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        bridge = SimpleNamespace(
            edit_entry=MagicMock(return_value={"ok": True})
        )
        panel.bridge = bridge
        emitted = []
        panel.operation_completed.connect(lambda ok: emitted.append(bool(ok)))

        container = panel.t_ctx_note.parentWidget()
        lock_btn = container.findChild(QPushButton, "inlineLockBtn")
        confirm_btn = container.findChild(QPushButton, "inlineConfirmBtn")

        lock_btn.click()
        panel.t_ctx_note.setPlainText("new-note")
        confirm_btn.click()

        bridge.edit_entry.assert_called_once()
        kwargs = bridge.edit_entry.call_args.kwargs
        self.assertEqual(self.fake_yaml_path, kwargs["yaml_path"])
        self.assertEqual(1, kwargs["record_id"])
        self.assertEqual({"note": "new-note"}, kwargs["fields"])
        self.assertEqual("execute", kwargs["execution_mode"])
        self.assertEqual([True], emitted)
        self.assertTrue(panel.t_ctx_note.isReadOnly())
        self.assertTrue(confirm_btn.isHidden())

    def test_operations_panel_inline_stored_date_edit_uses_canonical_field_name(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            1: {
                "id": 1,
                "cell_line": "K562",
                "box": 1,
                "position": 1,
                "stored_at": "2025-01-01",
            },
        })
        panel.t_id.setValue(1)
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        bridge = SimpleNamespace(
            edit_entry=MagicMock(return_value={"ok": True})
        )
        panel.bridge = bridge

        container = panel.t_ctx_frozen.parentWidget()
        lock_btn = container.findChild(QPushButton, "inlineLockBtn")
        confirm_btn = container.findChild(QPushButton, "inlineConfirmBtn")

        self.assertEqual("2025-01-01", panel.t_ctx_frozen.text())
        lock_btn.click()
        panel.t_ctx_frozen.setText("2025-02-01")
        confirm_btn.click()

        bridge.edit_entry.assert_called_once()
        kwargs = bridge.edit_entry.call_args.kwargs
        self.assertEqual({"stored_at": "2025-02-01"}, kwargs["fields"])
        self.assertTrue(panel.t_ctx_frozen.isReadOnly())
        self.assertTrue(confirm_btn.isHidden())

    def test_operations_panel_inline_edit_confirm_works_with_real_gui_bridge(self):
        from app_gui.tool_bridge import GuiToolBridge
        from lib.yaml_ops import load_yaml, write_yaml

        panel = self._new_operations_panel()
        write_yaml(
            {
                "meta": {"box_layout": {"rows": 9, "cols": 9}},
                "inventory": [
                    {
                        "id": 1,
                        "cell_line": "K562",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2025-01-01",
                        "note": "old-note",
                    }
                ],
            },
            path=self.fake_yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )

        panel.bridge = GuiToolBridge(session_id="ops-inline-edit")
        panel.update_records_cache({
            1: {
                "id": 1,
                "cell_line": "K562",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "note": "old-note",
            },
        })
        panel.t_id.setValue(1)
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        emitted = []
        panel.operation_completed.connect(lambda ok: emitted.append(bool(ok)))

        container = panel.t_ctx_note.parentWidget()
        lock_btn = container.findChild(QPushButton, "inlineLockBtn")
        confirm_btn = container.findChild(QPushButton, "inlineConfirmBtn")

        lock_btn.click()
        panel.t_ctx_note.setPlainText("new-note")
        confirm_btn.click()

        current = load_yaml(self.fake_yaml_path)
        self.assertEqual("new-note", current["inventory"][0]["note"])
        self.assertEqual([True], emitted)
        self.assertTrue(panel.t_ctx_note.isReadOnly())
        self.assertTrue(confirm_btn.isHidden())

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

    def test_rollback_staging_replaces_existing_plan_items(self):
        panel = self._new_operations_panel()
        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from lib.plan_item_factory import build_rollback_plan_item

        panel.add_plan_items([_make_takeout_item(record_id=1, position=1)])
        panel.add_plan_items([build_rollback_plan_item(backup_path="/tmp/backup_a.bak", source="tests")])

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual("rollback", panel.plan_items[0].get("action"))
        self.assertIn(
            tr("operations.planRollbackReplaced", count=1),
            [str(msg) for msg in messages],
        )

    def test_invalid_rollback_staging_keeps_existing_plan_items(self):
        panel = self._new_operations_panel()
        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(msg))

        from lib.plan_item_factory import build_rollback_plan_item

        panel.add_plan_items([_make_takeout_item(record_id=1, position=1)])
        panel.add_plan_items([build_rollback_plan_item(backup_path="", source="tests")])

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual("takeout", panel.plan_items[0].get("action"))
        reject_prefix = tr("operations.planRejected", error="").strip()
        self.assertTrue(
            any(
                str(msg).startswith(reject_prefix)
                for msg in messages
            )
        )
        self.assertTrue(
            any(
                "RollbackKept" in str(msg)
                or "kept" in str(msg).lower()
                or "\u4fdd\u7559" in str(msg)
                for msg in messages
            )
        )

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

    def test_operations_panel_move_requires_active_source_position(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            31: {
                "id": 31,
                "parent_cell_line": "K562",
                "short_name": "K562-consumed",
                "box": 2,
                "position": None,
            },
        })
        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(str(msg)))

        panel.m_id.setValue(31)
        panel.m_to_position.setText("8")
        panel.on_record_move()

        self.assertEqual([], panel.plan_items)
        self.assertTrue(messages)
        self.assertIn(tr("operations.positionRequired"), messages[-1])

    def test_operations_panel_takeout_requires_position(self):
        panel = self._new_operations_panel()
        messages = []
        panel.status_message.connect(lambda msg, _timeout, _level: messages.append(str(msg)))

        panel.on_record_takeout()

        self.assertEqual([], panel.plan_items)
        self.assertTrue(messages)
        self.assertIn(tr("operations.positionRequired"), messages[-1])

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

        from app_gui.ui import operations_panel_results as _ops_results

        _ops_results._handle_response(panel, {"ok": True, "result": {"dry_run": True}}, "Single Operation")

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

    def _form_label_for_context_status(self, panel, mode):
        tab = panel.op_stack.widget(panel.op_mode_indexes[mode])
        status_label = panel.t_ctx_status if mode == "takeout" else panel.m_ctx_status
        root_layout = tab.layout()
        for index in range(root_layout.count()):
            item = root_layout.itemAt(index)
            child_layout = item.layout()
            if child_layout is None or not hasattr(child_layout, "labelForField"):
                continue
            label = child_layout.labelForField(status_label)
            if label is not None:
                return label
        return None

    def test_operations_panel_context_status_is_not_a_form_field_row(self):
        panel = self._new_operations_panel()

        self.assertIsNone(self._form_label_for_context_status(panel, "takeout"))
        self.assertIsNone(self._form_label_for_context_status(panel, "move"))
        self.assertIs(panel._top_status_slot, panel.plan_feedback_label.parent())
        self.assertIs(panel._top_status_slot, panel.t_ctx_status.parent())
        self.assertIs(panel._top_status_slot, panel.m_ctx_status.parent())
        self.assertTrue(panel.t_ctx_status.isHidden())
        self.assertTrue(panel.m_ctx_status.isHidden())
        self.assertTrue(panel.t_ctx_status.alignment() & Qt.AlignRight)
        self.assertTrue(panel.m_ctx_status.alignment() & Qt.AlignRight)
        self.assertEqual(QSizePolicy.Fixed, panel.op_mode_combo.sizePolicy().horizontalPolicy())

    def test_operations_panel_plan_feedback_shares_top_status_slot(self):
        panel = self._new_operations_panel()
        panel.t_ctx_status.setText(tr("operations.recordNotFound"))
        panel.t_ctx_status.setVisible(True)

        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._set_plan_feedback(panel, "blocked detail", level="error")

        self.assertFalse(panel.plan_feedback_label.isHidden())
        self.assertEqual("blocked detail", panel.plan_feedback_label.text())
        self.assertEqual("blocked detail", panel.plan_feedback_label.toolTip())
        self.assertEqual("", panel.plan_feedback_label.property("role"))
        self.assertEqual("", panel.plan_feedback_label.objectName())
        self.assertIs(panel._top_status_slot, panel.plan_feedback_label.parent())
        self.assertTrue(panel.t_ctx_status.isHidden())

    def test_operations_panel_prefill_context_shows_status_when_record_missing(self):
        panel = self._new_operations_panel()

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertFalse(panel.t_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.t_ctx_status.text())

    def test_operations_panel_takeout_source_miss_clears_stale_record_id(self):
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
        self.assertEqual(5, panel.t_id.value())

        panel.t_from_position.setText("31")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)

        self.assertEqual(0, panel.t_id.value())
        self.assertFalse(panel.t_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.t_ctx_status.text())

    def test_operations_panel_move_context_shows_status_when_record_missing(self):
        panel = self._new_operations_panel()

        panel.m_from_box.setValue(1)
        panel.m_from_position.setText("30")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)

        self.assertFalse(panel.m_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.m_ctx_status.text())

    def test_operations_panel_move_source_miss_clears_stale_record_id(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                7: {
                    "id": 7,
                    "parent_cell_line": "K562",
                    "short_name": "K562_move",
                    "box": 2,
                    "position": 15,
                }
            }
        )
        panel.m_from_box.setValue(2)
        panel.m_from_position.setText("15")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)
        self.assertEqual(7, panel.m_id.value())

        panel.m_from_position.setText("16")
        _ops_context._refresh_move_record_context(panel)

        self.assertEqual(0, panel.m_id.value())
        self.assertFalse(panel.m_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.m_ctx_status.text())

    def test_operations_panel_readonly_context_fields_reset_cursor_to_start(self):
        panel = self._new_operations_panel()
        long_cell_line = "K562_" + ("X" * 96)
        long_note = "\n".join([f"note line {idx}" for idx in range(1, 30)])
        panel.update_records_cache(
            {
                42: {
                    "id": 42,
                    "cell_line": long_cell_line,
                    "note": long_note,
                    "box": 1,
                    "position": 30,
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.set_prefill({"box": 1, "position": 30, "record_id": 42})
        panel.m_from_box.setValue(1)
        panel.m_from_position.setText("30")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)

        self.assertTrue(panel.t_ctx_cell_line.isReadOnly())
        self.assertEqual(0, panel.t_ctx_cell_line.cursorPosition())
        self.assertTrue(panel.m_ctx_cell_line.isReadOnly())
        self.assertEqual(0, panel.m_ctx_cell_line.cursorPosition())

        self.assertTrue(panel.t_ctx_note.isReadOnly())
        self.assertEqual(0, panel.t_ctx_note.textCursor().position())
        self.assertTrue(panel.m_ctx_note.isReadOnly())
        self.assertEqual(0, panel.m_ctx_note.textCursor().position())

    def test_operations_panel_readonly_custom_context_fields_reset_cursor_to_start(self):
        panel = self._new_operations_panel()
        panel.apply_meta_update(
            {
                "custom_fields": [
                    {"key": "custom_tag", "label": "Custom Tag", "type": "str"},
                ]
            }
        )
        panel._refresh_custom_fields = lambda: None
        long_tag = "TAG_" + ("Y" * 120)
        panel.update_records_cache(
            {
                43: {
                    "id": 43,
                    "box": 2,
                    "position": 11,
                    "frozen_at": "2026-02-10",
                    "custom_tag": long_tag,
                }
            }
        )

        panel.set_prefill({"box": 2, "position": 11, "record_id": 43})
        panel.m_from_box.setValue(2)
        panel.m_from_position.setText("11")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)

        t_custom = panel._takeout_ctx_widgets["custom_tag"][1]
        m_custom = panel._move_ctx_widgets["custom_tag"][1]

        self.assertIsInstance(t_custom, QLineEdit)
        self.assertTrue(t_custom.isReadOnly())
        self.assertEqual(0, t_custom.cursorPosition())

        self.assertIsInstance(m_custom, QLineEdit)
        self.assertTrue(m_custom.isReadOnly())
        self.assertEqual(0, m_custom.cursorPosition())

    def test_operations_panel_editable_context_fields_are_not_forced_to_cursor_start(self):
        panel = self._new_operations_panel()
        long_cell_line = "HeLa_" + ("Z" * 80)
        panel.update_records_cache(
            {
                44: {
                    "id": 44,
                    "cell_line": long_cell_line,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.t_id.setValue(44)
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_takeout_record_context(panel)
        container = panel.t_ctx_cell_line.parentWidget()
        lock_btn = container.findChild(QPushButton, "inlineLockBtn")
        lock_btn.click()
        self.assertFalse(panel.t_ctx_cell_line.isReadOnly())

        _ops_context._refresh_takeout_record_context(panel)

        self.assertGreater(panel.t_ctx_cell_line.cursorPosition(), 0)

    def test_operations_panel_move_source_change_updates_record_id_and_target_box(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            7: {
                "id": 7,
                "parent_cell_line": "K562",
                "short_name": "K562_move",
                "box": "2",
                "position": "15",
            },
        })

        panel.m_from_box.setValue(2)
        panel.m_from_position.setText("15")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)

        self.assertEqual(7, panel.m_id.value())
        self.assertEqual(2, panel.m_to_box.value())

    def test_operations_panel_move_lookup_matches_string_slot_values(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            18: {
                "id": 18,
                "parent_cell_line": "K562",
                "short_name": "K562_move",
                "box": "3",
                "position": "21",
            },
        })

        panel.m_from_box.setValue(3)
        panel.m_from_position.setText("21")
        from app_gui.ui import operations_panel_context as _ops_context

        _ops_context._refresh_move_record_context(panel)

        self.assertEqual(18, panel.m_id.value())
        self.assertTrue(panel.m_ctx_status.isHidden())

    def test_operations_panel_move_falls_back_to_source_slot_when_id_missing(self):
        panel = self._new_operations_panel()
        panel.update_records_cache({
            19: {
                "id": 19,
                "parent_cell_line": "K562",
                "short_name": "K562_move",
                "box": "4",
                "position": "9",
            },
        })

        panel.m_id.setValue(0)
        panel.m_from_box.setValue(4)
        panel.m_from_position.setText("9")
        panel.m_to_position.setText("10")
        panel.on_record_move()

        self.assertEqual(1, len(panel.plan_items))
        self.assertEqual(19, panel.plan_items[0]["record_id"])

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
                "yaml_path": self.fake_yaml_path,
                "output_path": "/tmp/full_export.csv",
            },
            bridge.last_export_payload,
        )

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
        # set_prefill_background switches to takeout mode
        self.assertEqual("takeout", panel.current_operation_mode)

    def test_operations_background_prefill_formats_multi_positions_for_numeric_layout(self):
        panel = self._new_operations_panel()

        panel.set_add_prefill_background({"box": 2, "position": 9, "positions": [9, 10, 11]})

        self.assertEqual(2, panel.a_box.value())
        self.assertEqual("9,10,11", panel.a_positions.text())
        self.assertEqual("add", panel.current_operation_mode)

    def test_operations_background_prefill_formats_multi_positions_for_alphanumeric_layout(self):
        panel = self._new_operations_panel()
        panel._current_layout = {"rows": 3, "cols": 3, "indexing": "alphanumeric"}

        panel.set_add_prefill_background({"box": 1, "position": 1, "positions": [1, 2, 3]})

        self.assertEqual("A1,A2,A3", panel.a_positions.text())
        self.assertEqual("add", panel.current_operation_mode)

    def test_overview_click_staged_add_prefills_full_form_and_locks_inputs(self):
        plan_store = PlanStore()
        overview = OverviewPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)
        panel = OperationsPanel(
            bridge=object(),
            yaml_path_getter=lambda: self.fake_yaml_path,
            plan_store=plan_store,
            overview_panel=overview,
        )
        overview.request_add_prefill_background.connect(panel.set_add_prefill_background)
        overview.request_prefill_background.connect(panel.set_prefill_background)
        overview.bind_plan_store(plan_store)

        panel._current_custom_fields = [
            {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
        ]
        from app_gui.ui import operations_panel_forms as _ops_forms

        _ops_forms._rebuild_custom_add_fields(panel, panel._current_custom_fields)

        item = {
            "action": "add",
            "box": 1,
            "position": 2,
            "record_id": None,
            "source": "human",
            "payload": {
                "box": 1,
                "positions": [2, 3],
                "stored_at": "2026-02-10",
                "fields": {
                    "short_name": "clone-23",
                },
            },
        }
        panel.add_plan_items([item])

        overview._rebuild_boxes(rows=1, cols=4, box_numbers=[1])
        overview.overview_pos_map = {}
        for key, button in overview.overview_cells.items():
            overview._paint_cell(button, key[0], key[1], record=None)

        QTest.mouseClick(overview.overview_cells[(1, 3)], Qt.LeftButton)
        self._app.processEvents()

        self.assertEqual("add", panel.current_operation_mode)
        self.assertEqual(1, panel.a_box.value())
        self.assertEqual("2,3", panel.a_positions.text())
        self.assertEqual("2026-02-10", panel.a_date.date().toString("yyyy-MM-dd"))
        self.assertEqual("clone-23", panel._add_custom_widgets["short_name"].text())
        self.assertFalse(panel.a_box.isEnabled())
        self.assertFalse(panel.a_positions.isEnabled())
        self.assertFalse(panel._add_custom_widgets["short_name"].isEnabled())
        self.assertFalse(panel.a_apply_btn.isEnabled())

    def test_operations_panel_record_takeout_creates_plan_item(self):
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
        panel.on_record_takeout()

        self.assertEqual(1, len(panel.plan_items))
        item = panel.plan_items[0]
        self.assertEqual("takeout", item["action"])
        self.assertEqual(2, item["box"])
        self.assertEqual(10, item["position"])
        self.assertEqual(5, item["record_id"])
