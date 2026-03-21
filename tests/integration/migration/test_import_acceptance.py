"""
Module: test_import_acceptance
Layer: integration/migration
Covers: lib/import_acceptance.py

导入流程的验收测试场景，验证候选 YAML 文件的结构完整性、
自定义字段声明、盒布局配置以及最终导入操作的完整流程。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.import_acceptance import import_validated_yaml, validate_candidate_yaml


def _valid_payload():
    return {
        "meta": {
            "box_layout": {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_numbers": [1, 2, 3, 4, 5],
            },
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": False},
            ],
        },
        "inventory": [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "stored_at": "2025-01-01",
                "cell_line": "K562",
                "note": None,
                "storage_events": None,
            }
        ],
    }


class ImportAcceptanceTests(unittest.TestCase):
    def test_validate_candidate_yaml_ok(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(0, (result.get("report") or {}).get("error_count"))
            self.assertEqual("document", (result.get("report") or {}).get("mode"))

    def test_validate_candidate_yaml_keeps_import_specific_missing_file_message(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "missing.yaml"
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("file_not_found", result.get("error_code"))
            self.assertIn("Candidate YAML not found", str(result.get("message") or ""))

    def test_validate_candidate_yaml_rejects_extra_root_keys(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["unexpected"] = {"x": 1}
            candidate = Path(td) / "bad.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("Unsupported top-level key" in msg for msg in errors))

    def test_validate_candidate_yaml_rejects_structural_custom_field_key(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            # Use a truly structural key (e.g. "position") — note and cell_line are now valid custom fields
            payload["meta"]["custom_fields"] = [
                {"key": "position", "label": "Position", "type": "int", "required": False}
            ]
            candidate = Path(td) / "bad_structural_custom_field.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(
                any("conflicts with structural field" in msg and "position" in msg for msg in errors),
                errors,
            )

    def test_validate_candidate_yaml_rejects_unknown_color_key(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["color_key"] = "legacy_cell_line"
            candidate = Path(td) / "bad_color_key.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(
                any("meta.color_key" in msg and "invalid" in msg for msg in errors),
                errors,
            )

    def test_validate_candidate_yaml_rejects_color_key_with_trailing_space(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["color_key"] = "cell_line "
            candidate = Path(td) / "bad_color_key_whitespace.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(
                any("meta.color_key" in msg and "whitespace" in msg for msg in errors),
                errors,
            )

    def test_validate_candidate_yaml_rejects_unknown_display_key(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["display_key"] = "legacy_alias"
            candidate = Path(td) / "bad_display_key.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(
                any("meta.display_key" in msg and "invalid" in msg for msg in errors),
                errors,
            )

    def test_validate_candidate_yaml_accepts_custom_field_color_key(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["custom_fields"] = [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": False},
                {"key": "short_name", "label": "Short Name", "type": "str", "required": False}
            ]
            payload["meta"]["color_key"] = "short_name"
            payload["inventory"][0]["short_name"] = "K562-A1"
            candidate = Path(td) / "ok_color_key_custom_field.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertTrue(result.get("ok"), result)

    def test_validate_candidate_yaml_rejects_undeclared_record_fields(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["inventory"][0]["short_name"] = "K562-A1"
            payload["inventory"][0]["plasmid_name"] = "PB-demo"
            candidate = Path(td) / "bad_undeclared_record_fields.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("Unsupported inventory field(s):" in msg for msg in errors), errors)
            self.assertTrue(any("short_name" in msg for msg in errors), errors)
            self.assertTrue(any("plasmid_name" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_accepts_declared_record_fields(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["custom_fields"] = [
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": False},
                {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
                {"key": "plasmid_name", "label": "Plasmid Name", "type": "str", "required": False},
                {"key": "plasmid_id", "label": "Plasmid ID", "type": "str", "required": False},
            ]
            payload["inventory"][0]["short_name"] = "K562-A1"
            payload["inventory"][0]["plasmid_name"] = "PB-demo"
            payload["inventory"][0]["plasmid_id"] = "p-demo-1"
            candidate = Path(td) / "ok_declared_record_fields.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertTrue(result.get("ok"), result)

    def test_validate_candidate_yaml_rejects_missing_box_count(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"].pop("box_count", None)
            candidate = Path(td) / "bad_missing_box_count.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("box_count is required" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_rejects_missing_box_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"].pop("box_numbers", None)
            candidate = Path(td) / "bad_missing_box_numbers.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("box_numbers is required" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_rejects_box_count_box_numbers_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"]["box_count"] = 4
            payload["meta"]["box_layout"]["box_numbers"] = [1, 2, 3]
            candidate = Path(td) / "bad_box_layout_mismatch.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("box_count=4" in msg and "box_numbers has 3" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_accepts_valid_box_tags(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"]["box_tags"] = {
                "1": "Rack A",
                "3": "Shelf B",
            }
            candidate = Path(td) / "valid_box_tags.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertTrue(result.get("ok"), result)

    def test_validate_candidate_yaml_rejects_invalid_box_tags(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"]["box_tags"] = {
                "9": "Out of layout",
                "1": "Line 1\nLine 2",
            }
            candidate = Path(td) / "invalid_box_tags.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("box_tags key '9'" in msg for msg in errors), errors)
            self.assertTrue(any("box_tags[1] must be a single-line" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_rejects_inventory_using_undeclared_boxes(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"]["box_layout"]["box_count"] = 2
            payload["meta"]["box_layout"]["box_numbers"] = [1, 2]
            payload["inventory"][0]["box"] = 3
            candidate = Path(td) / "bad_undeclared_box.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("Inventory uses undeclared boxes" in msg for msg in errors), errors)

    def test_import_validated_yaml_writes_target(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            target = Path(td) / "imported.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = import_validated_yaml(str(candidate), str(target))
            self.assertTrue(result.get("ok"), result)
            self.assertTrue(target.exists())

    def test_import_validated_yaml_honors_overwrite_flag(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            target = Path(td) / "existing.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            target.write_text("meta: {}\ninventory: []\n", encoding="utf-8")

            blocked = import_validated_yaml(str(candidate), str(target))
            self.assertFalse(blocked.get("ok"))
            self.assertEqual("target_exists", blocked.get("error_code"))

            allowed = import_validated_yaml(str(candidate), str(target), overwrite=True)
            self.assertTrue(allowed.get("ok"), allowed)

    def test_import_validated_yaml_rejects_undeclared_record_fields(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["inventory"][0]["short_name"] = "K562-A1"

            candidate = Path(td) / "candidate_with_undeclared.yaml"
            target = Path(td) / "imported.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = import_validated_yaml(str(candidate), str(target))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            self.assertFalse(target.exists())

    def test_validate_candidate_yaml_does_not_assume_missing_cell_line_field(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"].pop("custom_fields", None)
            payload["inventory"][0].pop("cell_line", None)
            candidate = Path(td) / "warn.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate), fail_on_warnings=True)
            self.assertTrue(result.get("ok"), result)
            report = result.get("report") or {}
            self.assertEqual(0, (report.get("warning_count") or 0))

    def test_validate_candidate_yaml_rejects_missing_cell_line_when_legacy_required_flag_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"].pop("custom_fields", None)
            payload["meta"]["cell_line_required"] = True
            payload["inventory"][0].pop("cell_line", None)
            candidate = Path(td) / "missing_required_cell_line.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = list((result.get("report") or {}).get("errors") or [])
            self.assertTrue(any("missing required field 'cell_line'" in msg for msg in errors), errors)

    def test_validate_candidate_yaml_blocks_non_option_cell_line_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"].pop("custom_fields", None)
            payload["meta"]["cell_line_options"] = ["K562", "HeLa"]
            payload["inventory"][0]["cell_line"] = "H1299"
            candidate = Path(td) / "warn_non_option.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate), fail_on_warnings=True)
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            report = result.get("report") or {}
            warnings = list(report.get("warnings") or [])
            self.assertTrue(any("not in configured options" in msg for msg in warnings), report)

    def test_validate_candidate_yaml_allows_non_option_cell_line_in_non_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["meta"].pop("custom_fields", None)
            payload["meta"]["cell_line_options"] = ["K562", "HeLa"]
            payload["inventory"][0]["cell_line"] = "H1299"
            candidate = Path(td) / "warn_non_option_non_strict.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate), fail_on_warnings=False)
            self.assertTrue(result.get("ok"), result)
            report = result.get("report") or {}
            warnings = list(report.get("warnings") or [])
            self.assertTrue(any("not in configured options" in msg for msg in warnings), report)


class SkipRecordValidationTests(unittest.TestCase):
    """Tests for validate_inventory_document(skip_record_validation=True)."""

    def test_skip_record_validation_ignores_option_mismatch(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str",
                     "options": ["HeLa"]},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        errors, warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_skip_record_validation_ignores_missing_required_custom_field(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "passage", "label": "Passage", "type": "int",
                     "required": True},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        errors, warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertEqual(errors, [])

    def test_skip_record_validation_ignores_duplicate_ids(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
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
                {"id": 1, "box": 1, "position": 2, "frozen_at": "2025-01-01",
                 "cell_line": "HeLa"},
            ],
        }
        errors, _warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertEqual(errors, [])

    def test_skip_record_validation_still_catches_meta_errors(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [],
                "color_key": "nonexistent ",
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        errors, _warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("color_key" in e for e in errors))

    def test_skip_record_validation_still_catches_undeclared_fields(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562", "totally_unknown": "x"},
            ],
        }
        errors, _warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("totally_unknown" in e for e in errors))

    def test_skip_record_validation_still_catches_invalid_custom_field_schema(self):
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "id", "type": "str"},
                ],
            },
            "inventory": [],
        }
        errors, _warnings = validate_inventory_document(
            data, skip_record_validation=True,
        )
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("structural" in e.lower() for e in errors))

    def test_full_validation_still_catches_option_mismatch_as_warning(self):
        """Verify the default (skip_record_validation=False) still works."""
        from lib.import_validation_core import validate_inventory_document

        data = {
            "meta": {
                "box_layout": {
                    "rows": 9, "cols": 9,
                    "box_count": 2, "box_numbers": [1, 2],
                },
                "custom_fields": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str",
                     "options": ["HeLa"]},
                ],
            },
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01",
                 "cell_line": "K562"},
            ],
        }
        errors, warnings = validate_inventory_document(data)
        self.assertEqual(errors, [])
        self.assertTrue(len(warnings) > 0)
        self.assertTrue(any("not in configured options" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
