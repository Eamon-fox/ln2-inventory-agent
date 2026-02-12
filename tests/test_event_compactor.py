import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.event_compactor import (
    compact_operation_event_for_context,
    compact_plan_report,
    expand_plan_report,
)


class EventCompactorTests(unittest.TestCase):
    def _sample_report(self):
        shared_response = {
            "ok": True,
            "preview": {"count": 2, "operations": [{"record_id": 1}, {"record_id": 2}]},
            "result": {"count": 2, "record_ids": [1, 2]},
        }
        return {
            "ok": True,
            "items": [
                {"ok": True, "blocked": False, "item": {"record_id": 1}, "response": shared_response},
                {"ok": True, "blocked": False, "item": {"record_id": 2}, "response": shared_response},
            ],
            "stats": {"total": 2, "ok": 2, "blocked": 0},
        }

    def test_compact_expand_report_roundtrip(self):
        report = self._sample_report()
        compact = compact_plan_report(report)
        expanded = expand_plan_report(compact)

        self.assertEqual(report, expanded)

    def test_compact_report_reduces_json_size_when_responses_repeat(self):
        report = self._sample_report()
        compact = compact_plan_report(report)

        raw_len = len(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        compact_len = len(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        self.assertLess(compact_len, raw_len)
        self.assertIn("response_pool", compact)

    def test_event_compactor_only_compacts_plan_events(self):
        event = {
            "type": "plan_executed",
            "report": self._sample_report(),
            "stats": {"total": 2},
        }
        compact = compact_operation_event_for_context(event)
        self.assertIn("response_pool", compact["report"])

        other = {"type": "tool_result", "report": self._sample_report()}
        untouched = compact_operation_event_for_context(other)
        self.assertNotIn("response_pool", untouched["report"])


if __name__ == "__main__":
    unittest.main()
