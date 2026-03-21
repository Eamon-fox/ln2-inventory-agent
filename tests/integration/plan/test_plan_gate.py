"""
Module: test_plan_gate
Layer: integration/plan
Covers: lib/plan_gate.py

计划门控预检与阻塞规则的集成测试
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import preflight_plan
from lib.plan_gate import validate_stage_request


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


def make_edit_item(record_id=7, box=1, position=5, fields=None):
    return {
        "action": "edit",
        "box": box,
        "position": position,
        "record_id": record_id,
        "source": "human",
        "payload": {
            "record_id": record_id,
            "fields": dict(fields or {"note": "edited"}),
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


class PlanGateDedupStageTests(unittest.TestCase):
    def test_duplicate_exact_item_is_treated_as_noop(self):
        existing = [make_takeout_item()]
        incoming = [make_takeout_item()]

        result = validate_stage_request(
            existing_items=existing,
            incoming_items=incoming,
            yaml_path=None,
            bridge=None,
            run_preflight=False,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual([], result["accepted_items"])
        self.assertEqual(1, len(result["noop_items"]))
        self.assertEqual(0, result["stats"]["accepted"])
        self.assertEqual(1, result["stats"]["noop"])

    def test_same_key_with_changed_payload_replaces_existing(self):
        existing = [make_move_item()]
        incoming = [dict(make_move_item(), to_position=20, payload=dict(make_move_item()["payload"], to_position=20))]

        result = validate_stage_request(
            existing_items=existing,
            incoming_items=incoming,
            yaml_path=None,
            bridge=None,
            run_preflight=False,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(1, len(result["accepted_items"]))
        self.assertEqual(20, result["accepted_items"][0]["to_position"])
        self.assertEqual([], result["noop_items"])

    def test_same_key_edit_merges_existing_fields(self):
        existing = [
            make_edit_item(
                record_id=435,
                fields={"plasmid_name": "p1", "plasmid_id": "id1"},
            )
        ]
        incoming = [
            make_edit_item(
                record_id=435,
                fields={"sample": "TetOn-StitchR-Clone4"},
            )
        ]

        result = validate_stage_request(
            existing_items=existing,
            incoming_items=incoming,
            yaml_path=None,
            bridge=None,
            run_preflight=False,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(1, len(result["accepted_items"]))
        self.assertEqual(
            {
                "plasmid_name": "p1",
                "plasmid_id": "id1",
                "sample": "TetOn-StitchR-Clone4",
            },
            result["accepted_items"][0]["payload"]["fields"],
        )
        self.assertEqual([], result["noop_items"])

    def test_same_key_edit_with_no_effective_change_is_noop(self):
        existing = [make_edit_item(record_id=435, fields={"sample": "new", "note": ""})]
        incoming = [make_edit_item(record_id=435, fields={"sample": "new"})]

        result = validate_stage_request(
            existing_items=existing,
            incoming_items=incoming,
            yaml_path=None,
            bridge=None,
            run_preflight=False,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual([], result["accepted_items"])
        self.assertEqual(1, len(result["noop_items"]))

    def test_duplicate_restage_stays_blocked_when_current_plan_is_already_invalid(self):
        from lib.inventory_paths import ensure_inventories_root, get_inventories_root
        from lib.yaml_ops import write_yaml

        ensure_inventories_root()
        tmpdir = tempfile.mkdtemp(prefix="ln2_plan_gate_", dir=get_inventories_root())
        yaml_path = os.path.join(tmpdir, "inventory.yaml")
        write_yaml(
            {
                "meta": {"box_layout": {"rows": 9, "cols": 9}},
                "inventory": [],
            },
            path=yaml_path,
            audit_meta={"action": "seed", "source": "tests"},
        )
        self.addCleanup(shutil.rmtree, tmpdir, True)

        existing = [make_takeout_item()]
        incoming = [make_takeout_item()]

        result = validate_stage_request(
            existing_items=existing,
            incoming_items=incoming,
            yaml_path=yaml_path,
            bridge=None,
            run_preflight=True,
            preflight_fn=preflight_plan,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual([], result["accepted_items"])
        self.assertEqual(1, len(result["noop_items"]))
        self.assertTrue(result["blocked_items"])
