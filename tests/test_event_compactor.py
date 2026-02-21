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

    def test_system_notice_compacts_nested_report_in_data(self):
        event = {
            "type": "system_notice",
            "code": "plan.execute.result",
            "text": "Execution completed",
            "data": {
                "report": self._sample_report(),
                "stats": {"total": 2},
            },
        }
        compact = compact_operation_event_for_context(event)
        compact_data = compact.get("data")
        data = compact_data if isinstance(compact_data, dict) else {}
        nested_report = data.get("report")
        nested = nested_report if isinstance(nested_report, dict) else {}
        self.assertIn("response_pool", nested)
        self.assertIn("_hint", compact)

    def test_plan_stage_blocked_notice_is_compacted_for_context(self):
        long_msg = (
            "Write blocked: integrity validation failed\n"
            "- Record #16 (id=16): cell_line invalid\n"
            "- Record #17 (id=17): cell_line invalid\n"
            "- Record #18 (id=18): cell_line invalid"
        )
        event = {
            "type": "system_notice",
            "code": "plan.stage.blocked",
            "text": "Plan rejected: " + long_msg,
            "details": long_msg,
            "data": {
                "blocked_items": [
                    {
                        "action": "takeout",
                        "record_id": 21,
                        "box": 2,
                        "position": 16,
                        "error_code": "preflight_snapshot_invalid",
                        "message": long_msg,
                    }
                ],
                "errors": [
                    {
                        "kind": "preflight",
                        "error_code": "preflight_snapshot_invalid",
                        "message": long_msg,
                        "item": {
                            "action": "takeout",
                            "record_id": 21,
                            "box": 2,
                            "position": 16,
                            "payload": {"very": "large"},
                        },
                    }
                ],
                "incoming_items": [
                    {
                        "action": "takeout",
                        "record_id": 21,
                        "box": 2,
                        "position": 16,
                        "payload": {"very": "large"},
                    }
                ],
            },
        }

        compact = compact_operation_event_for_context(event)
        raw_data = compact.get("data")
        compact_data = raw_data if isinstance(raw_data, dict) else {}
        raw_blocked = compact_data.get("blocked_items")
        blocked = raw_blocked if isinstance(raw_blocked, list) else []
        self.assertTrue(blocked)
        first = blocked[0] if isinstance(blocked[0], dict) else {}
        self.assertNotIn("\n", first.get("message", ""))
        self.assertIn("validation_record_ids", compact_data)
        raw_ids = compact_data.get("validation_record_ids")
        ids = list(raw_ids) if isinstance(raw_ids, list) else []
        self.assertIn(16, ids)


if __name__ == "__main__":
    unittest.main()
