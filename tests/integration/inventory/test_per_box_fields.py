"""Integration tests for rejecting legacy per-box field schemas."""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    tool_add_entry,
    tool_edit_entry,
    tool_export_inventory_csv,
    tool_search_records,
)
from lib.validators import validate_inventory
from tests.managed_paths import ManagedPathTestCase


def _write_raw_yaml(path, payload):
    Path(path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _legacy_box_fields_payload():
    return {
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
        "inventory": [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "cell_line": "K562",
                "virus_titer": "MOI50",
            }
        ],
    }


class TestLegacyBoxFieldsRejected(ManagedPathTestCase):
    """Datasets with ``meta.box_fields`` should be blocked consistently."""

    def test_validate_inventory_rejects_legacy_box_fields(self):
        errors, warnings = validate_inventory(_legacy_box_fields_payload())
        self.assertTrue(errors)
        self.assertEqual([], warnings)
        self.assertIn("meta.box_fields", errors[0])

    def test_add_entry_rejects_legacy_box_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_fields_add_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_raw_yaml(yaml_path, _legacy_box_fields_payload())

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2],
                frozen_at="2026-03-01",
                fields={"cell_line": "HeLa"},
                source="test_box_fields",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("unsupported_box_fields", result.get("error_code"))
            self.assertIn("meta.box_fields", result.get("message", ""))

    def test_edit_entry_rejects_legacy_box_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_fields_edit_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_raw_yaml(yaml_path, _legacy_box_fields_payload())

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"cell_line": "HeLa"},
                source="test_box_fields",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("unsupported_box_fields", result.get("error_code"))

    def test_search_records_rejects_legacy_box_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_fields_search_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_raw_yaml(yaml_path, _legacy_box_fields_payload())

            result = tool_search_records(
                yaml_path=str(yaml_path),
                query="MOI50",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("unsupported_box_fields", result.get("error_code"))

    def test_export_inventory_csv_rejects_legacy_box_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_fields_export_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            output_path = Path(td) / "export.csv"
            _write_raw_yaml(yaml_path, _legacy_box_fields_payload())

            result = tool_export_inventory_csv(
                yaml_path=str(yaml_path),
                output_path=str(output_path),
            )

            self.assertFalse(result["ok"])
            self.assertEqual("unsupported_box_fields", result.get("error_code"))
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
