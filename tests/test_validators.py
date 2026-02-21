"""Tests for lib.validators."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validators import (  # noqa: E402
    check_duplicate_ids,
    check_position_conflicts,
    format_chinese_date,
    format_validation_errors,
    normalize_date_arg,
    parse_date,
    parse_positions,
    validate_action,
    validate_box,
    validate_date,
    validate_inventory,
    validate_position,
    validate_record,
)


class DateTests(unittest.TestCase):
    def test_validate_date(self):
        self.assertTrue(validate_date("2026-02-10"))
        self.assertFalse(validate_date("2026/02/10"))
        self.assertFalse(validate_date("bad"))

    def test_parse_date(self):
        self.assertIsNotNone(parse_date("2026-02-10"))
        self.assertIsNone(parse_date("bad"))
        self.assertIsNone(parse_date(None))

    def test_normalize_date_arg(self):
        for alias in (None, "", "today"):
            out = normalize_date_arg(alias)
            self.assertRegex(out, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual("2026-01-15", normalize_date_arg("2026-01-15"))
        self.assertIsNone(normalize_date_arg("bad"))


class RangeTests(unittest.TestCase):
    def test_validate_box(self):
        self.assertTrue(validate_box(1))
        self.assertTrue(validate_box(5))
        self.assertFalse(validate_box(0))
        self.assertFalse(validate_box(6))

    def test_validate_position(self):
        self.assertTrue(validate_position(1))
        self.assertTrue(validate_position(81))
        self.assertFalse(validate_position(0))
        self.assertFalse(validate_position(82))


class ActionTests(unittest.TestCase):
    def test_allowed_actions(self):
        for action in ("takeout", "move", "取出", "移动"):
            self.assertTrue(validate_action(action))

    def test_legacy_actions_blocked(self):
        for action in ("thaw", "discard", "复苏", "扔掉"):
            self.assertFalse(validate_action(action))


class ParsePositionsTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual([5], parse_positions("5"))
        self.assertEqual([1, 2, 3], parse_positions("1,2,3"))
        self.assertEqual([1, 2, 3], parse_positions("1-3"))
        self.assertEqual([1, 2, 3, 10], parse_positions("1-3,10"))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_positions("0")
        with self.assertRaises(ValueError):
            parse_positions("abc")


class FormattingTests(unittest.TestCase):
    def test_format_chinese_date(self):
        self.assertEqual("2025年01月01日", format_chinese_date("2025-01-01"))
        self.assertIn("(周", format_chinese_date("2025-01-01", weekday=True))

    def test_format_validation_errors(self):
        self.assertIn("Integrity validation failed", format_validation_errors([]))
        msg = format_validation_errors([f"e{i}" for i in range(10)])
        self.assertIn("and 4 more", msg)
        self.assertIn("custom", format_validation_errors(["e"], prefix="custom"))


class IntegrityHelpersTests(unittest.TestCase):
    def test_duplicate_ids(self):
        errors = check_duplicate_ids([{"id": 1}, {"id": 1}])
        self.assertEqual(1, len(errors))
        self.assertIn("ID 1", errors[0])

    def test_position_conflicts(self):
        errors = check_position_conflicts([{"box": 1, "position": 1}, {"box": 1, "position": 1}])
        self.assertEqual(1, len(errors))
        self.assertIn("1", errors[0])


class ValidateRecordTests(unittest.TestCase):
    def _record(self, **overrides):
        rec = {
            "id": 1,
            "box": 1,
            "position": 1,
            "frozen_at": "2025-01-01",
            "cell_line": "NCCIT",
        }
        rec.update(overrides)
        return rec

    def test_valid_record(self):
        errors, _warnings = validate_record(self._record())
        self.assertEqual([], errors)

    def test_empty_position_needs_takeout_history(self):
        errors, _warnings = validate_record(self._record(position=None))
        self.assertTrue(any("position" in e for e in errors))

        errors2, _warnings2 = validate_record(
            self._record(position=None, thaw_events=[{"date": "2025-01-02", "action": "takeout", "positions": [1]}])
        )
        self.assertEqual([], errors2)

    def test_thaw_events_validation(self):
        errors, _warnings = validate_record(self._record(thaw_events="broken"))
        self.assertTrue(any("thaw_events" in e for e in errors))

        errors2, _warnings2 = validate_record(
            self._record(thaw_events=[{"date": "2025-01-02", "action": "invalid", "positions": [1]}])
        )
        self.assertTrue(any("invalid action" in e for e in errors2))


class ValidateInventoryTests(unittest.TestCase):
    def test_root_and_inventory_shape(self):
        errors, _ = validate_inventory("bad")
        self.assertTrue(errors)
        errors2, _ = validate_inventory({"meta": {}})
        self.assertTrue(any("inventory" in e for e in errors2))

    def test_record_and_conflicts(self):
        data = {
            "inventory": [
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01", "cell_line": "A"},
                {"id": 1, "box": 1, "position": 1, "frozen_at": "2025-01-01", "cell_line": "B"},
            ]
        }
        errors, _warnings = validate_inventory(data)
        self.assertTrue(any("ID 1" in e for e in errors))
        self.assertTrue(any("position" in e.lower() or "浣嶇疆" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
