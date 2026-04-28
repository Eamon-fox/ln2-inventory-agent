"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from lib.plan_store import PlanStore

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsOpsSettingsTests(GuiPanelsBaseCase):
    def test_operations_panel_refresh_custom_fields_delegates_to_apply_meta_update(self):
        panel = self._new_operations_panel()

        with patch.object(panel, "apply_meta_update") as apply_meta_update:
            panel._refresh_custom_fields()

        apply_meta_update.assert_called_once_with()

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

        host.setGeometry(0, 0, 500, 420)
        panel._update_operation_watermark_geometry()
        self.assertEqual(240, watermark.width())
        self.assertEqual((500 - watermark.width()) // 2, watermark.x())
        self.assertEqual((420 - watermark.height()) // 2, watermark.y())

        host.setGeometry(0, 0, 300, 420)
        panel._update_operation_watermark_geometry()
        self.assertEqual(180, watermark.width())
        self.assertEqual((300 - watermark.width()) // 2, watermark.x())

        host.setGeometry(0, 0, 1200, 700)
        panel._update_operation_watermark_geometry()
        self.assertEqual(360, watermark.width())

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

    def test_main_window_ctrl_f_focuses_overview_search_when_focus_not_editable(self):
        from app_gui.main import MainWindow

        window = MainWindow.__new__(MainWindow)
        search = MagicMock()
        window.overview_panel = SimpleNamespace(ov_filter_keyword=search)

        with patch("app_gui.main.QApplication.focusWidget", return_value=QPushButton()):
            MainWindow._focus_overview_search(window)

        search.setFocus.assert_called_once_with(Qt.ShortcutFocusReason)
        search.selectAll.assert_called_once()

    def test_main_window_ctrl_f_does_not_steal_focus_from_line_edit(self):
        from app_gui.main import MainWindow

        window = MainWindow.__new__(MainWindow)
        search = MagicMock()
        window.overview_panel = SimpleNamespace(ov_filter_keyword=search)

        with patch("app_gui.main.QApplication.focusWidget", return_value=QLineEdit()):
            MainWindow._focus_overview_search(window)

        search.setFocus.assert_not_called()
        search.selectAll.assert_not_called()

    def test_main_window_setup_shortcuts_registers_window_ctrl_f(self):
        from app_gui.main import MainWindow

        window = MainWindow.__new__(MainWindow)
        with patch("app_gui.main.QShortcut") as shortcut_cls:
            shortcut = MagicMock()
            shortcut_cls.return_value = shortcut

            MainWindow._setup_shortcuts(window)

        self.assertIs(window._find_shortcut, shortcut)
        args, _kwargs = shortcut_cls.call_args
        self.assertEqual(window, args[1])
        self.assertEqual("Ctrl+F", args[0].toString())
        shortcut.setContext.assert_called_once_with(Qt.WindowShortcut)
        shortcut.activated.connect.assert_called_once_with(window._focus_overview_search)

    def test_settings_dialog_api_key_is_locked_and_masked_by_default(self):
        from app_gui.main import SettingsDialog, PROVIDER_DEFAULTS

        provider_id = next(iter(PROVIDER_DEFAULTS))
        dialog = SettingsDialog(config={"api_keys": {provider_id: "sk-initial"}})

        api_edit = dialog._api_key_edits[provider_id]
        self.assertTrue(api_edit.isReadOnly())
        self.assertEqual(QLineEdit.Password, api_edit.echoMode())

    def test_help_dialog_feedback_support_controls_are_available(self):
        from app_gui.main import HelpDialog
        from app_gui.i18n import tr

        dialog = HelpDialog()
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(tr("settings.feedbackPlaceholder"), dialog.feedback_edit.placeholderText())
        self.assertEqual(tr("settings.feedbackSubmit"), dialog.feedback_submit_btn.text())
        self.assertEqual("", dialog.feedback_email_copy_btn.text())
        self.assertEqual("", dialog.feedback_qq_copy_btn.text())
        self.assertEqual(tr("settings.feedbackCopyEmailTooltip"), dialog.feedback_email_copy_btn.toolTip())
        self.assertEqual(tr("settings.feedbackCopyQQTooltip"), dialog.feedback_qq_copy_btn.toolTip())

        dialog._copy_feedback_email()
        self.assertEqual("fym22@mails.tsinghua.edu.cn", QApplication.clipboard().text())
        self.assertEqual(tr("settings.feedbackEmailCopied"), dialog.feedback_status_label.text())
        self.assertEqual(tr("settings.feedbackCopiedTooltip"), dialog.feedback_email_copy_btn.toolTip())

        dialog._copy_feedback_qq_group()
        self.assertEqual("471436975", QApplication.clipboard().text())
        self.assertEqual(tr("settings.feedbackQQCopied"), dialog.feedback_status_label.text())
        self.assertEqual(tr("settings.feedbackCopiedTooltip"), dialog.feedback_qq_copy_btn.toolTip())

        dialog.feedback_edit.setPlainText("")
        dialog._submit_feedback()
        self.assertEqual(tr("settings.feedbackEmpty"), dialog.feedback_status_label.text())

    def test_settings_dialog_excludes_help_feedback_controls(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(config={})
        self.addCleanup(dialog.deleteLater)

        self.assertFalse(hasattr(dialog, "feedback_edit"))
        self.assertFalse(hasattr(dialog, "feedback_submit_btn"))
        self.assertFalse(hasattr(dialog, "_check_update_btn"))

    def test_settings_dialog_long_hints_are_inline_info_tooltips(self):
        from app_gui.main import SettingsDialog
        from app_gui.i18n import tr
        from PySide6.QtWidgets import QLabel

        dialog = SettingsDialog(config={})
        self.addCleanup(dialog.deleteLater)

        info_labels = dialog.findChildren(QLabel, "settingsInlineInfoLabel")
        tooltip_sources = [label.accessibleName() for label in info_labels]
        label_texts = [label.text() for label in dialog.findChildren(QLabel)]

        self.assertNotIn(tr("settings.inventoryFileLockedHint"), label_texts)
        self.assertNotIn(tr("settings.dataRootHint"), label_texts)
        self.assertNotIn(tr("settings.localApiHint"), label_texts)
        self.assertTrue(info_labels)
        self.assertTrue(all(label.text() == "i" for label in info_labels))
        self.assertIn(tr("settings.inventoryFileLockedHint"), tooltip_sources)
        self.assertIn(tr("settings.dataRootHint"), tooltip_sources)
        self.assertIn(tr("settings.localApiHint"), tooltip_sources)
        self.assertIn(tr("settings.localApiSkillTemplateHint"), tooltip_sources)
        self.assertIn(tr("settings.customPromptHint"), tooltip_sources)

    def test_custom_fields_dialog_structural_fields_use_canonical_names(self):
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))

        expected_by_language = {
            "en": [
                ("id", "ID"),
                ("box", "Box"),
                ("position", "Position"),
                ("stored_at", "Deposited Date"),
                ("storage_events", "History Events"),
            ],
            "zh-CN": [
                ("id", "ID"),
                ("box", "盒子"),
                ("position", "位置"),
                ("stored_at", "存入日期"),
                ("storage_events", "历史事件"),
            ],
        }

        for language, expected_pairs in expected_by_language.items():
            self.assertTrue(set_language(language))
            dialog = CustomFieldsDialog()
            self.addCleanup(dialog.deleteLater)

            structural_pairs = [
                (key, label)
                for key, label, _field_type, _required in dialog._structural_display
            ]

            self.assertEqual(expected_pairs, structural_pairs)
            self.assertNotIn("frozen_at", {key for key, _label in structural_pairs})
            self.assertNotIn("thaw_events", {key for key, _label in structural_pairs})

    def test_custom_fields_dialog_move_up_updates_order_and_preserves_selectors(self):
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        dialog = CustomFieldsDialog(
            custom_fields=[
                {"key": "short_name", "label": "Short Name", "type": "str"},
                {"key": "project_code", "label": "Project Code", "type": "str"},
            ],
            display_key="project_code",
            color_key="project_code",
        )
        self.addCleanup(dialog.deleteLater)

        initial_keys = [entry["key"].text().strip() for entry in dialog._field_rows]
        self.assertEqual(["note", "short_name", "project_code"], initial_keys)
        self.assertFalse(dialog._field_rows[0]["_move_up_btn"].isEnabled())
        self.assertTrue(dialog._field_rows[-1]["_move_up_btn"].isEnabled())
        self.assertFalse(dialog._field_rows[-1]["_move_down_btn"].isEnabled())

        QTest.mouseClick(dialog._field_rows[-1]["_move_up_btn"], Qt.LeftButton)

        reordered_keys = [entry["key"].text().strip() for entry in dialog._field_rows]
        self.assertEqual(["note", "project_code", "short_name"], reordered_keys)
        self.assertEqual("project_code", dialog.get_display_key())
        self.assertEqual("project_code", dialog.get_color_key())

        display_items = [
            dialog._display_key_combo.itemData(index)
            for index in range(dialog._display_key_combo.count())
        ]
        color_items = [
            dialog._color_key_combo.itemData(index)
            for index in range(dialog._color_key_combo.count())
        ]
        self.assertEqual(["note", "project_code", "short_name"], display_items)
        self.assertEqual(display_items, color_items)

    def test_custom_fields_dialog_note_row_can_move_but_cannot_be_removed(self):
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        dialog = CustomFieldsDialog(
            custom_fields=[
                {"key": "sample_type", "label": "Sample Type", "type": "str"},
            ],
        )
        self.addCleanup(dialog.deleteLater)

        note_entry = dialog._field_rows[0]
        self.assertEqual("note", note_entry["key"].text().strip())
        self.assertFalse(note_entry["_remove_btn"].isEnabled())
        self.assertFalse(note_entry["_move_up_btn"].isEnabled())
        self.assertTrue(note_entry["_move_down_btn"].isEnabled())

        QTest.mouseClick(note_entry["_move_down_btn"], Qt.LeftButton)

        reordered_keys = [entry["key"].text().strip() for entry in dialog._field_rows]
        self.assertEqual(["sample_type", "note"], reordered_keys)
        moved_note_entry = dialog._field_rows[-1]
        self.assertEqual("note", moved_note_entry["key"].text().strip())
        self.assertTrue(moved_note_entry["_move_up_btn"].isEnabled())
        self.assertFalse(moved_note_entry["_move_down_btn"].isEnabled())
        self.assertFalse(moved_note_entry["_remove_btn"].isEnabled())

    def test_custom_fields_dialog_preserves_blocked_fixed_field_rename_attempt(self):
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        dialog = CustomFieldsDialog(
            custom_fields=[
                {"key": "short_name", "label": "Short Name", "type": "str"},
            ],
        )
        self.addCleanup(dialog.deleteLater)

        rename_entry = next(
            entry for entry in dialog._field_rows
            if entry["key"].text().strip() == "short_name"
        )
        rename_entry["key"].setText("note")

        fields = dialog.get_custom_fields()
        blocked_entries = [
            item for item in fields
            if item.get("key") == "note" and item.get("_original_key") == "short_name"
        ]
        self.assertEqual(1, len(blocked_entries))

    def test_custom_fields_dialog_rejects_accept_when_key_has_space(self):
        """Lock issue #32: keys containing spaces must trigger an error dialog
        instead of being silently dropped on save.
        """
        from unittest.mock import patch

        from app_gui.i18n import get_language, set_language
        from app_gui.ui.dialogs import custom_fields_dialog as cf_module
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        previous_language = get_language()
        set_language("en")
        self.addCleanup(lambda: set_language(previous_language))

        dialog = CustomFieldsDialog(
            custom_fields=[{"key": "short_name", "label": "Short Name", "type": "str"}],
        )
        self.addCleanup(dialog.deleteLater)

        accepted = {"count": 0}
        orig_accept = dialog.accept
        dialog.accept = lambda: accepted.__setitem__("count", accepted["count"] + 1)
        self.addCleanup(lambda: setattr(dialog, "accept", orig_accept))

        target_entry = next(
            entry for entry in dialog._field_rows
            if entry["key"].text().strip() == "short_name"
        )
        target_entry["key"].setText("project name")

        captured = {"shown": 0, "text": ""}

        def _fake_warning(parent, title, text):
            captured["shown"] += 1
            captured["text"] = text

        with patch.object(cf_module, "show_warning_message", side_effect=lambda parent, *, title, text, informative_text="", detailed_text=None: _fake_warning(parent, title, text)):
            dialog._on_accept_requested()

        self.assertEqual(1, captured["shown"])
        self.assertIn("project name", captured["text"])
        self.assertEqual(0, accepted["count"])

    def test_custom_fields_dialog_accepts_when_all_keys_valid(self):
        """Lock issue #32 complement: a clean save still accepts without warning."""
        from unittest.mock import patch

        from app_gui.ui.dialogs import custom_fields_dialog as cf_module
        from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog

        dialog = CustomFieldsDialog(
            custom_fields=[{"key": "short_name", "label": "Short Name", "type": "str"}],
        )
        self.addCleanup(dialog.deleteLater)

        accepted = {"count": 0}
        orig_accept = dialog.accept
        dialog.accept = lambda: accepted.__setitem__("count", accepted["count"] + 1)
        self.addCleanup(lambda: setattr(dialog, "accept", orig_accept))

        with patch.object(cf_module, "show_warning_message") as mock_warn:
            dialog._on_accept_requested()

        self.assertEqual(0, mock_warn.call_count)
        self.assertEqual(1, accepted["count"])

    def test_settings_dialog_api_key_unlock_and_relock(self):
        from app_gui.main import SettingsDialog, PROVIDER_DEFAULTS

        provider_id = next(iter(PROVIDER_DEFAULTS))
        dialog = SettingsDialog(config={"api_keys": {provider_id: "sk-initial"}})

        api_edit = dialog._api_key_edits[provider_id]
        lock_btn = dialog._api_key_lock_buttons[provider_id]

        lock_btn.click()
        self.assertFalse(api_edit.isReadOnly())
        self.assertEqual(QLineEdit.Normal, api_edit.echoMode())

        lock_btn.click()
        self.assertTrue(api_edit.isReadOnly())
        self.assertEqual(QLineEdit.Password, api_edit.echoMode())

    def test_settings_dialog_get_values_reads_updated_api_key(self):
        from app_gui.main import SettingsDialog, PROVIDER_DEFAULTS

        provider_id = next(iter(PROVIDER_DEFAULTS))
        dialog = SettingsDialog(config={"api_keys": {provider_id: "sk-initial"}})

        api_edit = dialog._api_key_edits[provider_id]
        lock_btn = dialog._api_key_lock_buttons[provider_id]
        lock_btn.click()
        api_edit.setText("sk-updated")

        values = dialog.get_values()
        self.assertEqual("sk-updated", values["api_keys"][provider_id])

    def test_settings_dialog_get_submission_returns_typed_contract(self):
        from app_gui.application import SettingsDialogSubmission
        from app_gui.main import SettingsDialog, PROVIDER_DEFAULTS

        provider_id = next(iter(PROVIDER_DEFAULTS))
        dialog = SettingsDialog(
            config={
                "ai": {
                    "provider": provider_id,
                    "model": PROVIDER_DEFAULTS[provider_id]["model"],
                }
            }
        )

        submission = dialog.get_submission()

        self.assertIsInstance(submission, SettingsDialogSubmission)
        self.assertEqual(dialog.get_values(), submission.as_dict())

    def test_settings_dialog_submission_includes_local_open_api_fields(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(
            config={
                "yaml_path": self.fake_yaml_path,
                "open_api": {"enabled": True, "port": 40123},
            }
        )

        submission = dialog.get_submission()

        self.assertTrue(submission.open_api_enabled)
        self.assertEqual(40123, submission.open_api_port)

    def test_settings_dialog_exposes_read_only_local_api_skill_template_and_copy_button(self):
        from app_gui.main import SettingsDialog

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        dialog = SettingsDialog(config={"yaml_path": self.fake_yaml_path, "language": "en"})
        template_edit = dialog.findChild(QPlainTextEdit, "localApiSkillTemplateEdit")
        copy_button = dialog.findChild(QPushButton, "localApiSkillCopyButton")

        self.assertIsNotNone(template_edit)
        self.assertIsNotNone(copy_button)
        self.assertTrue(template_edit.isReadOnly())
        self.assertGreaterEqual(template_edit.minimumHeight(), 120)
        self.assertEqual(160, template_edit.maximumHeight())
        self.assertEqual(Qt.WheelFocus, template_edit.focusPolicy())
        self.assertGreaterEqual(template_edit.verticalScrollBar().singleStep(), 18)
        self.assertIn("name: snowfox-local-api", template_edit.toPlainText())
        self.assertIn("`case_sensitive`", template_edit.toPlainText())
        self.assertIn("`summary_only`", template_edit.toPlainText())
        self.assertIn("`keywords`", template_edit.toPlainText())

        QApplication.clipboard().setText("")
        copy_button.click()

        self.assertEqual(template_edit.toPlainText(), QApplication.clipboard().text())
        self.assertEqual(tr("settings.localApiSkillCopied"), copy_button.text())

    def test_settings_dialog_local_api_skill_template_follows_selected_language(self):
        from app_gui.main import SettingsDialog

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        dialog = SettingsDialog(config={"yaml_path": self.fake_yaml_path, "language": "zh-CN"})
        template_edit = dialog.findChild(QPlainTextEdit, "localApiSkillTemplateEdit")

        self.assertIn("# SnowFox 本地 Open API", template_edit.toPlainText())
        self.assertIn("查询参数", template_edit.toPlainText())
        self.assertIn("`/api/v1/capabilities`", template_edit.toPlainText())
        self.assertIn("`dataset_schema`", template_edit.toPlainText())
        self.assertIn("`response_shapes`", template_edit.toPlainText())
        self.assertIn("`summary_only`", template_edit.toPlainText())

    def test_settings_dialog_local_api_skill_template_falls_back_to_english(self):
        import tempfile
        from pathlib import Path

        from app_gui.main import SettingsDialog

        with tempfile.TemporaryDirectory(prefix="snowfox_skill_tpl_") as temp_dir:
            root = Path(temp_dir)
            assets_dir = root / "app_gui" / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "local_api_skill_template.en.md").write_text(
                "english fallback template",
                encoding="utf-8",
            )

            dialog = SettingsDialog(
                config={"yaml_path": self.fake_yaml_path, "language": "zh-CN"},
                root_dir=str(root),
            )
            template_edit = dialog.findChild(QPlainTextEdit, "localApiSkillTemplateEdit")
            copy_button = dialog.findChild(QPushButton, "localApiSkillCopyButton")

            self.assertEqual("english fallback template", template_edit.toPlainText())
            self.assertTrue(copy_button.isEnabled())

    def test_settings_dialog_ai_model_is_editable_and_persisted(self):
        from app_gui.main import SettingsDialog, PROVIDER_DEFAULTS

        provider_id = next(iter(PROVIDER_DEFAULTS))
        default_model = PROVIDER_DEFAULTS[provider_id]["model"]
        dialog = SettingsDialog(config={"ai": {"provider": provider_id, "model": default_model}})

        self.assertTrue(dialog.ai_model_edit.isEnabled())
        dialog.ai_model_edit.setEditText("custom-model-id")

        values = dialog.get_values()
        self.assertEqual("custom-model-id", values["ai_model"])

    def test_settings_dialog_provider_switch_updates_model_dropdown_options(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(config={"ai": {"provider": "zhipu", "model": "glm-5"}})
        options = [dialog.ai_model_edit.itemText(i) for i in range(dialog.ai_model_edit.count())]

        self.assertIn("glm-5", options)
        self.assertIn("glm-4.7", options)

    def test_settings_dialog_uses_readable_zhipu_provider_label(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(config={"ai": {"provider": "zhipu", "model": "glm-5"}})

        self.assertEqual("Zhipu AI (GLM)", dialog.ai_provider_combo.currentText())

    def test_settings_dialog_import_handoff_closes_dialog_for_ai_panel(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(
            config={"yaml_path": self.fake_yaml_path},
            on_import_existing_data=lambda **_kwargs: "awaiting_ai",
        )

        with patch.object(dialog, "reject") as reject_mock:
            dialog._open_import_journey()

        reject_mock.assert_called_once()

    def test_settings_dialog_custom_fields_editor_blocks_legacy_box_fields(self):
        import shutil
        import tempfile
        import yaml
        from pathlib import Path
        from app_gui.main import SettingsDialog

        tmpdir = tempfile.mkdtemp(prefix="ln2_settings_box_fields_")
        yaml_path = Path(tmpdir) / "inventory.yaml"
        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 1,
                    "box_numbers": [1],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
                "box_fields": {
                    "1": [
                        {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                    ]
                },
            },
            "inventory": [],
        }
        yaml_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        dialog_cls = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": str(yaml_path)},
            custom_fields_dialog_cls=dialog_cls,
        )

        try:
            with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warning_mock:
                dialog._open_custom_fields_editor()

            warning_mock.assert_called_once()
            self.assertIn("meta.box_fields", warning_mock.call_args.kwargs["text"])
            dialog_cls.assert_not_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_settings_dialog_custom_fields_save_preserves_reordered_field_order(self):
        from app_gui.main import SettingsDialog
        from lib.csv_export import build_export_columns
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 2,
                    "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                    {"key": "project_code", "label": "Project Code", "type": "str"},
                ],
                "display_key": "short_name",
                "color_key": "short_name",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "short_name": "clone-a",
                    "project_code": "P-001",
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-reordered-save", payload=payload)
        on_data_changed = MagicMock()

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def exec():
                return 1

            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "project_code", "label": "Project Code", "type": "str"},
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                ]

            @staticmethod
            def get_display_key():
                return "project_code"

            @staticmethod
            def get_color_key():
                return "project_code"

        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        saved_keys = [
            field.get("key")
            for field in (saved_meta.get("custom_fields") or [])
            if isinstance(field, dict)
        ]
        self.assertEqual(["project_code", "short_name"], saved_keys)
        self.assertEqual("project_code", saved_meta.get("display_key"))
        self.assertEqual("project_code", saved_meta.get("color_key"))
        self.assertEqual(
            ["id", "location", "frozen_at", "note", "project_code", "short_name", "thaw_events"],
            build_export_columns(saved_meta, split_location=False),
        )

    def test_settings_dialog_custom_fields_allows_option_removal_even_when_records_use_old_value(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "custom_fields": [],
                "cell_line_required": True,
                "cell_line_options": ["K562", "HeLa"],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "note": None,
                    "thaw_events": None,
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-cell-line-strict", payload=payload)
        on_data_changed = MagicMock()

        class _FakeCustomFieldsDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def exec():
                return 1

            @staticmethod
            def get_custom_fields():
                return [{"key": "cell_line", "label": "Cell Line", "type": "str"}]

            @staticmethod
            def get_display_key():
                return ""

            @staticmethod
            def get_color_key():
                return "cell_line"

        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeCustomFieldsDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        # Meta-only validation: removing an option should NOT be blocked
        # even though a record still uses the removed value.
        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        self.assertNotIn("cell_line_options", saved_meta)
        self.assertNotIn("cell_line_required", saved_meta)
        saved_cell_line_field = next(
            field
            for field in (saved_meta.get("custom_fields") or [])
            if str(field.get("key") or "") == "cell_line"
        )
        self.assertNotIn("options", saved_cell_line_field)

    def test_settings_dialog_custom_fields_allows_adding_required_field(self):
        """Scenario 2: adding a new required field should not be blocked
        by existing records that lack the field."""
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-add-required", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "passage", "label": "Passage", "type": "int", "required": True},
                ]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_cf_keys = [f["key"] for f in saved.get("meta", {}).get("custom_fields", [])]
        self.assertIn("passage", saved_cf_keys)

    def test_settings_dialog_custom_fields_allows_making_field_required(self):
        """Scenario 3: changing a field from optional to required should not
        be blocked by records with empty values."""
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "tissue", "label": "Tissue", "type": "str"},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562", "tissue": ""},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-make-required", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "tissue", "label": "Tissue", "type": "str", "required": True},
                ]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved_cf = (load_yaml(yaml_path) or {}).get("meta", {}).get("custom_fields", [])
        tissue = next(f for f in saved_cf if f["key"] == "tissue")
        self.assertTrue(tissue.get("required"))

    def test_settings_dialog_custom_fields_allows_adding_options_to_freetext(self):
        """Scenario 4: adding options to a free-text field should not be
        blocked by records whose values are not in the new options list."""
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "source", "label": "Source", "type": "str"},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562", "source": "custom_value"},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-add-options", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "source", "label": "Source", "type": "str",
                     "options": ["Lab A", "Lab B"]},
                ]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved_cf = (load_yaml(yaml_path) or {}).get("meta", {}).get("custom_fields", [])
        source_def = next(f for f in saved_cf if f["key"] == "source")
        self.assertEqual(["Lab A", "Lab B"], source_def.get("options"))
        # Record data kept intact — "custom_value" NOT removed
        inv = (load_yaml(yaml_path) or {}).get("inventory", [])
        self.assertEqual("custom_value", inv[0].get("source"))

    def test_settings_dialog_custom_fields_still_blocks_meta_errors(self):
        """Scenario 9: structural meta errors must still block saving."""
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-bad-display-key", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                # Structural key cannot be declared as a custom field.
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "box", "label": "Box", "type": "str"},
                ]
            @staticmethod
            def get_display_key(): return "cell_line"
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_called_once()
        on_data_changed.assert_not_called()

        # YAML should NOT have been modified
        saved_meta = (load_yaml(yaml_path) or {}).get("meta", {})
        self.assertEqual(
            [{"key": "cell_line", "label": "Cell Line", "type": "str"}],
            saved_meta.get("custom_fields"),
        )

    def test_settings_dialog_custom_fields_blocks_conflicting_rename(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                    {"key": "alias", "label": "Alias", "type": "str"},
                ],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "short_name": "clone-A",
                    "alias": "alpha",
                },
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-rename-conflict", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "alias", "label": "Alias", "type": "str", "_original_key": "short_name"},
                ]
            @staticmethod
            def get_display_key(): return "alias"
            @staticmethod
            def get_color_key(): return "alias"
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_called_once()
        self.assertIn("Field rename conflict detected", str(warn_mock.call_args.kwargs["text"]))
        on_data_changed.assert_not_called()

        saved = load_yaml(yaml_path) or {}
        record = (saved.get("inventory") or [{}])[0]
        self.assertEqual("clone-A", record.get("short_name"))
        self.assertEqual("alpha", record.get("alias"))

    def test_settings_dialog_custom_fields_blocks_rename_to_fixed_system_field_before_delete_flow(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                ],
                "display_key": "short_name",
                "color_key": "short_name",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "short_name": "clone-A",
                },
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-rename-to-note-blocked", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "note", "label": "Note", "type": "str", "multiline": True},
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "note", "label": "Short Name", "type": "str", "_original_key": "short_name"},
                ]
            @staticmethod
            def get_display_key(): return "note"
            @staticmethod
            def get_color_key(): return "note"
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, patch.object(
            dialog,
            "_format_removed_field_preview_summary",
            side_effect=AssertionError("remove-data preview should not run"),
        ):
            dialog._open_custom_fields_editor()

        warn_mock.assert_called_once()
        self.assertIn("Field rename blocked", str(warn_mock.call_args.kwargs["text"]))
        on_data_changed.assert_not_called()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        self.assertEqual("short_name", saved_meta.get("display_key"))
        self.assertEqual("short_name", saved_meta.get("color_key"))
        record = (saved.get("inventory") or [{}])[0]
        self.assertEqual("clone-A", record.get("short_name"))
        self.assertNotIn("note", record)

    def test_settings_dialog_custom_fields_selector_keys_follow_rename(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "old_tag", "label": "Old Tag", "type": "str"},
                ],
                "display_key": "old_tag",
                "color_key": "old_tag",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "old_tag": "tag-A",
                },
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-rename-selector-follow", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "new_tag", "label": "New Tag", "type": "str", "_original_key": "old_tag"},
                ]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        self.assertEqual("new_tag", saved_meta.get("display_key"))
        self.assertEqual("new_tag", saved_meta.get("color_key"))
        record = (saved.get("inventory") or [{}])[0]
        self.assertEqual("tag-A", record.get("new_tag"))
        self.assertNotIn("old_tag", record)

    def test_settings_dialog_custom_fields_save_creates_backup_and_audit(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import list_yaml_backups, load_yaml, read_audit_events

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                ],
                "display_key": "short_name",
                "color_key": "short_name",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "short_name": "clone-A",
                },
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-save-backup-audit", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "alias", "label": "Alias", "type": "str", "_original_key": "short_name"},
                ]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        self.assertEqual("alias", saved_meta.get("display_key"))
        self.assertEqual("alias", saved_meta.get("color_key"))
        self.assertTrue(list_yaml_backups(yaml_path))

        events = read_audit_events(yaml_path) or []
        actions = [str(ev.get("action") or "") for ev in events]
        self.assertIn("backup", actions)
        self.assertIn("edit_custom_fields", actions)
        edit_events = [ev for ev in events if str(ev.get("action") or "") == "edit_custom_fields"]
        self.assertTrue(edit_events)
        details = dict(edit_events[-1].get("details") or {})
        self.assertEqual("edit_custom_fields", details.get("op"))
        self.assertIn({"from": "short_name", "to": "alias"}, details.get("renames") or [])

    def test_settings_dialog_custom_fields_rename_cell_line_to_type_has_no_ghost_field(self):
        from app_gui.main import SettingsDialog
        from lib.custom_fields import get_effective_fields
        from lib.yaml_ops import load_yaml

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                ],
                "display_key": "cell_line",
                "color_key": "cell_line",
                "cell_line_required": True,
                "cell_line_options": ["K562", "HeLa"],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                },
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-rename-cell-line-to-type", payload=payload)

        class _FakeDialog:
            def __init__(self, *a, **kw): pass
            @staticmethod
            def exec(): return 1
            @staticmethod
            def get_custom_fields():
                return [{"key": "type", "label": "Type", "type": "str", "_original_key": "cell_line"}]
            @staticmethod
            def get_display_key(): return ""
            @staticmethod
            def get_color_key(): return ""
        on_data_changed = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._open_custom_fields_editor()

        warn_mock.assert_not_called()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        saved_meta = saved.get("meta") or {}
        custom_keys = [f.get("key") for f in (saved_meta.get("custom_fields") or []) if isinstance(f, dict)]
        self.assertEqual(["type"], custom_keys)
        self.assertNotIn("cell_line_required", saved_meta)
        self.assertNotIn("cell_line_options", saved_meta)
        self.assertEqual("type", saved_meta.get("display_key"))
        self.assertEqual("type", saved_meta.get("color_key"))

        record = (saved.get("inventory") or [{}])[0]
        self.assertEqual("K562", record.get("type"))
        self.assertNotIn("cell_line", record)

        effective_keys = [f.get("key") for f in get_effective_fields(saved_meta)]
        self.assertIn("type", effective_keys)
        self.assertIn("note", effective_keys)
        self.assertNotIn("cell_line", effective_keys)

    def test_settings_dialog_accept_still_blocks_on_path_change_to_invalid_yaml(self):
        """accept() must still enforce strict validation when the user
        selects a different YAML file."""
        from app_gui.main import SettingsDialog

        # Create a YAML with a meta-level error (trailing-space color_key)
        bad_payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "color_key": "cell_line ",
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        bad_path = self.ensure_dataset_yaml("accept-bad-path-change", payload=bad_payload)
        good_path = self.ensure_dataset_yaml("accept-good-origin")

        dialog = SettingsDialog(config={"yaml_path": good_path})
        # Simulate user changing the path to the bad file
        dialog.yaml_edit.setText(bad_path)

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, \
             patch("app_gui.ui.dialogs.settings_dialog.QDialog.accept") as accept_mock:
            dialog.accept()

        warn_mock.assert_called_once()
        accept_mock.assert_not_called()

    def test_settings_dialog_accept_allows_close_when_path_unchanged(self):
        """accept() should not block when the YAML path is unchanged, even
        if records have stale option values from a field-definition edit."""
        from app_gui.main import SettingsDialog

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str",
                     "options": ["HeLa"]},
                ],
                "cell_line_options": ["HeLa"],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("accept-path-unchanged", payload=payload)
        dialog = SettingsDialog(config={"yaml_path": yaml_path})

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, \
             patch("app_gui.ui.dialogs.settings_dialog.QDialog.accept") as accept_mock:
            dialog.accept()

        # record has "K562" not in options ["HeLa"], but path unchanged
        # → meta-only validation → no per-record blocking
        warn_mock.assert_not_called()
        accept_mock.assert_called_once()

    def test_settings_dialog_accept_blocks_meta_error_even_when_path_unchanged(self):
        """accept() must still block meta-level errors (undeclared fields)
        even when the YAML path is unchanged."""
        from app_gui.main import SettingsDialog

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562", "undeclared_xyz": "bad"},
            ],
        }
        yaml_path = self.ensure_dataset_yaml("accept-meta-err-same-path", payload=payload)
        dialog = SettingsDialog(config={"yaml_path": yaml_path})

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, \
             patch("app_gui.ui.dialogs.settings_dialog.QDialog.accept") as accept_mock:
            dialog.accept()

        warn_mock.assert_called_once()
        accept_mock.assert_not_called()
        warning_text = str(warn_mock.call_args.kwargs["text"])
        self.assertIn("undeclared_xyz", warning_text)
        from app_gui.main import SettingsDialog

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "custom_fields": [],
                "color_key": "cell_line ",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "note": None,
                    "thaw_events": None,
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("settings-invalid-color-key", payload=payload)
        dialog = SettingsDialog(config={"yaml_path": yaml_path})

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, patch(
            "app_gui.ui.dialogs.settings_dialog.QDialog.accept"
        ) as accept_mock:
            dialog.accept()

        warn_mock.assert_called_once()
        accept_mock.assert_not_called()
        warning_text = str(warn_mock.call_args.kwargs["text"])
        self.assertIn("meta.color_key", warning_text)

    def test_settings_dialog_accept_blocks_undeclared_record_fields_and_reports_names(self):
        from app_gui.main import SettingsDialog

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "custom_fields": [],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "short_name": "K562_A1",
                    "plasmid_name": "PB-demo",
                    "note": None,
                    "thaw_events": None,
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("settings-undeclared-record-fields", payload=payload)
        dialog = SettingsDialog(config={"yaml_path": yaml_path})

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, patch(
            "app_gui.ui.dialogs.settings_dialog.QDialog.accept"
        ) as accept_mock:
            dialog.accept()

        warn_mock.assert_called_once()
        accept_mock.assert_not_called()
        warning_text = str(warn_mock.call_args.kwargs["text"])
        self.assertIn("Unsupported inventory field(s)", warning_text)
        self.assertIn("short_name", warning_text)
        self.assertIn("plasmid_name", warning_text)

    def test_settings_dialog_accept_allows_custom_field_color_key(self):
        from app_gui.main import SettingsDialog

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str", "required": False},
                    {"key": "short_name", "label": "Short Name", "type": "str", "required": False}
                ],
                "color_key": "short_name",
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "cell_line": "K562",
                    "short_name": "K562_A1",
                    "note": None,
                    "thaw_events": None,
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("settings-valid-color-key", payload=payload)
        dialog = SettingsDialog(config={"yaml_path": yaml_path})

        with patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock, patch(
            "app_gui.ui.dialogs.settings_dialog.QDialog.accept"
        ) as accept_mock:
            dialog.accept()

        warn_mock.assert_not_called()
        accept_mock.assert_called_once()

    def test_settings_dialog_export_csv_uses_selected_yaml(self):
        from app_gui.main import SettingsDialog

        export_mock = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": self.fake_yaml_path},
            on_export_inventory_csv=export_mock,
        )

        dialog.export_csv_btn.click()

        export_mock.assert_called_once_with(
            parent=dialog,
            yaml_path_override=dialog.yaml_edit.text().strip(),
        )

    def test_settings_dialog_rename_dataset_updates_selected_yaml(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        new_path = self.ensure_dataset_yaml("renamed-by-settings")
        rename_mock = MagicMock(return_value=new_path)
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_rename_dataset=rename_mock,
        )

        with patch(
            "app_gui.ui.dialogs.settings_dialog.QInputDialog.getText",
            return_value=("renamed-by-settings", True),
        ):
            dialog._emit_rename_dataset_request()

        rename_mock.assert_called_once_with(old_path, "renamed-by-settings")
        self.assertEqual(os.path.abspath(new_path), dialog.yaml_edit.text())

    def test_settings_dialog_rename_dataset_shows_warning_on_failure(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_rename_dataset=MagicMock(side_effect=RuntimeError("rename failed")),
        )

        with patch(
            "app_gui.ui.dialogs.settings_dialog.QInputDialog.getText",
            return_value=("renamed-by-settings", True),
        ), patch("app_gui.ui.dialogs.settings_dialog.show_warning_message") as warn_mock:
            dialog._emit_rename_dataset_request()

        warn_mock.assert_called_once()
        self.assertEqual(os.path.abspath(old_path), dialog.yaml_edit.text())

    def test_settings_dialog_delete_dataset_updates_selected_yaml(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        new_path = self.ensure_dataset_yaml("after-delete")
        delete_mock = MagicMock(return_value=new_path)
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_delete_dataset=delete_mock,
        )

        with patch.object(dialog, "_confirm_delete_dataset_initial", return_value=True), patch.object(
            dialog, "_confirm_phrase_dialog", return_value=True
        ):
            dialog._confirm_delete_dataset_final = MagicMock(return_value=True)
            dialog._emit_delete_dataset_request()

        delete_mock.assert_called_once_with(old_path)
        self.assertEqual(os.path.abspath(new_path), dialog.yaml_edit.text())

    def test_settings_dialog_delete_dataset_shows_warning_on_failure(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_delete_dataset=MagicMock(side_effect=RuntimeError("delete failed")),
        )

        with patch.object(dialog, "_confirm_delete_dataset_initial", return_value=True), patch.object(
            dialog, "_confirm_phrase_dialog", return_value=True
        ), patch.object(dialog, "_confirm_delete_dataset_final", return_value=True), patch(
            "app_gui.ui.dialogs.settings_dialog.show_warning_message"
        ) as warn_mock:
            dialog._emit_delete_dataset_request()

        warn_mock.assert_called_once()
        self.assertEqual(os.path.abspath(old_path), dialog.yaml_edit.text())

    def test_settings_dialog_delete_dataset_requires_phrase_confirmation(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        delete_mock = MagicMock(return_value=self.ensure_dataset_yaml("phrase-should-not-pass"))
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_delete_dataset=delete_mock,
        )

        with patch.object(dialog, "_confirm_delete_dataset_initial", return_value=True), patch.object(
            dialog, "_confirm_phrase_dialog", return_value=False
        ), patch.object(dialog, "_confirm_delete_dataset_final", return_value=True) as final_mock:
            dialog._emit_delete_dataset_request()

        delete_mock.assert_not_called()
        final_mock.assert_not_called()
        self.assertEqual(os.path.abspath(old_path), dialog.yaml_edit.text())

    def test_settings_dialog_delete_dataset_phrase_stays_english_in_zh_locale(self):
        from app_gui.main import SettingsDialog

        old_path = self.fake_yaml_path
        delete_mock = MagicMock()
        dialog = SettingsDialog(
            config={"yaml_path": old_path},
            on_delete_dataset=delete_mock,
        )

        original_language = get_language()
        set_language("zh-CN")
        try:
            with patch.object(dialog, "_confirm_delete_dataset_initial", return_value=True), patch.object(
                dialog, "_confirm_phrase_dialog", return_value=False
            ) as phrase_mock, patch.object(
                dialog, "_confirm_delete_dataset_final", return_value=True
            ) as final_mock:
                dialog._emit_delete_dataset_request()

            dataset_name = os.path.basename(os.path.dirname(os.path.abspath(old_path)))
            expected_phrase = f"DELETE DATASET {dataset_name}"

            phrase_mock.assert_called_once()
            kwargs = phrase_mock.call_args.kwargs
            self.assertEqual(expected_phrase, kwargs.get("phrase"))
            self.assertIn(expected_phrase, kwargs.get("prompt_text", ""))
            final_mock.assert_not_called()
            delete_mock.assert_not_called()
        finally:
            set_language(original_language)

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

    def test_operations_panel_prefill_context_shows_status_when_record_missing(self):
        panel = self._new_operations_panel()

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertFalse(panel.t_ctx_status.isHidden())
        self.assertEqual(tr("operations.recordNotFound"), panel.t_ctx_status.text())

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
