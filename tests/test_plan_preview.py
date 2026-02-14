"""Unit tests for app_gui/plan_preview.py (pure simulation)."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_preview import simulate_plan_pos_map
from lib.yaml_ops import write_yaml


def make_record(rec_id=1, box=1, pos=1, **extra):
    base = {
        "id": rec_id,
        "parent_cell_line": "K562",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": [pos],
        "frozen_at": "2026-02-10",
    }
    base.update(extra)
    return base


def add_item(box, positions, parent="K562", short="clone", frozen_at="2026-02-13"):
    return {
        "action": "add",
        "box": box,
        "position": positions[0],
        "record_id": None,
        "label": short,
        "source": "human",
        "payload": {
            "box": box,
            "positions": list(positions),
            "frozen_at": frozen_at,
            "fields": {
                "parent_cell_line": parent,
                "short_name": short,
            },
        },
    }


def move_item(record_id, from_pos, to_pos, to_box=None):
    item = {
        "action": "move",
        "box": 1,
        "position": from_pos,
        "to_position": to_pos,
        "record_id": record_id,
        "label": f"rec-{record_id}",
        "source": "human",
        "payload": {"record_id": record_id, "position": from_pos, "to_position": to_pos, "action": "Move"},
    }
    if to_box is not None:
        item["to_box"] = to_box
    return item


def takeout_item(record_id, pos):
    return {
        "action": "takeout",
        "box": 1,
        "position": pos,
        "record_id": record_id,
        "label": f"rec-{record_id}",
        "source": "human",
        "payload": {"record_id": record_id, "position": pos, "action": "Takeout"},
    }


class PlanPreviewSimTests(unittest.TestCase):
    def test_add_predicts_new_ids_and_occupies_positions(self):
        base = {1: make_record(1, box=1, pos=1)}
        plan = [add_item(1, [2, 3], parent="NCCIT", short="stitchr")]
        out = simulate_plan_pos_map(base_records_by_id=base, plan_items=plan)
        self.assertTrue(out["ok"])
        self.assertEqual([2, 3], out["predicted_new_ids"])
        pos_map = out["pos_map"]
        self.assertIn((1, 2), pos_map)
        self.assertIn((1, 3), pos_map)
        self.assertEqual("stitchr", pos_map[(1, 2)].get("short_name"))

    def test_move_updates_location(self):
        base = {1: make_record(1, box=1, pos=1)}
        plan = [move_item(1, 1, 10)]
        out = simulate_plan_pos_map(base_records_by_id=base, plan_items=plan)
        self.assertTrue(out["ok"])
        pos_map = out["pos_map"]
        self.assertNotIn((1, 1), pos_map)
        self.assertIn((1, 10), pos_map)
        self.assertEqual(1, pos_map[(1, 10)]["id"])

    def test_move_swap_same_box(self):
        base = {
            1: make_record(1, box=1, pos=1),
            2: make_record(2, box=1, pos=2),
        }
        plan = [move_item(1, 1, 2)]
        out = simulate_plan_pos_map(base_records_by_id=base, plan_items=plan)
        self.assertTrue(out["ok"])
        pos_map = out["pos_map"]
        self.assertEqual(1, pos_map[(1, 2)]["id"])
        self.assertEqual(2, pos_map[(1, 1)]["id"])

    def test_takeout_removes_position(self):
        base = {1: make_record(1, box=1, pos=5)}
        plan = [takeout_item(1, 5)]
        out = simulate_plan_pos_map(base_records_by_id=base, plan_items=plan)
        self.assertTrue(out["ok"])
        self.assertNotIn((1, 5), out["pos_map"])

    def test_add_then_move_then_takeout(self):
        base = {1: make_record(1, box=1, pos=1)}
        plan = [
            add_item(1, [2], parent="X", short="new"),
            move_item(1, 1, 10),
            takeout_item(1, 10),
        ]
        out = simulate_plan_pos_map(base_records_by_id=base, plan_items=plan)
        self.assertTrue(out["ok"])
        pos_map = out["pos_map"]
        # ID 1 took out; new record stays
        self.assertNotIn((1, 10), pos_map)
        self.assertIn((1, 2), pos_map)

    def test_rollback_preview_loads_backup_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_preview_rb_") as td:
            backup_path = Path(td) / "backup.yaml"
            write_yaml(
                {"meta": {"box_layout": {"rows": 9, "cols": 9}}, "inventory": [make_record(7, box=2, pos=3)]},
                path=str(backup_path),
                auto_backup=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            plan = [
                {
                    "action": "rollback",
                    "box": 0,
                    "position": 1,
                    "record_id": None,
                    "label": "Rollback",
                    "source": "human",
                    "payload": {"backup_path": str(backup_path)},
                }
            ]
            out = simulate_plan_pos_map(base_records_by_id={}, plan_items=plan)
            self.assertTrue(out["ok"])
            self.assertIn((2, 3), out["pos_map"])
            self.assertEqual(7, out["pos_map"][(2, 3)]["id"])


if __name__ == "__main__":
    unittest.main()

