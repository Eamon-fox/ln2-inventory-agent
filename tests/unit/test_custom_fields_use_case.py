"""Unit tests for custom-fields application use case orchestration."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import CustomFieldsEditorState, CustomFieldsUseCase
from lib.custom_fields import get_effective_fields
from lib.custom_fields_update_service import prepare_custom_fields_update


class CustomFieldsUseCaseTests(unittest.TestCase):
    def test_load_editor_state_normalizes_document_and_collects_effective_fields(self):
        loaded = {
            "meta": {
                "custom_fields": [
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
                    "short_name": "clone-a",
                }
            ],
            "extra": {"keep": True},
        }
        use_case = CustomFieldsUseCase()

        with patch(
            "app_gui.application.custom_fields_use_case.load_yaml",
            return_value=loaded,
        ) as load_mock:
            result = use_case.load_editor_state(yaml_path="D:/inventories/test.yaml")

        load_mock.assert_called_once_with("D:/inventories/test.yaml")
        self.assertIsNone(result.unsupported_issue)
        self.assertEqual(loaded, result.state.source_data)
        self.assertEqual("short_name", result.state.current_display_key)
        self.assertEqual("short_name", result.state.current_color_key)
        keys = [field.get("key") for field in result.state.existing_fields]
        self.assertEqual(["note", "short_name"], keys)

    def test_load_editor_state_surfaces_unsupported_box_fields(self):
        loaded = {
            "meta": {
                "box_fields": {"1": [{"key": "virus_titer", "label": "Virus Titer", "type": "str"}]},
            },
            "inventory": [],
        }
        use_case = CustomFieldsUseCase()

        with patch(
            "app_gui.application.custom_fields_use_case.load_yaml",
            return_value=loaded,
        ):
            result = use_case.load_editor_state(yaml_path="D:/inventories/test.yaml")

        self.assertEqual("unsupported_box_fields", result.unsupported_issue.get("error_code"))
        self.assertEqual([], result.state.existing_fields)

    def test_commit_update_validates_and_persists_cleaned_inventory(self):
        meta = {
            "box_layout": {"rows": 9, "cols": 9, "box_count": 1, "box_numbers": [1]},
            "custom_fields": [
                {"key": "short_name", "label": "Short Name", "type": "str"},
            ],
        }
        inventory = [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "short_name": "clone-a",
            }
        ]
        use_case = CustomFieldsUseCase()
        state = CustomFieldsEditorState(
            source_data={"meta": meta, "inventory": inventory, "extra": {"keep": True}},
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta, inventory=inventory),
            current_display_key="short_name",
            current_color_key="short_name",
        )
        draft = prepare_custom_fields_update(
            meta=state.meta,
            inventory=state.inventory,
            existing_fields=state.existing_fields,
            new_fields=[],
            current_display_key=state.current_display_key,
            current_color_key=state.current_color_key,
            requested_display_key="",
            requested_color_key="",
        )

        with patch(
            "app_gui.application.custom_fields_use_case.persist_custom_fields_update",
            return_value={"ok": True, "backup_path": "D:/backups/test.bak"},
        ) as persist_mock:
            result = use_case.commit_update(
                yaml_path="D:/inventories/test.yaml",
                state=state,
                draft=draft,
                remove_removed_field_data=True,
            )

        self.assertTrue(result.ok)
        self.assertEqual(1, result.removed_records_count)
        persist_mock.assert_called_once()
        pending_data = persist_mock.call_args.kwargs["pending_data"]
        self.assertEqual({"keep": True}, pending_data.get("extra"))
        self.assertEqual([], pending_data["meta"].get("custom_fields"))
        self.assertNotIn("short_name", pending_data["inventory"][0])

    def test_commit_update_returns_validation_errors_without_persisting(self):
        use_case = CustomFieldsUseCase()
        state = CustomFieldsEditorState(
            source_data={"meta": {}, "inventory": []},
            meta={},
            inventory=[],
            existing_fields=[],
            current_display_key="",
            current_color_key="",
        )
        draft = prepare_custom_fields_update(
            meta={},
            inventory=[],
            existing_fields=[],
            new_fields=[{"key": "box", "label": "Box", "type": "str"}],
            current_display_key="",
            current_color_key="",
            requested_display_key="box",
            requested_color_key="",
        )

        with patch(
            "app_gui.application.custom_fields_use_case.persist_custom_fields_update",
        ) as persist_mock:
            result = use_case.commit_update(
                yaml_path="D:/inventories/test.yaml",
                state=state,
                draft=draft,
                remove_removed_field_data=False,
            )

        self.assertFalse(result.ok)
        self.assertEqual("validation_failed", result.error_code)
        self.assertTrue(result.meta_errors)
        persist_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
