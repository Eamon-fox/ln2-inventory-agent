"""Unit tests for lib.takeout_parser."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.takeout_parser import (  # noqa: E402
    ACTION_ALIAS,
    extract_events,
    extract_takeout_positions,
    format_positions,
    is_position_active,
    normalize_action,
)


class NormalizeActionTests(unittest.TestCase):
    def test_aliases_takeout_and_move_only(self):
        self.assertEqual("takeout", normalize_action("takeout"))
        self.assertEqual("takeout", normalize_action("取出"))
        self.assertEqual("move", normalize_action("move"))
        self.assertEqual("move", normalize_action("移动"))
        self.assertEqual("move", normalize_action("整理"))

    def test_rejects_legacy_aliases(self):
        self.assertIsNone(normalize_action("thaw"))
        self.assertIsNone(normalize_action("discard"))
        self.assertIsNone(normalize_action("复苏"))
        self.assertIsNone(normalize_action("扔掉"))

    def test_unknown(self):
        self.assertIsNone(normalize_action(None))
        self.assertIsNone(normalize_action(""))
        self.assertIsNone(normalize_action("delete"))


class ExtractEventsTests(unittest.TestCase):
    def test_extracts_and_normalizes(self):
        rec = {
            "thaw_events": [
                {"date": "2026-01-01", "action": "取出", "positions": [1]},
                {"date": "2026-01-02", "action": "move", "positions": [2]},
                {"date": "2026-01-03", "action": "thaw", "positions": [3]},
            ]
        }
        events = extract_events(rec)
        self.assertEqual(2, len(events))
        self.assertEqual("takeout", events[0]["action"])
        self.assertEqual("move", events[1]["action"])

    def test_empty(self):
        self.assertEqual([], extract_events({}))
        self.assertEqual([], extract_events({"thaw_events": []}))
        self.assertEqual([], extract_events({"thaw_events": None}))


class ExtractTakeoutPositionsTests(unittest.TestCase):
    def test_takeout_positions_accumulate(self):
        rec = {
            "thaw_events": [
                {"action": "takeout", "positions": [1, 2]},
                {"action": "取出", "positions": 3},
            ]
        }
        self.assertEqual({1, 2, 3}, extract_takeout_positions(rec))

    def test_move_is_excluded(self):
        rec = {"thaw_events": [{"action": "move", "positions": [1]}]}
        self.assertEqual(set(), extract_takeout_positions(rec))

    def test_all_keyword_uses_record_positions(self):
        rec = {
            "positions": [10, 20, 30],
            "thaw_events": [{"action": "takeout", "positions": "all"}],
        }
        self.assertEqual({10, 20, 30}, extract_takeout_positions(rec))

    def test_out_of_range_filtered(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [0, 1, 82]}]}
        self.assertEqual({1}, extract_takeout_positions(rec))


class IsPositionActiveTests(unittest.TestCase):
    def test_taken_out_position(self):
        rec = {"thaw_events": [{"action": "takeout", "positions": [5]}]}
        self.assertFalse(is_position_active(rec, 5))
        self.assertTrue(is_position_active(rec, 6))


class FormatPositionsTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual("未知", format_positions(None))

    def test_empty_list(self):
        self.assertEqual("无", format_positions([]))

    def test_list(self):
        self.assertEqual("1,2,3", format_positions([1, 2, 3]))

    def test_passthrough(self):
        self.assertEqual("custom", format_positions("custom"))
        self.assertEqual("42", format_positions(42))


class AliasMapTests(unittest.TestCase):
    def test_alias_map_no_legacy_actions(self):
        self.assertIn("takeout", ACTION_ALIAS)
        self.assertIn("move", ACTION_ALIAS)
        self.assertNotIn("thaw", ACTION_ALIAS)
        self.assertNotIn("discard", ACTION_ALIAS)


if __name__ == "__main__":
    unittest.main()
