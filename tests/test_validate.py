"""Focused tests for depletion-history behavior in validators."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validators import has_depletion_history, validate_record  # noqa: E402


def make_record(**overrides):
    rec = {
        "id": 1,
        "box": 1,
        "position": 1,
        "frozen_at": "2025-01-01",
        "cell_line": "NCCIT",
    }
    rec.update(overrides)
    return rec


class ValidatePositionsTests(unittest.TestCase):
    def test_empty_position_without_history_is_error(self):
        rec = make_record(position=None)
        errors, warnings = validate_record(rec, 0)
        self.assertEqual([], warnings)
        self.assertTrue(any("position" in err for err in errors))

    def test_empty_position_with_takeout_event_is_allowed(self):
        rec = make_record(
            position=None,
            thaw_events=[{"date": "2025-01-02", "action": "takeout", "positions": [1]}],
        )
        errors, warnings = validate_record(rec, 0)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_empty_position_with_unknown_action_still_errors(self):
        rec = make_record(
            position=None,
            thaw_events=[{"date": "2025-01-02", "action": "unknown", "positions": [1]}],
        )
        errors, warnings = validate_record(rec, 0)
        self.assertEqual([], warnings)
        self.assertTrue(any("position" in err for err in errors))
        self.assertTrue(any("action" in err.lower() for err in errors))

    def test_has_depletion_history_takeout_only(self):
        for action in ("takeout", "取出"):
            with self.subTest(action=action):
                rec = make_record(
                    position=None,
                    thaw_events=[{"date": "2025-01-02", "action": action, "positions": [1]}],
                )
                self.assertTrue(has_depletion_history(rec))

        for action in ("thaw", "discard", "复苏", "扔掉", "move"):
            with self.subTest(action=action):
                rec = make_record(
                    position=1,
                    thaw_events=[{"date": "2025-01-02", "action": action, "positions": [1]}],
                )
                self.assertFalse(has_depletion_history(rec))


if __name__ == "__main__":
    unittest.main()
