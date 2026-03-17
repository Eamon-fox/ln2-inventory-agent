"""
Module: test_migration_conflict_report
Layer: integration/migration
Covers: lib/import_validation_core._check_position_conflicts,
        lib/import_acceptance.validate_candidate_yaml

Verify that position conflicts within migration/import data are reported as
"Import data internal conflict" rather than the generic "Position conflict"
message, so users and agents do not confuse them with existing-inventory
conflicts.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.import_acceptance import validate_candidate_yaml
from lib.import_validation_core import validate_inventory_document


def _base_payload():
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
        "inventory": [],
    }


class TestMigrationConflictReport(unittest.TestCase):
    """Integration tests for conflict reporting in migration data."""

    def test_internal_conflict_message_via_validate_inventory_document(self):
        """Position conflicts within import data must say 'Import data internal conflict'."""
        payload = _base_payload()
        payload["inventory"] = [
            {"id": 1, "box": 1, "position": 34, "frozen_at": "2025-01-01", "cell_line": "K562"},
            {"id": 2, "box": 1, "position": 34, "frozen_at": "2025-01-02", "cell_line": "HeLa"},
        ]
        errors, _warnings = validate_inventory_document(payload)
        conflict_errors = [e for e in errors if "Position" in e and "34" in e]
        self.assertEqual(len(conflict_errors), 1)
        self.assertIn("Import data internal conflict", conflict_errors[0])
        self.assertNotIn("existing", conflict_errors[0].lower())

    def test_no_conflict_different_positions(self):
        payload = _base_payload()
        payload["inventory"] = [
            {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01", "cell_line": "K562"},
            {"id": 2, "box": 1, "position": 2, "frozen_at": "2025-01-01", "cell_line": "HeLa"},
        ]
        errors, _warnings = validate_inventory_document(payload)
        conflict_errors = [e for e in errors if "conflict" in e.lower()]
        self.assertEqual(conflict_errors, [])

    def test_multiple_internal_conflicts(self):
        """Multiple position conflicts each get the 'Import data internal' label."""
        payload = _base_payload()
        payload["inventory"] = [
            {"id": 1, "box": 1, "position": 10, "frozen_at": "2025-01-01", "cell_line": "A"},
            {"id": 2, "box": 1, "position": 10, "frozen_at": "2025-01-01", "cell_line": "B"},
            {"id": 3, "box": 2, "position": 20, "frozen_at": "2025-01-01", "cell_line": "C"},
            {"id": 4, "box": 2, "position": 20, "frozen_at": "2025-01-01", "cell_line": "D"},
        ]
        errors, _warnings = validate_inventory_document(payload)
        conflict_errors = [e for e in errors if "Import data internal conflict" in e]
        self.assertEqual(len(conflict_errors), 2)

    def test_candidate_yaml_conflict_message(self):
        """End-to-end: validate_candidate_yaml surfaces the improved message."""
        payload = _base_payload()
        payload["inventory"] = [
            {"id": 218, "box": 1, "position": 34, "frozen_at": "2025-01-01", "cell_line": "K562"},
            {"id": 219, "box": 1, "position": 34, "frozen_at": "2025-01-02", "cell_line": "HeLa"},
        ]
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            errors = (result.get("report") or {}).get("errors", [])
            conflict_errors = [e for e in errors if "Import data internal conflict" in e]
            self.assertGreater(len(conflict_errors), 0)
            # Must not contain misleading "existing" references
            for err in conflict_errors:
                self.assertNotIn("existing", err.lower())


if __name__ == "__main__":
    unittest.main()
