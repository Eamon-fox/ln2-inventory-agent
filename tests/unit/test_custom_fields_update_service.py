"""Unit tests for custom-fields settings update domain service."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.custom_fields import get_effective_fields
from lib.custom_fields_update_service import (
    REMOVED_FIELD_PREVIEW_SAMPLE_LIMIT,
    drop_removed_fields_from_inventory,
    prepare_custom_fields_update,
    validate_custom_fields_update_draft,
)


class CustomFieldsUpdateServiceTests(unittest.TestCase):
    def test_prepare_detects_conflicting_rename(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "short_name", "label": "Short Name", "type": "str"},
                {"key": "alias", "label": "Alias", "type": "str"},
            ]
        }
        inventory = [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "cell_line": "K562",
                "short_name": "clone-a",
                "alias": "existing-alias",
            }
        ]
        draft = prepare_custom_fields_update(
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta),
            new_fields=[
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "alias", "label": "Alias", "type": "str", "_original_key": "short_name"},
            ],
            current_display_key="short_name",
            current_color_key="short_name",
            requested_display_key="",
            requested_color_key="",
        )

        self.assertEqual(1, len(draft.rename_conflicts))
        rec = draft.pending_inventory[0]
        self.assertEqual("clone-a", rec.get("short_name"))
        self.assertEqual("existing-alias", rec.get("alias"))

    def test_prepare_selector_follows_rename_and_cleans_cell_line_legacy_meta(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "old_tag", "label": "Old Tag", "type": "str"},
            ],
            "display_key": "old_tag",
            "color_key": "old_tag",
            "cell_line_required": True,
            "cell_line_options": ["K562", "HeLa"],
        }
        inventory = [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "cell_line": "K562",
                "old_tag": "tag-a",
            }
        ]
        draft = prepare_custom_fields_update(
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta),
            new_fields=[
                {"key": "new_tag", "label": "New Tag", "type": "str", "_original_key": "old_tag"},
            ],
            current_display_key="old_tag",
            current_color_key="old_tag",
            requested_display_key="",
            requested_color_key="",
        )

        self.assertEqual("new_tag", draft.pending_meta.get("display_key"))
        self.assertEqual("new_tag", draft.pending_meta.get("color_key"))
        self.assertNotIn("cell_line_required", draft.pending_meta)
        self.assertNotIn("cell_line_options", draft.pending_meta)
        rec = draft.pending_inventory[0]
        self.assertEqual("tag-a", rec.get("new_tag"))
        self.assertNotIn("old_tag", rec)

    def test_drop_removed_fields_from_inventory_returns_touched_count(self):
        inventory = [
            {"id": 1, "x": "a", "y": 1},
            {"id": 2, "x": None, "z": 2},
            "non-dict",
        ]
        touched = drop_removed_fields_from_inventory(inventory, {"x", "z"})
        self.assertEqual(2, touched)
        self.assertNotIn("x", inventory[0])
        self.assertNotIn("x", inventory[1])
        self.assertNotIn("z", inventory[1])

    def test_validate_draft_uses_meta_only_rules(self):
        meta = {
            "box_layout": {"rows": 9, "cols": 9, "box_count": 2, "box_numbers": [1, 2]},
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "passage", "label": "Passage", "type": "int", "required": True},
            ],
        }
        inventory = [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "cell_line": "K562",
            }
        ]
        draft = prepare_custom_fields_update(
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta),
            new_fields=meta["custom_fields"],
            current_display_key="",
            current_color_key="",
            requested_display_key="",
            requested_color_key="",
        )
        errors, _warnings = validate_custom_fields_update_draft(draft)
        self.assertEqual([], errors)

    def test_prepare_collects_removed_field_previews_and_ignores_blank_values(self):
        meta = {
            "custom_fields": [
                {"key": "short_name", "label": "Short Name", "type": "str"},
                {"key": "empty_tag", "label": "Empty Tag", "type": "str"},
            ]
        }
        inventory = [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "short_name": "clone-A",
                "empty_tag": "   ",
            },
            {
                "id": 2,
                "box": 2,
                "position": 5,
                "frozen_at": "2025-01-02",
                "short_name": "clone-B",
                "empty_tag": None,
            },
        ]
        draft = prepare_custom_fields_update(
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta),
            new_fields=[],
            current_display_key="",
            current_color_key="",
            requested_display_key="",
            requested_color_key="",
        )

        self.assertEqual({"short_name"}, draft.removed_keys_with_data)
        self.assertEqual(["short_name"], [preview.field_key for preview in draft.removed_field_previews])
        preview = draft.removed_field_previews[0]
        self.assertEqual(2, preview.affected_count)
        self.assertEqual(["clone-A", "clone-B"], [entry.value for entry in preview.entries])
        self.assertEqual(0, preview.hidden_count)

    def test_prepare_limits_removed_field_preview_samples(self):
        meta = {
            "custom_fields": [
                {"key": "short_name", "label": "Short Name", "type": "str"},
            ]
        }
        inventory = [
            {
                "id": idx + 1,
                "box": 1,
                "position": idx + 1,
                "frozen_at": "2025-01-01",
                "short_name": f"clone-{idx + 1}",
            }
            for idx in range(REMOVED_FIELD_PREVIEW_SAMPLE_LIMIT + 2)
        ]
        draft = prepare_custom_fields_update(
            meta=meta,
            inventory=inventory,
            existing_fields=get_effective_fields(meta),
            new_fields=[],
            current_display_key="",
            current_color_key="",
            requested_display_key="",
            requested_color_key="",
        )

        preview = draft.removed_field_previews[0]
        self.assertEqual(REMOVED_FIELD_PREVIEW_SAMPLE_LIMIT + 2, preview.affected_count)
        self.assertEqual(REMOVED_FIELD_PREVIEW_SAMPLE_LIMIT, len(preview.samples))
        self.assertEqual(2, preview.hidden_count)
        self.assertEqual("clone-1", preview.samples[0].value)
        self.assertEqual(
            f"clone-{REMOVED_FIELD_PREVIEW_SAMPLE_LIMIT}",
            preview.samples[-1].value,
        )


if __name__ == "__main__":
    unittest.main()
