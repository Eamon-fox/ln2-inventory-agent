"""Unit tests for lib/thaw_parser.py — action normalization, event extraction, position tracking."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.thaw_parser import (
    ACTION_ALIAS,
    extract_events,
    extract_thaw_positions,
    format_positions,
    is_position_active,
    normalize_action,
)


class NormalizeActionTests(unittest.TestCase):
    def test_chinese_aliases(self):
        self.assertEqual("takeout", normalize_action("取出"))
        self.assertEqual("thaw", normalize_action("复苏"))
        self.assertEqual("discard", normalize_action("扔掉"))
        self.assertEqual("discard", normalize_action("丢掉"))
        self.assertEqual("move", normalize_action("移动"))
        self.assertEqual("move", normalize_action("整理"))

    def test_english_aliases(self):
        self.assertEqual("takeout", normalize_action("takeout"))
        self.assertEqual("thaw", normalize_action("thaw"))
        self.assertEqual("discard", normalize_action("discard"))
        self.assertEqual("move", normalize_action("move"))

    def test_case_insensitive(self):
        self.assertEqual("takeout", normalize_action("Takeout"))
        self.assertEqual("thaw", normalize_action("THAW"))
        self.assertEqual("move", normalize_action("Move"))

    def test_none_returns_none(self):
        self.assertIsNone(normalize_action(None))

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize_action("delete"))
        self.assertIsNone(normalize_action(""))
        self.assertIsNone(normalize_action("unknown"))

    def test_whitespace_stripped(self):
        self.assertEqual("takeout", normalize_action("  takeout  "))


class ExtractEventsTests(unittest.TestCase):
    def test_extracts_valid_events(self):
        rec = {
            "thaw_events": [
                {"date": "2026-01-01", "action": "takeout", "positions": [1]},
                {"date": "2026-01-02", "action": "thaw", "positions": [2]},
            ]
        }
        events = extract_events(rec)
        self.assertEqual(2, len(events))
        self.assertEqual("takeout", events[0]["action"])
        self.assertEqual("thaw", events[1]["action"])

    def test_skips_invalid_action(self):
        rec = {
            "thaw_events": [
                {"date": "2026-01-01", "action": "invalid", "positions": [1]},
                {"date": "2026-01-02", "action": "takeout", "positions": [2]},
            ]
        }
        events = extract_events(rec)
        self.assertEqual(1, len(events))

    def test_empty_events(self):
        self.assertEqual([], extract_events({}))
        self.assertEqual([], extract_events({"thaw_events": []}))
        self.assertEqual([], extract_events({"thaw_events": None}))

    def test_normalizes_chinese_action(self):
        rec = {"thaw_events": [{"date": "2026-01-01", "action": "复苏", "positions": [1]}]}
        events = extract_events(rec)
        self.assertEqual("thaw", events[0]["action"])


class ExtractThawPositionsTests(unittest.TestCase):
    def test_single_takeout(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [5]}]}
        self.assertEqual({5}, extract_thaw_positions(rec))

    def test_multiple_events_accumulate(self):
        rec = {
            "thaw_events": [
                {"action": "takeout", "positions": [1]},
                {"action": "thaw", "positions": [2, 3]},
            ]
        }
        self.assertEqual({1, 2, 3}, extract_thaw_positions(rec))

    def test_move_is_excluded(self):
        rec = {"thaw_events": [{"action": "move", "positions": [1]}]}
        self.assertEqual(set(), extract_thaw_positions(rec))

    def test_all_literal(self):
        rec = {
            "positions": [10, 20, 30],
            "thaw_events": [{"action": "discard", "positions": "all"}],
        }
        self.assertEqual({10, 20, 30}, extract_thaw_positions(rec))

    def test_int_position_coerced_to_list(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": 5}]}
        self.assertEqual({5}, extract_thaw_positions(rec))

    def test_none_positions_skipped(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": None}]}
        self.assertEqual(set(), extract_thaw_positions(rec))

    def test_empty_record(self):
        self.assertEqual(set(), extract_thaw_positions({}))

    def test_position_out_of_range_excluded(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [0, 1, 82]}]}
        self.assertEqual({1}, extract_thaw_positions(rec))


class IsPositionActiveTests(unittest.TestCase):
    def test_active_position(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [1]}]}
        self.assertTrue(is_position_active(rec, 2))

    def test_taken_out_position(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [1]}]}
        self.assertFalse(is_position_active(rec, 1))

    def test_no_events_all_active(self):
        rec = {}
        self.assertTrue(is_position_active(rec, 1))


class FormatPositionsTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual("未知", format_positions(None))

    def test_string_passthrough(self):
        self.assertEqual("custom", format_positions("custom"))

    def test_empty_list(self):
        self.assertEqual("无", format_positions([]))

    def test_list(self):
        self.assertEqual("1,2,3", format_positions([1, 2, 3]))

    def test_other_type(self):
        self.assertEqual("42", format_positions(42))


if __name__ == "__main__":
    unittest.main()
