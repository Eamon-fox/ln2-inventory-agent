"""
Module: test_validators_conflict
Layer: unit
Covers: lib/validators.py

测试位置冲突检测（含 batch-internal / cross-source 区分）。
"""

import sys
import unittest
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validators import check_position_conflicts


class TestCheckPositionConflicts(unittest.TestCase):
    """Test check_position_conflicts with batch-internal vs cross-source."""

    def test_no_conflicts(self):
        records = [
            {"id": 1, "box": 1, "position": 1},
            {"id": 2, "box": 1, "position": 2},
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(errors, [])

    def test_generic_conflict_without_existing_count(self):
        """Without existing_count, uses the original generic message."""
        records = [
            {"id": 1, "box": 1, "position": 1},
            {"id": 2, "box": 1, "position": 1},
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(len(errors), 1)
        self.assertIn("Position conflict:", errors[0])
        self.assertIn("multiple records", errors[0])

    def test_batch_internal_conflict(self):
        """Both conflicting records are in the batch (idx >= existing_count)."""
        existing = [
            {"id": 1, "box": 1, "position": 10},
        ]
        batch = [
            {"id": 100, "box": 2, "position": 5},
            {"id": 101, "box": 2, "position": 5},
        ]
        errors = check_position_conflicts(existing + batch, existing_count=len(existing))
        self.assertEqual(len(errors), 1)
        self.assertIn("batch-internal", errors[0])
        self.assertIn("id=100", errors[0])
        self.assertIn("id=101", errors[0])
        # Must NOT say "existing"
        self.assertNotIn("existing", errors[0])

    def test_cross_source_conflict(self):
        """One existing record and one batch record at the same slot."""
        existing = [
            {"id": 1, "box": 1, "position": 5},
        ]
        batch = [
            {"id": 200, "box": 1, "position": 5},
        ]
        errors = check_position_conflicts(existing + batch, existing_count=len(existing))
        self.assertEqual(len(errors), 1)
        self.assertIn("cross-source", errors[0])
        self.assertIn("existing", errors[0])
        self.assertIn("batch", errors[0])

    def test_existing_only_conflict(self):
        """Both conflicting records are from existing inventory."""
        existing = [
            {"id": 1, "box": 1, "position": 5},
            {"id": 2, "box": 1, "position": 5},
        ]
        batch = [
            {"id": 100, "box": 2, "position": 1},
        ]
        errors = check_position_conflicts(existing + batch, existing_count=len(existing))
        self.assertEqual(len(errors), 1)
        self.assertIn("existing records", errors[0])
        self.assertNotIn("batch", errors[0])

    def test_skips_none_position(self):
        records = [
            {"id": 1, "box": 1, "position": None},
            {"id": 2, "box": 1, "position": None},
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(errors, [])

    def test_multiple_conflict_types(self):
        """Mixed batch-internal and cross-source conflicts in one call."""
        existing = [
            {"id": 1, "box": 1, "position": 5},
        ]
        batch = [
            {"id": 100, "box": 1, "position": 5},   # cross-source with id=1
            {"id": 101, "box": 2, "position": 10},
            {"id": 102, "box": 2, "position": 10},   # batch-internal with id=101
        ]
        errors = check_position_conflicts(existing + batch, existing_count=len(existing))
        self.assertEqual(len(errors), 2)
        cross = [e for e in errors if "cross-source" in e]
        internal = [e for e in errors if "batch-internal" in e]
        self.assertEqual(len(cross), 1)
        self.assertEqual(len(internal), 1)


if __name__ == "__main__":
    unittest.main()
