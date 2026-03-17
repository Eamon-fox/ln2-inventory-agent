"""Unit tests for per-box custom field schema resolution."""

import unittest

from lib.custom_fields import (
    get_effective_fields,
    get_field_options,
    get_required_field_keys,
    is_field_required,
    _get_box_fields_raw,
    parse_custom_fields,
)


class TestGetBoxFieldsRaw(unittest.TestCase):
    """Tests for _get_box_fields_raw helper."""

    def test_returns_none_when_no_box_fields(self):
        self.assertIsNone(_get_box_fields_raw({}, 1))
        self.assertIsNone(_get_box_fields_raw({"custom_fields": []}, 1))

    def test_returns_none_when_box_is_none(self):
        meta = {"box_fields": {"1": [{"key": "x"}]}}
        self.assertIsNone(_get_box_fields_raw(meta, None))

    def test_returns_none_when_box_not_in_box_fields(self):
        meta = {"box_fields": {"1": [{"key": "x"}]}}
        self.assertIsNone(_get_box_fields_raw(meta, 2))

    def test_returns_list_for_matching_box(self):
        field_list = [{"key": "sample_type", "label": "Type"}]
        meta = {"box_fields": {"1": field_list}}
        self.assertEqual(field_list, _get_box_fields_raw(meta, 1))

    def test_box_key_is_string(self):
        meta = {"box_fields": {"3": [{"key": "x"}]}}
        result = _get_box_fields_raw(meta, 3)
        self.assertIsNotNone(result)

    def test_non_dict_meta_returns_none(self):
        self.assertIsNone(_get_box_fields_raw(None, 1))
        self.assertIsNone(_get_box_fields_raw("bad", 1))

    def test_non_dict_box_fields_returns_none(self):
        self.assertIsNone(_get_box_fields_raw({"box_fields": "bad"}, 1))

    def test_non_list_value_returns_none(self):
        meta = {"box_fields": {"1": "not a list"}}
        self.assertIsNone(_get_box_fields_raw(meta, 1))


class TestGetEffectiveFieldsPerBox(unittest.TestCase):
    """Tests for get_effective_fields with per-box overrides."""

    def _meta_with_global_and_box(self):
        return {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "passage_number", "label": "Passage", "type": "int"},
            ],
            "box_fields": {
                "2": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                ],
            },
        }

    def test_no_box_returns_global_fields(self):
        meta = self._meta_with_global_and_box()
        fields = get_effective_fields(meta)
        keys = [f["key"] for f in fields]
        self.assertIn("cell_line", keys)
        self.assertIn("passage_number", keys)
        self.assertIn("note", keys)
        self.assertNotIn("virus_titer", keys)

    def test_box_without_override_returns_global(self):
        meta = self._meta_with_global_and_box()
        fields = get_effective_fields(meta, box=1)
        keys = [f["key"] for f in fields]
        self.assertIn("passage_number", keys)
        self.assertNotIn("virus_titer", keys)

    def test_box_with_override_returns_box_fields(self):
        meta = self._meta_with_global_and_box()
        fields = get_effective_fields(meta, box=2)
        keys = [f["key"] for f in fields]
        self.assertIn("cell_line", keys)
        self.assertIn("virus_titer", keys)
        self.assertIn("note", keys)  # always auto-injected
        self.assertNotIn("passage_number", keys)

    def test_box_override_note_always_present(self):
        meta = {
            "custom_fields": [{"key": "cell_line", "type": "str"}],
            "box_fields": {
                "1": [{"key": "sample_type", "label": "Sample", "type": "str"}],
            },
        }
        fields = get_effective_fields(meta, box=1)
        keys = [f["key"] for f in fields]
        self.assertIn("note", keys)
        self.assertIn("sample_type", keys)
        self.assertNotIn("cell_line", keys)


class TestFieldOptionsPerBox(unittest.TestCase):
    """Tests for get_field_options / is_field_required with box overrides."""

    def test_get_field_options_uses_box_override(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "type": "str", "options": ["K562", "HeLa"]},
            ],
            "box_fields": {
                "2": [
                    {"key": "cell_line", "type": "str", "options": ["A549", "MCF7"]},
                ],
            },
        }
        self.assertEqual(["K562", "HeLa"], get_field_options(meta, "cell_line"))
        self.assertEqual(["K562", "HeLa"], get_field_options(meta, "cell_line", box=1))
        self.assertEqual(["A549", "MCF7"], get_field_options(meta, "cell_line", box=2))

    def test_get_required_field_keys_per_box(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "type": "str", "required": True},
            ],
            "box_fields": {
                "3": [
                    {"key": "cell_line", "type": "str", "required": False},
                    {"key": "virus_titer", "type": "str", "required": True},
                ],
            },
        }
        global_required = get_required_field_keys(meta)
        self.assertIn("cell_line", global_required)

        box3_required = get_required_field_keys(meta, box=3)
        self.assertNotIn("cell_line", box3_required)
        self.assertIn("virus_titer", box3_required)

    def test_is_field_required_per_box(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "type": "str", "required": True},
            ],
            "box_fields": {
                "2": [
                    {"key": "cell_line", "type": "str", "required": False},
                ],
            },
        }
        self.assertTrue(is_field_required(meta, "cell_line"))
        self.assertTrue(is_field_required(meta, "cell_line", box=1))
        self.assertFalse(is_field_required(meta, "cell_line", box=2))


class TestParseCustomFieldsWithFieldList(unittest.TestCase):
    """Tests for parse_custom_fields with explicit field_list parameter."""

    def test_field_list_overrides_meta(self):
        meta = {
            "custom_fields": [{"key": "cell_line", "type": "str"}],
        }
        override = [{"key": "virus_titer", "label": "Titer", "type": "str"}]
        result = parse_custom_fields(meta, field_list=override)
        self.assertEqual(1, len(result))
        self.assertEqual("virus_titer", result[0]["key"])

    def test_empty_field_list_returns_empty(self):
        meta = {
            "custom_fields": [{"key": "cell_line", "type": "str"}],
        }
        result = parse_custom_fields(meta, field_list=[])
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
