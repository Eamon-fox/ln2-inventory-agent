"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from lib.plan_store import PlanStore
from PySide6.QtWidgets import QSizePolicy


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsCustomFieldsTests(GuiPanelsBaseCase):
    def test_operations_panel_refresh_custom_fields_delegates_to_apply_meta_update(self):
        panel = self._new_operations_panel()

        with patch.object(panel, "apply_meta_update") as apply_meta_update:
            panel._refresh_custom_fields()

        apply_meta_update.assert_called_once_with()

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

