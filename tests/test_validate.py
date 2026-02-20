import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validators import has_depletion_history, validate_record


def make_record(**overrides):
    rec = {
        "id": 1,
        "parent_cell_line": "NCCIT",
        "short_name": "example",
        "box": 1,
        "position": 1,
        "frozen_at": "2025-01-01",
    }
    rec.update(overrides)
    return rec


class ValidatePositionsTests(unittest.TestCase):
    def test_empty_position_without_history_is_error(self):
        rec = make_record(position=None)
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], warnings)
        self.assertEqual(1, len(errors))
        self.assertIn("position", errors[0])

    def test_empty_position_with_thaw_event_is_allowed(self):
        rec = make_record(
            position=None,
            thaw_events=[{"date": "2025-01-02", "action": "thaw", "positions": [1]}],
        )
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_empty_position_with_legacy_thaw_log_is_error(self):
        rec = make_record(position=None, thaw_log="legacy free-text log")
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], warnings)
        self.assertGreaterEqual(len(errors), 1)
        self.assertTrue(any("position" in err for err in errors))

    def test_empty_position_with_unknown_action_still_errors(self):
        rec = make_record(
            position=None,
            thaw_events=[{"date": "2025-01-02", "action": "unknown", "positions": [1]}],
        )
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], warnings)
        self.assertGreaterEqual(len(errors), 1)
        self.assertTrue(any("position" in err for err in errors))
        self.assertTrue(any("action" in err for err in errors))

    def test_position_must_be_int(self):
        rec = make_record(position="abc")
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], warnings)
        self.assertEqual(1, len(errors))
        self.assertIn("position", errors[0])

    def test_has_depletion_history_detects_canonical_actions(self):
        for action in ("takeout", "thaw", "discard", "取出", "复苏", "扔掉"):
            with self.subTest(action=action):
                rec = make_record(
                    position=None,
                    thaw_events=[{"date": "2025-01-02", "action": action, "positions": [1]}],
                )
                self.assertTrue(has_depletion_history(rec))

    def test_move_action_is_valid_but_not_depletion(self):
        rec = make_record(
            position=1,
            thaw_events=[{"date": "2025-01-02", "action": "move", "positions": [1]}],
        )
        errors, warnings = validate_record(rec, 0)

        self.assertEqual([], warnings)
        self.assertEqual([], errors)
        self.assertFalse(has_depletion_history(rec))


if __name__ == "__main__":
    unittest.main()
