"""Unit tests for lib/custom_fields and integration tests for custom fields in tool_api."""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.custom_fields import CORE_FIELD_KEYS, coerce_value, parse_custom_fields
from lib.tool_api import (
    tool_add_entry,
    tool_edit_entry,
    tool_query_inventory,
    tool_search_records,
)
from lib.yaml_ops import load_yaml, write_yaml


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_tool_api.py)
# ---------------------------------------------------------------------------

def make_record(rec_id=1, box=1, positions=None, **extra):
    rec = {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }
    rec.update(extra)
    return rec


def make_data(records, custom_fields=None):
    meta = {"box_layout": {"rows": 9, "cols": 9}}
    if custom_fields is not None:
        meta["custom_fields"] = custom_fields
    return {"meta": meta, "inventory": records}


def write_raw_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


# ===========================================================================
# Unit tests: parse_custom_fields
# ===========================================================================

class TestParseCustomFields(unittest.TestCase):
    """Unit tests for parse_custom_fields()."""

    def test_empty_meta_returns_empty(self):
        self.assertEqual([], parse_custom_fields({}))
        self.assertEqual([], parse_custom_fields(None))
        self.assertEqual([], parse_custom_fields({"custom_fields": []}))

    def test_basic_field(self):
        meta = {"custom_fields": [
            {"key": "passage_number", "label": "Passage #", "type": "int"},
        ]}
        result = parse_custom_fields(meta)
        self.assertEqual(1, len(result))
        self.assertEqual("passage_number", result[0]["key"])
        self.assertEqual("Passage #", result[0]["label"])
        self.assertEqual("int", result[0]["type"])
        self.assertIsNone(result[0]["default"])

    def test_default_type_is_str(self):
        meta = {"custom_fields": [{"key": "color", "label": "Color"}]}
        result = parse_custom_fields(meta)
        self.assertEqual("str", result[0]["type"])

    def test_label_defaults_to_key(self):
        meta = {"custom_fields": [{"key": "color"}]}
        result = parse_custom_fields(meta)
        self.assertEqual("color", result[0]["label"])

    def test_default_value_preserved(self):
        meta = {"custom_fields": [
            {"key": "medium", "label": "Medium", "type": "str", "default": "10% DMSO"},
        ]}
        result = parse_custom_fields(meta)
        self.assertEqual("10% DMSO", result[0]["default"])

    def test_core_field_key_rejected(self):
        for core_key in ("id", "box", "positions", "frozen_at", "note"):
            meta = {"custom_fields": [{"key": core_key, "label": "X"}]}
            result = parse_custom_fields(meta)
            self.assertEqual([], result, f"core key {core_key!r} should be rejected")

    def test_invalid_key_rejected(self):
        # Not a valid Python identifier
        meta = {"custom_fields": [{"key": "123bad", "label": "X"}]}
        self.assertEqual([], parse_custom_fields(meta))

    def test_empty_key_rejected(self):
        meta = {"custom_fields": [{"key": "", "label": "X"}]}
        self.assertEqual([], parse_custom_fields(meta))
        meta2 = {"custom_fields": [{"label": "X"}]}
        self.assertEqual([], parse_custom_fields(meta2))

    def test_duplicate_key_rejected(self):
        meta = {"custom_fields": [
            {"key": "color", "label": "Color"},
            {"key": "color", "label": "Color2"},
        ]}
        result = parse_custom_fields(meta)
        self.assertEqual(1, len(result))
        self.assertEqual("Color", result[0]["label"])

    def test_non_dict_entry_skipped(self):
        meta = {"custom_fields": ["bad", {"key": "ok", "label": "OK"}]}
        result = parse_custom_fields(meta)
        self.assertEqual(1, len(result))
        self.assertEqual("ok", result[0]["key"])

    def test_non_list_custom_fields_returns_empty(self):
        meta = {"custom_fields": "not a list"}
        self.assertEqual([], parse_custom_fields(meta))

    def test_unknown_type_defaults_to_str(self):
        meta = {"custom_fields": [{"key": "x", "label": "X", "type": "boolean"}]}
        result = parse_custom_fields(meta)
        self.assertEqual("str", result[0]["type"])

    def test_multiple_valid_fields(self):
        meta = {"custom_fields": [
            {"key": "passage_number", "label": "Passage #", "type": "int"},
            {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
            {"key": "concentration", "label": "Conc.", "type": "float", "default": 1.0},
        ]}
        result = parse_custom_fields(meta)
        self.assertEqual(3, len(result))
        self.assertEqual(["passage_number", "virus_titer", "concentration"],
                         [f["key"] for f in result])

    def test_all_core_keys_in_blacklist(self):
        expected = {"id", "parent_cell_line", "short_name", "box", "positions",
                    "frozen_at", "plasmid_name", "plasmid_id", "note", "thaw_events"}
        self.assertEqual(expected, CORE_FIELD_KEYS)


# ===========================================================================
# Unit tests: coerce_value
# ===========================================================================

class TestCoerceValue(unittest.TestCase):
    """Unit tests for coerce_value()."""

    def test_none_returns_none(self):
        self.assertIsNone(coerce_value(None, "str"))
        self.assertIsNone(coerce_value(None, "int"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(coerce_value("", "str"))
        self.assertIsNone(coerce_value("  ", "int"))

    def test_str_passthrough(self):
        self.assertEqual("hello", coerce_value("hello", "str"))

    def test_int_coercion(self):
        self.assertEqual(42, coerce_value("42", "int"))
        self.assertEqual(0, coerce_value("0", "int"))

    def test_int_invalid_raises(self):
        with self.assertRaises(ValueError):
            coerce_value("abc", "int")

    def test_float_coercion(self):
        self.assertAlmostEqual(3.14, coerce_value("3.14", "float"))

    def test_float_invalid_raises(self):
        with self.assertRaises(ValueError):
            coerce_value("xyz", "float")

    def test_date_valid(self):
        self.assertEqual("2026-01-15", coerce_value("2026-01-15", "date"))

    def test_date_invalid_raises(self):
        with self.assertRaises(ValueError):
            coerce_value("not-a-date", "date")

    def test_strips_whitespace(self):
        self.assertEqual(5, coerce_value("  5  ", "int"))
        self.assertEqual("hi", coerce_value("  hi  ", "str"))


# ===========================================================================
# Integration tests: tool_add_entry with custom_data
# ===========================================================================

class TestToolAddEntryCustomData(unittest.TestCase):
    """Integration: custom_data flows through tool_add_entry into YAML."""

    def test_add_with_custom_data(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_add_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data(
                    [make_record(1, box=1, positions=[1])],
                    custom_fields=[
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                        {"key": "medium", "label": "Medium", "type": "str"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="K562_test",
                box=1,
                positions=[2],
                frozen_at="2026-02-10",
                custom_data={"passage_number": 5, "medium": "10% DMSO"},
                source="test_custom_fields",
            )

            self.assertTrue(result["ok"])
            data = load_yaml(str(yaml_path))
            new_rec = data["inventory"][-1]
            self.assertEqual(5, new_rec["passage_number"])
            self.assertEqual("10% DMSO", new_rec["medium"])

    def test_add_without_custom_data_no_extra_keys(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_add_none_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data(
                    [make_record(1, box=1, positions=[1])],
                    custom_fields=[
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="K562_plain",
                box=1,
                positions=[2],
                frozen_at="2026-02-10",
                source="test_custom_fields",
            )

            self.assertTrue(result["ok"])
            data = load_yaml(str(yaml_path))
            new_rec = data["inventory"][-1]
            self.assertNotIn("passage_number", new_rec)

    def test_custom_data_cannot_overwrite_core_fields(self):
        """custom_data keys that collide with core fields should be ignored."""
        with tempfile.TemporaryDirectory(prefix="ln2_cf_add_core_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="K562_core",
                box=1,
                positions=[2],
                frozen_at="2026-02-10",
                custom_data={"box": 999, "note": "hacked", "virus_titer": "high"},
                source="test_custom_fields",
            )

            self.assertTrue(result["ok"])
            data = load_yaml(str(yaml_path))
            new_rec = data["inventory"][-1]
            # Core fields should NOT be overwritten
            self.assertEqual(1, new_rec["box"])
            # Non-core custom key should be written
            self.assertEqual("high", new_rec["virus_titer"])


# ===========================================================================
# Integration tests: tool_edit_entry with custom fields
# ===========================================================================

class TestToolEditEntryCustomFields(unittest.TestCase):
    """Integration: custom fields are editable via tool_edit_entry."""

    def test_edit_custom_field(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_edit_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1], passage_number=3)
            write_yaml(
                make_data(
                    [rec],
                    custom_fields=[
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"passage_number": 10},
                source="test_custom_fields",
            )

            self.assertTrue(result["ok"])
            data = load_yaml(str(yaml_path))
            self.assertEqual(10, data["inventory"][0]["passage_number"])

    def test_edit_rejects_unknown_field(self):
        """Fields not in core set or custom_fields should be rejected."""
        with tempfile.TemporaryDirectory(prefix="ln2_cf_edit_bad_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data(
                    [make_record(1, box=1, positions=[1])],
                    custom_fields=[],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"nonexistent_field": "value"},
                source="test_custom_fields",
            )

            self.assertFalse(result["ok"])
            self.assertIn("error_code", result)

    def test_edit_custom_and_core_field_together(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_edit_mix_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1], passage_number=1)
            write_yaml(
                make_data(
                    [rec],
                    custom_fields=[
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"note": "updated note", "passage_number": 7},
                source="test_custom_fields",
            )

            self.assertTrue(result["ok"])
            data = load_yaml(str(yaml_path))
            self.assertEqual("updated note", data["inventory"][0]["note"])
            self.assertEqual(7, data["inventory"][0]["passage_number"])


# ===========================================================================
# Integration tests: search includes custom field values
# ===========================================================================

class TestSearchCustomFields(unittest.TestCase):
    """Integration: search_records finds matches in custom field values."""

    def test_search_finds_custom_field_value(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_search_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1], virus_titer="MOI50")
            write_yaml(
                make_data(
                    [rec],
                    custom_fields=[
                        {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_search_records(
                yaml_path=str(yaml_path),
                query="MOI50",
            )

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(result["result"]["records"]), 1)
            self.assertEqual(1, result["result"]["records"][0]["id"])

    def test_search_does_not_match_absent_custom_value(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_search_miss_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1])
            write_yaml(
                make_data(
                    [rec],
                    custom_fields=[
                        {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_search_records(
                yaml_path=str(yaml_path),
                query="MOI50",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(0, len(result["result"]["records"]))


# ===========================================================================
# Integration tests: _get_editable_fields
# ===========================================================================

class TestGetEditableFields(unittest.TestCase):
    """Integration: _get_editable_fields merges custom fields."""

    def test_no_custom_fields_returns_base_set(self):
        from lib.tool_api import _EDITABLE_FIELDS, _get_editable_fields

        with tempfile.TemporaryDirectory(prefix="ln2_cf_ef_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_raw_yaml(str(yaml_path), make_data([make_record()]))
            result = _get_editable_fields(str(yaml_path))
            self.assertEqual(_EDITABLE_FIELDS, result)

    def test_custom_fields_extend_editable_set(self):
        from lib.tool_api import _EDITABLE_FIELDS, _get_editable_fields

        with tempfile.TemporaryDirectory(prefix="ln2_cf_ef2_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_raw_yaml(
                str(yaml_path),
                make_data(
                    [make_record()],
                    custom_fields=[
                        {"key": "passage_number", "label": "P#", "type": "int"},
                        {"key": "medium", "label": "Medium"},
                    ],
                ),
            )
            result = _get_editable_fields(str(yaml_path))
            self.assertTrue(result.issuperset(_EDITABLE_FIELDS))
            self.assertIn("passage_number", result)
            self.assertIn("medium", result)

    def test_missing_yaml_returns_base_set(self):
        from lib.tool_api import _EDITABLE_FIELDS, _get_editable_fields

        result = _get_editable_fields("/nonexistent/path.yaml")
        self.assertEqual(_EDITABLE_FIELDS, result)


# ===========================================================================
# Integration tests: query includes custom field columns
# ===========================================================================

class TestQueryCustomFieldColumns(unittest.TestCase):
    """Integration: query results include custom field values."""

    def test_query_returns_custom_field_in_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_cf_query_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1], passage_number=5)
            write_yaml(
                make_data(
                    [rec],
                    custom_fields=[
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(result["ok"])
            records = result["result"]["records"]
            self.assertEqual(1, len(records))
            self.assertEqual(5, records[0]["passage_number"])


if __name__ == "__main__":
    unittest.main()
