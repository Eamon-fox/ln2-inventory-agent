"""Settings dialog delete-preview integration tests."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class SettingsDialogRemovePreviewTests(GuiPanelsBaseCase):
    def _capture_remove_preview_message(self, captured, *, click_role):
        def _fake_exec(msg):
            captured.append(
                {
                    "text": msg.text(),
                    "informative": msg.informativeText(),
                    "details": msg.detailedText(),
                }
            )
            for button in msg.buttons():
                if msg.buttonRole(button) != click_role:
                    continue
                button.click()
                break
            return 0

        return patch.object(QMessageBox, "exec", new=_fake_exec)

    def test_remove_data_preview_shows_summary_and_details_before_delete(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

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
                ],
            },
            "inventory": [
                {
                    "id": idx + 1,
                    "box": 1 if idx < 5 else 2,
                    "position": idx + 1,
                    "frozen_at": "2025-01-01",
                    "short_name": f"clone-{idx + 1}",
                }
                for idx in range(7)
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-remove-preview-summary", payload=payload)
        on_data_changed = MagicMock()

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            @staticmethod
            def exec():
                return 1

            @staticmethod
            def get_custom_fields():
                return []

            @staticmethod
            def get_display_key():
                return ""

            @staticmethod
            def get_color_key():
                return ""

        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        captured = []
        with self._capture_remove_preview_message(
            captured,
            click_role=QMessageBox.DestructiveRole,
        ), patch.object(dialog, "_confirm_phrase_dialog", return_value=True) as phrase_mock:
            dialog._open_custom_fields_editor()

        self.assertEqual(1, len(captured))
        preview = captured[0]
        self.assertIn("short_name", preview["text"])
        self.assertIn('Field "short_name": 7 record(s)', preview["informative"])
        self.assertIn("- ID 1 | Box 1 | Pos 1 | Value clone-1", preview["informative"])
        self.assertIn("- ID 5 | Box 1 | Pos 5 | Value clone-5", preview["informative"])
        self.assertIn("- 2 more record(s)", preview["informative"])
        self.assertIn("- ID 7 | Box 2 | Pos 7 | Value clone-7", preview["details"])
        phrase_mock.assert_called_once()
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        self.assertEqual([], saved.get("meta", {}).get("custom_fields") or [])
        for record in saved.get("inventory") or []:
            self.assertNotIn("short_name", record)

    def test_remove_data_preview_cancel_keeps_yaml_unchanged(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 1,
                    "box_numbers": [1],
                },
                "custom_fields": [
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                ],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "short_name": "clone-A",
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-remove-preview-cancel", payload=payload)
        on_data_changed = MagicMock()

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            @staticmethod
            def exec():
                return 1

            @staticmethod
            def get_custom_fields():
                return []

            @staticmethod
            def get_display_key():
                return ""

            @staticmethod
            def get_color_key():
                return ""

        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        captured = []
        with self._capture_remove_preview_message(
            captured,
            click_role=QMessageBox.RejectRole,
        ), patch.object(dialog, "_confirm_phrase_dialog", return_value=True) as phrase_mock:
            dialog._open_custom_fields_editor()

        self.assertEqual(1, len(captured))
        self.assertIn("short_name", captured[0]["text"])
        self.assertIn("clone-A", captured[0]["informative"])
        phrase_mock.assert_not_called()
        on_data_changed.assert_not_called()

        saved = load_yaml(yaml_path) or {}
        self.assertEqual(
            [{"key": "short_name", "label": "Short Name", "type": "str"}],
            saved.get("meta", {}).get("custom_fields") or [],
        )
        record = (saved.get("inventory") or [{}])[0]
        self.assertEqual("clone-A", record.get("short_name"))

    def test_remove_data_preview_skips_fields_without_meaningful_values(self):
        from app_gui.main import SettingsDialog
        from lib.yaml_ops import load_yaml

        previous_language = get_language()
        self.addCleanup(lambda: set_language(previous_language))
        self.assertTrue(set_language("en"))

        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 1,
                    "box_numbers": [1],
                },
                "custom_fields": [
                    {"key": "short_name", "label": "Short Name", "type": "str"},
                    {"key": "empty_tag", "label": "Empty Tag", "type": "str"},
                ],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2025-01-01",
                    "short_name": "clone-A",
                    "empty_tag": "   ",
                }
            ],
        }
        yaml_path = self.ensure_dataset_yaml("cf-remove-preview-skip-empty", payload=payload)
        on_data_changed = MagicMock()

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                _ = (args, kwargs)

            @staticmethod
            def exec():
                return 1

            @staticmethod
            def get_custom_fields():
                return []

            @staticmethod
            def get_display_key():
                return ""

            @staticmethod
            def get_color_key():
                return ""

        dialog = SettingsDialog(
            config={"yaml_path": yaml_path},
            on_data_changed=on_data_changed,
            custom_fields_dialog_cls=_FakeDialog,
        )

        captured = []
        with self._capture_remove_preview_message(
            captured,
            click_role=QMessageBox.DestructiveRole,
        ), patch.object(dialog, "_confirm_phrase_dialog", return_value=True):
            dialog._open_custom_fields_editor()

        self.assertEqual(1, len(captured))
        preview = captured[0]
        self.assertIn("short_name", preview["text"])
        self.assertNotIn("empty_tag", preview["text"])
        self.assertIn("clone-A", preview["informative"])
        self.assertNotIn("empty_tag", preview["informative"])
        on_data_changed.assert_called_once()

        saved = load_yaml(yaml_path) or {}
        self.assertEqual([], saved.get("meta", {}).get("custom_fields") or [])
        record = (saved.get("inventory") or [{}])[0]
        self.assertNotIn("short_name", record)
        self.assertNotIn("empty_tag", record)
