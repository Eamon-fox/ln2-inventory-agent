import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.audit_guide import build_operation_guide_from_audit_events


class AuditGuideBuilderTests(unittest.TestCase):
    def test_collapse_repeated_moves_into_single_net_move(self):
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 7,
                    "box": 1,
                    "position": 5,
                    "to_position": 10,
                },
                "tool_input": {
                    "record_id": 7,
                    "position": 5,
                    "to_position": 10,
                    "action": "Move",
                },
            },
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 7,
                    "box": 1,
                    "position": 10,
                    "to_position": 20,
                },
                "tool_input": {
                    "record_id": 7,
                    "position": 10,
                    "to_position": 20,
                    "action": "Move",
                },
            },
        ]

        guide = build_operation_guide_from_audit_events(events)
        items = guide["items"]

        self.assertEqual(1, len(items))
        self.assertEqual("move", items[0]["action"])
        self.assertEqual(1, items[0]["box"])
        self.assertEqual(5, items[0]["position"])
        self.assertEqual(20, items[0]["to_position"])

    def test_mixed_actions_are_flattened(self):
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 3,
                    "box": 1,
                    "position": 2,
                    "to_position": 12,
                },
                "tool_input": {
                    "record_id": 3,
                    "position": 2,
                    "to_position": 12,
                    "action": "Move",
                },
            },
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "discard",
                    "record_id": 3,
                    "box": 1,
                    "position": 12,
                },
                "tool_input": {
                    "record_id": 3,
                    "position": 12,
                    "action": "Discard",
                },
            },
            {
                "timestamp": "2026-02-12T09:02:00",
                "action": "add_entry",
                "status": "success",
                "details": {
                    "new_id": 20,
                    "box": 1,
                    "positions": [30],
                    "short_name": "NEW20",
                },
                "tool_input": {
                    "box": 1,
                    "positions": [30],
                    "short_name": "NEW20",
                },
            },
            {
                "timestamp": "2026-02-12T09:03:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "move",
                    "record_id": 20,
                    "box": 1,
                    "position": 30,
                    "to_position": 35,
                },
                "tool_input": {
                    "record_id": 20,
                    "position": 30,
                    "to_position": 35,
                    "action": "Move",
                },
            },
        ]

        guide = build_operation_guide_from_audit_events(events)
        items = guide["items"]

        self.assertEqual(2, len(items))
        self.assertEqual("takeout", items[0]["action"])
        self.assertEqual(2, items[0]["position"])
        self.assertEqual("add", items[1]["action"])
        self.assertEqual(35, items[1]["position"])
        self.assertEqual(20, items[1]["record_id"])

    def test_skips_failed_and_rollback_events(self):
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_takeout",
                "status": "failed",
                "details": {"record_id": 1},
            },
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "rollback",
                "status": "success",
                "details": {},
            },
        ]

        guide = build_operation_guide_from_audit_events(events)
        self.assertEqual([], guide["items"])
        self.assertGreaterEqual(len(guide["warnings"]), 2)

    def test_batch_move_entry_dicts_collapse(self):
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "batch_takeout",
                "status": "success",
                "details": {"action": "move"},
                "tool_input": {
                    "action": "Move",
                    "entries": [{"record_id": 9, "box": 2, "position": 1, "to_position": 5, "to_box": 2}],
                },
            },
            {
                "timestamp": "2026-02-12T09:01:00",
                "action": "batch_takeout",
                "status": "success",
                "details": {"action": "move"},
                "tool_input": {
                    "action": "Move",
                    "entries": [{"record_id": 9, "box": 2, "position": 5, "to_position": 7, "to_box": 2}],
                },
            },
        ]

        guide = build_operation_guide_from_audit_events(events)
        self.assertEqual(1, len(guide["items"]))
        item = guide["items"][0]
        self.assertEqual("move", item["action"])
        self.assertEqual(2, item["box"])
        self.assertEqual(1, item["position"])
        self.assertEqual(7, item["to_position"])

    def test_action_alias_take_out_is_normalized(self):
        events = [
            {
                "timestamp": "2026-02-12T09:00:00",
                "action": "record_takeout",
                "status": "success",
                "details": {
                    "action": "take out",
                    "record_id": 11,
                    "box": 1,
                    "position": 9,
                },
                "tool_input": {
                    "record_id": 11,
                    "position": 9,
                    "action": "take out",
                },
            },
        ]

        guide = build_operation_guide_from_audit_events(events)
        self.assertEqual(1, len(guide["items"]))
        self.assertEqual("takeout", guide["items"][0]["action"])


if __name__ == "__main__":
    unittest.main()

