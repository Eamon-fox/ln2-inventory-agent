"""Unit tests for app_gui/plan_gate.py payload-schema strictness."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_gate import validate_stage_request


def make_add_item():
    return {
        "action": "add",
        "box": 1,
        "position": 5,
        "record_id": None,
        "source": "human",
        "payload": {
            "box": 1,
            "positions": [5],
            "frozen_at": "2026-02-10",
            "fields": {"short_name": "clone-a"},
        },
    }


def make_takeout_item():
    return {
        "action": "takeout",
        "box": 1,
        "position": 5,
        "record_id": 7,
        "source": "human",
        "payload": {
            "record_id": 7,
            "position": 5,
            "date_str": "2026-02-10",
            "action": "Takeout",
        },
    }


def make_move_item():
    return {
        "action": "move",
        "box": 1,
        "position": 5,
        "to_position": 10,
        "to_box": 1,
        "record_id": 7,
        "source": "human",
        "payload": {
            "record_id": 7,
            "position": 5,
            "to_position": 10,
            "to_box": 1,
            "date_str": "2026-02-10",
            "action": "Move",
        },
    }


class PlanGatePayloadSchemaTests(unittest.TestCase):
    def _validate_incoming(self, item):
        return validate_stage_request(
            existing_items=[],
            incoming_items=[item],
            yaml_path=None,
            bridge=None,
            run_preflight=False,
        )

    def test_accepts_valid_add_payload(self):
        result = self._validate_incoming(make_add_item())
        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(1, len(result["accepted_items"]))

    def test_rejects_add_payload_positions_not_integer_list(self):
        item = make_add_item()
        item["payload"]["positions"] = ["A5"]
        result = self._validate_incoming(item)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("payload.positions[0]", result["errors"][0]["message"])

    def test_rejects_takeout_payload_position_mismatch(self):
        item = make_takeout_item()
        item["payload"]["position"] = 6
        result = self._validate_incoming(item)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("payload.position must match item.position", result["errors"][0]["message"])

    def test_rejects_move_payload_missing_to_position(self):
        item = make_move_item()
        item["payload"].pop("to_position")
        result = self._validate_incoming(item)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("payload.to_position", result["errors"][0]["message"])

    def test_allows_move_payload_same_position_for_cross_box(self):
        item = make_move_item()
        item["to_box"] = 2
        item["payload"]["to_box"] = 2
        item["to_position"] = item["position"]
        item["payload"]["to_position"] = item["payload"]["position"]
        result = self._validate_incoming(item)

        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(1, len(result["accepted_items"]))

    def test_rejects_move_payload_same_position_for_same_box(self):
        item = make_move_item()
        item["to_box"] = 1
        item["payload"]["to_box"] = 1
        item["to_position"] = item["position"]
        item["payload"]["to_position"] = item["payload"]["position"]
        result = self._validate_incoming(item)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("differ from position", result["errors"][0]["message"])

    def test_rejects_rollback_payload_missing_backup_path(self):
        item = {
            "action": "rollback",
            "box": 0,
            "position": 1,
            "record_id": None,
            "source": "human",
            "payload": {"backup_path": ""},
        }
        result = self._validate_incoming(item)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("payload.backup_path", result["errors"][0]["message"])
