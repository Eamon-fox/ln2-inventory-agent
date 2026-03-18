"""Unit tests for rejecting legacy per-box field schemas."""

import unittest

from lib.custom_fields import (
    ensure_supported_field_model,
    get_effective_fields,
    get_field_options,
    get_required_field_keys,
    is_field_required,
    unsupported_box_fields_issue,
)


class TestUnsupportedBoxFieldsIssue(unittest.TestCase):
    """Tests for legacy ``meta.box_fields`` detection."""

    def test_returns_none_when_box_fields_absent(self):
        self.assertIsNone(unsupported_box_fields_issue({}))
        self.assertIsNone(unsupported_box_fields_issue({"custom_fields": []}))
        self.assertIsNone(unsupported_box_fields_issue(None))

    def test_detects_box_fields_even_when_empty(self):
        issue = unsupported_box_fields_issue({"box_fields": {}})
        self.assertIsNotNone(issue)
        self.assertEqual("unsupported_box_fields", issue.get("error_code"))
        self.assertIn("meta.box_fields", issue.get("message", ""))

    def test_captures_box_ids_in_details(self):
        issue = unsupported_box_fields_issue(
            {"box_fields": {"1": [{"key": "virus_titer", "type": "str"}], "3": []}}
        )
        self.assertIsNotNone(issue)
        self.assertEqual(["1", "3"], issue.get("details", {}).get("boxes"))
        self.assertEqual(2, issue.get("details", {}).get("box_count"))

    def test_ensure_supported_field_model_raises(self):
        with self.assertRaisesRegex(ValueError, "meta.box_fields"):
            ensure_supported_field_model({"box_fields": {"1": []}})


class TestGlobalOnlyFieldResolution(unittest.TestCase):
    """Field helpers should use global schema only on supported datasets."""

    def test_get_effective_fields_ignores_box_parameter(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "sample_type", "label": "Sample Type", "type": "str"},
            ]
        }
        global_keys = [f["key"] for f in get_effective_fields(meta)]
        box_keys = [f["key"] for f in get_effective_fields(meta, box=2)]
        self.assertEqual(global_keys, box_keys)
        self.assertIn("note", box_keys)

    def test_field_option_helpers_ignore_box_parameter(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "type": "str", "options": ["K562", "HeLa"], "required": True},
            ]
        }
        self.assertEqual(["K562", "HeLa"], get_field_options(meta, "cell_line"))
        self.assertEqual(["K562", "HeLa"], get_field_options(meta, "cell_line", box=9))
        self.assertTrue(is_field_required(meta, "cell_line", box=9))
        self.assertEqual({"cell_line"}, get_required_field_keys(meta, box=9))


if __name__ == "__main__":
    unittest.main()
