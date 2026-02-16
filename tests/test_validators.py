"""Unit tests for lib/validators.py — boundary values, edge cases, invariants."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validators import (
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


class ValidateDateTests(unittest.TestCase):
    def test_valid_date(self):
        self.assertTrue(validate_date("2026-02-10"))
        self.assertTrue(validate_date("2000-01-01"))

    def test_invalid_formats(self):
        self.assertFalse(validate_date("2026/02/10"))
        self.assertFalse(validate_date("02-10-2026"))
        self.assertFalse(validate_date("not-a-date"))
        self.assertFalse(validate_date(""))

    def test_none_and_non_string(self):
        self.assertFalse(validate_date(None))
        self.assertFalse(validate_date(12345))

    def test_impossible_date(self):
        self.assertFalse(validate_date("2026-02-30"))
        self.assertFalse(validate_date("2026-13-01"))


class ParseDateTests(unittest.TestCase):
    def test_valid(self):
        dt = parse_date("2026-02-10")
        self.assertIsNotNone(dt)
        self.assertEqual(2026, dt.year)

    def test_none_empty(self):
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date(""))

    def test_invalid(self):
        self.assertIsNone(parse_date("bad"))
        self.assertIsNone(parse_date("2026/02/10"))


class NormalizeDateArgTests(unittest.TestCase):
    def test_today_aliases(self):
        for alias in (None, "", "today", "今天"):
            result = normalize_date_arg(alias)
            self.assertIsNotNone(result)
            self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_passthrough_valid(self):
        self.assertEqual("2026-01-15", normalize_date_arg("2026-01-15"))

    def test_invalid_returns_none(self):
        self.assertIsNone(normalize_date_arg("garbage"))
        self.assertIsNone(normalize_date_arg("02/10/2026"))


class ValidateBoxTests(unittest.TestCase):
    """BOX_RANGE defaults to (1, 5)."""

    def test_valid_boundaries(self):
        self.assertTrue(validate_box(1))
        self.assertTrue(validate_box(5))
        self.assertTrue(validate_box(3))

    def test_out_of_range(self):
        self.assertFalse(validate_box(0))
        self.assertFalse(validate_box(6))
        self.assertFalse(validate_box(-1))
        self.assertFalse(validate_box(100))


class ValidatePositionTests(unittest.TestCase):
    """POSITION_RANGE defaults to (1, 81)."""

    def test_valid_boundaries(self):
        self.assertTrue(validate_position(1))
        self.assertTrue(validate_position(81))
        self.assertTrue(validate_position(40))

    def test_out_of_range(self):
        self.assertFalse(validate_position(0))
        self.assertFalse(validate_position(82))
        self.assertFalse(validate_position(-1))
        self.assertFalse(validate_position(999))


class ValidateActionTests(unittest.TestCase):
    def test_valid_chinese_actions(self):
        for act in ("取出", "复苏", "扔掉", "移动"):
            self.assertTrue(validate_action(act), f"{act} should be valid")

    def test_english_actions_are_invalid_by_default(self):
        # VALID_ACTIONS comes from config and defaults to Chinese labels
        self.assertFalse(validate_action("takeout"))
        self.assertFalse(validate_action("thaw"))

    def test_invalid(self):
        self.assertFalse(validate_action(""))
        self.assertFalse(validate_action("delete"))
        self.assertFalse(validate_action(None))


class ParsePositionsTests(unittest.TestCase):
    def test_single(self):
        self.assertEqual([5], parse_positions("5"))

    def test_csv(self):
        self.assertEqual([1, 2, 3], parse_positions("1,2,3"))

    def test_range(self):
        self.assertEqual([1, 2, 3], parse_positions("1-3"))

    def test_mixed(self):
        self.assertEqual([1, 2, 3, 10], parse_positions("1-3,10"))

    def test_deduplicates(self):
        self.assertEqual([1, 2], parse_positions("1,1,2"))

    def test_sorts(self):
        self.assertEqual([1, 5, 10], parse_positions("10,1,5"))

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            parse_positions("0")
        with self.assertRaises(ValueError):
            parse_positions("82")

    def test_bad_format_raises(self):
        with self.assertRaises(ValueError):
            parse_positions("abc")


class FormatChineseDateTests(unittest.TestCase):
    def test_basic(self):
        result = format_chinese_date("2026-02-10")
        self.assertIn("2026", result)
        self.assertIn("02", result)
        self.assertIn("10", result)

    def test_weekday(self):
        result = format_chinese_date("2026-02-10", weekday=True)
        self.assertIn("周", result)

    def test_invalid_passthrough(self):
        self.assertEqual("bad-date", format_chinese_date("bad-date"))


class CheckDuplicateIdsTests(unittest.TestCase):
    def test_no_duplicates(self):
        records = [{"id": 1}, {"id": 2}, {"id": 3}]
        self.assertEqual([], check_duplicate_ids(records))

    def test_duplicates_detected(self):
        records = [{"id": 1}, {"id": 2}, {"id": 1}]
        errors = check_duplicate_ids(records)
        self.assertEqual(1, len(errors))
        self.assertIn("重复", errors[0])

    def test_none_id_skipped(self):
        records = [{"id": None}, {"id": None}]
        self.assertEqual([], check_duplicate_ids(records))

    def test_empty(self):
        self.assertEqual([], check_duplicate_ids([]))


class CheckPositionConflictsTests(unittest.TestCase):
    def test_no_conflict(self):
        records = [
            {"box": 1, "position": 1},
            {"box": 1, "position": 2},
        ]
        self.assertEqual([], check_position_conflicts(records))

    def test_conflict_same_box_same_position(self):
        records = [
            {"box": 1, "position": 1},
            {"box": 1, "position": 1},
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(1, len(errors))
        self.assertIn("位置冲突", errors[0])

    def test_same_position_different_box_ok(self):
        records = [
            {"box": 1, "position": 1},
            {"box": 2, "position": 1},
        ]
        self.assertEqual([], check_position_conflicts(records))

    def test_empty_position_no_conflict(self):
        records = [
            {"box": 1, "position": None},
            {"box": 1, "position": None},
        ]
        self.assertEqual([], check_position_conflicts(records))


class ValidateRecordTests(unittest.TestCase):
    def _valid_record(self, **overrides):
        base = {
            "id": 1,
            "parent_cell_line": "NCCIT",
            "short_name": "test-1",
            "box": 1,
            "position": 1,
            "frozen_at": "2025-01-01",
        }
        base.update(overrides)
        return base

    def test_valid_record_no_errors(self):
        errors, warnings = validate_record(self._valid_record())
        self.assertEqual([], errors)

    def test_missing_required_field(self):
        rec = self._valid_record()
        del rec["short_name"]
        errors, _ = validate_record(rec)
        self.assertTrue(any("short_name" in e for e in errors))

    def test_id_must_be_positive_int(self):
        errors, _ = validate_record(self._valid_record(id=0))
        self.assertTrue(any("id" in e for e in errors))
        errors, _ = validate_record(self._valid_record(id=-1))
        self.assertTrue(any("id" in e for e in errors))
        errors, _ = validate_record(self._valid_record(id="abc"))
        self.assertTrue(any("id" in e for e in errors))

    def test_box_out_of_range(self):
        errors, _ = validate_record(self._valid_record(box=0))
        self.assertTrue(any("box" in e for e in errors))
        errors, _ = validate_record(self._valid_record(box=99))
        self.assertTrue(any("box" in e for e in errors))

    def test_box_must_be_int(self):
        errors, _ = validate_record(self._valid_record(box="abc"))
        self.assertTrue(any("box" in e for e in errors))

    def test_position_must_be_int(self):
        errors, _ = validate_record(self._valid_record(position="abc"))
        self.assertTrue(any("position" in e and "整数" in e for e in errors))

    def test_position_out_of_range(self):
        errors, _ = validate_record(self._valid_record(position=0))
        self.assertTrue(any("超出范围" in e for e in errors))
        errors, _ = validate_record(self._valid_record(position=82))
        self.assertTrue(any("超出范围" in e for e in errors))

    def test_empty_position_with_depletion_history_ok(self):
        rec = self._valid_record(position=None)
        rec["thaw_events"] = [
            {"date": "2025-06-01", "action": "takeout", "positions": [1]}
        ]
        errors, _ = validate_record(rec)
        self.assertEqual([], errors)

    def test_empty_position_without_history_errors(self):
        errors, _ = validate_record(self._valid_record(position=None))
        self.assertTrue(any("为空" in e for e in errors))

    def test_frozen_at_invalid_format(self):
        errors, _ = validate_record(self._valid_record(frozen_at="01/01/2025"))
        self.assertTrue(any("frozen_at" in e for e in errors))

    def test_thaw_events_must_be_list(self):
        rec = self._valid_record()
        rec["thaw_events"] = "broken"
        errors, _ = validate_record(rec)
        self.assertTrue(any("thaw_events" in e and "列表" in e for e in errors))

    def test_thaw_event_invalid_action(self):
        rec = self._valid_record()
        rec["thaw_events"] = [
            {"date": "2025-06-01", "action": "invalid", "positions": [1]}
        ]
        errors, _ = validate_record(rec)
        self.assertTrue(any("action" in e for e in errors))

    def test_thaw_event_positions_must_be_nonempty_list(self):
        rec = self._valid_record()
        rec["thaw_events"] = [
            {"date": "2025-06-01", "action": "takeout", "positions": []}
        ]
        errors, _ = validate_record(rec)
        self.assertTrue(any("positions" in e and "非空" in e for e in errors))


class ValidateInventoryTests(unittest.TestCase):
    def test_non_dict_root(self):
        errors, _ = validate_inventory("string")
        self.assertTrue(any("根节点" in e for e in errors))

    def test_missing_inventory_key(self):
        errors, _ = validate_inventory({"meta": {}})
        self.assertTrue(any("inventory" in e for e in errors))

    def test_empty_inventory_ok(self):
        errors, _ = validate_inventory({"inventory": []})
        self.assertEqual([], errors)

    def test_non_dict_record_entry(self):
        errors, _ = validate_inventory({"inventory": ["not-a-dict"]})
        self.assertTrue(any("必须是对象" in e for e in errors))

    def test_detects_cross_record_id_duplicates(self):
        records = [
            {
                "id": 1,
                "parent_cell_line": "A",
                "short_name": "a",
                "box": 1,
                "positions": [1],
                "frozen_at": "2025-01-01",
            },
            {
                "id": 1,
                "parent_cell_line": "B",
                "short_name": "b",
                "box": 1,
                "positions": [2],
                "frozen_at": "2025-01-01",
            },
        ]
        errors, _ = validate_inventory({"inventory": records})
        self.assertTrue(any("重复" in e for e in errors))

    def test_detects_cross_record_position_conflicts(self):
        records = [
            {
                "id": 1,
                "parent_cell_line": "A",
                "short_name": "a",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
            {
                "id": 2,
                "parent_cell_line": "B",
                "short_name": "b",
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
            },
        ]
        errors, _ = validate_inventory({"inventory": records})
        self.assertTrue(any("位置冲突" in e for e in errors))


class FormatValidationErrorsTests(unittest.TestCase):
    def test_empty_errors(self):
        result = format_validation_errors([])
        self.assertIn("完整性校验失败", result)

    def test_truncates_at_six(self):
        errors = [f"error-{i}" for i in range(10)]
        result = format_validation_errors(errors)
        self.assertIn("另外 4 条", result)

    def test_custom_prefix(self):
        result = format_validation_errors(["err"], prefix="自定义前缀")
        self.assertIn("自定义前缀", result)


if __name__ == "__main__":
    unittest.main()
