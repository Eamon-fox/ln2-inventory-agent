import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_outcome import collect_blocked_items, summarize_plan_execution


class PlanOutcomeTests(unittest.TestCase):
    def test_summarize_rolls_back_applied_count_to_zero(self):
        report = {
            "stats": {"total": 3, "ok": 2, "blocked": 1},
            "items": [],
        }
        rollback = {"attempted": True, "ok": True, "message": "Rolled back"}

        summary = summarize_plan_execution(report, rollback)

        self.assertEqual(3, summary["total_count"])
        self.assertEqual(2, summary["ok_count"])
        self.assertEqual(1, summary["fail_count"])
        self.assertEqual(0, summary["applied_count"])
        self.assertTrue(summary["rollback_ok"])

    def test_summarize_falls_back_to_items_when_stats_missing(self):
        report = {
            "items": [
                {"ok": True, "blocked": False},
                {"ok": False, "blocked": True},
            ]
        }

        summary = summarize_plan_execution(report)

        self.assertEqual(2, summary["total_count"])
        self.assertEqual(1, summary["ok_count"])
        self.assertEqual(1, summary["blocked_count"])
        self.assertEqual(1, summary["fail_count"])
        self.assertEqual(1, summary["applied_count"])

    def test_collect_blocked_items_filters_non_blocked_entries(self):
        report = {
            "items": [
                {"ok": True, "blocked": False, "item": {"record_id": 1}},
                {"ok": False, "blocked": True, "item": {"record_id": 2}},
                {"ok": False, "item": {"record_id": 3}},
            ]
        }

        blocked = collect_blocked_items(report)

        self.assertEqual(1, len(blocked))
        self.assertEqual(2, blocked[0]["item"]["record_id"])


if __name__ == "__main__":
    unittest.main()
