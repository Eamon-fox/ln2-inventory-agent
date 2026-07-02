"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from lib.plan_store import PlanStore
from PySide6.QtWidgets import QSizePolicy


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsSettingsDialogTests(GuiPanelsBaseCase):
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

        dialog = SettingsDialog(config={"ai": {"provider": "zhipu", "model": "glm-5.1"}})
        options = [dialog.ai_model_edit.itemText(i) for i in range(dialog.ai_model_edit.count())]

        self.assertIn("glm-5.2", options)
        self.assertIn("glm-4.7", options)
        self.assertNotIn("glm-5.1", options)
        self.assertNotIn("glm-5", options)

    def test_settings_dialog_uses_readable_zhipu_provider_label(self):
        from app_gui.main import SettingsDialog

        dialog = SettingsDialog(config={"ai": {"provider": "zhipu", "model": "glm-5.1"}})

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

