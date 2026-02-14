"""Invariant & edge-case tests for lib/tool_api.py.

These tests verify properties that must ALWAYS hold, regardless of
implementation details.  They are designed to catch bugs before they
surface as end-to-end failures.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    parse_batch_entries,
    tool_add_entry,
    tool_batch_thaw,
    tool_record_thaw,
)
from lib.yaml_ops import load_yaml, write_yaml


def make_record(rec_id=1, box=1, positions=None, **extra):
    base = {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }
    base.update(extra)
    return base


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def _seed(temp_dir, records):
    yaml_path = Path(temp_dir) / "inventory.yaml"
    write_yaml(
        make_data(records),
        path=str(yaml_path),
        audit_meta={"action": "seed", "source": "tests"},
    )
    return str(yaml_path)


def _read_audit(temp_dir):
    audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
    if not audit_path.exists():
        return []
    return [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── parse_batch_entries ─────────────────────────────────────────────


class ParseBatchEntriesTests(unittest.TestCase):
    def test_csv_string(self):
        result = parse_batch_entries("1:5,2:10")
        self.assertEqual([(1, 5), (2, 10)], result)

    def test_move_string(self):
        result = parse_batch_entries("1:5->10")
        self.assertEqual([(1, 5, 10)], result)

    def test_whitespace_tolerance(self):
        result = parse_batch_entries("  1 : 5 , 2 : 10 ")
        self.assertEqual([(1, 5), (2, 10)], result)

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            parse_batch_entries("not-valid")


# ── Position consistency invariants ─────────────────────────────────


class PositionConsistencyTests(unittest.TestCase):
    """After any write operation, the resulting YAML must satisfy these invariants."""

    def test_takeout_removes_position_completely(self):
        """After takeout, the removed position must NOT appear in positions list."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[2])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=2,
                date_str="2026-02-10", action="取出",
            )
            data = load_yaml(yp)
            positions = data["inventory"][0]["positions"]
            self.assertNotIn(2, positions)
            self.assertEqual([], positions)

    def test_takeout_creates_thaw_event(self):
        """Every takeout must record a thaw_event with the removed position."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=1,
                date_str="2026-02-10", action="取出",
            )
            data = load_yaml(yp)
            events = data["inventory"][0].get("thaw_events", [])
            self.assertEqual(1, len(events))
            self.assertEqual([1], events[0]["positions"])

    def test_takeout_last_position_results_in_empty_list(self):
        """Taking out the only remaining position yields positions=[]."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[5])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=5,
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            self.assertEqual([], data["inventory"][0]["positions"])

    def test_move_preserves_position_count(self):
        """Move must not change the total number of positions on the record."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=10,
                date_str="2026-02-10", action="move",
            )
            data = load_yaml(yp)
            self.assertEqual(1, len(data["inventory"][0]["positions"]))

    def test_move_replaces_old_with_new(self):
        """After move, old position is gone and new position is present."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=5,
                date_str="2026-02-10", action="move",
            )
            data = load_yaml(yp)
            positions = data["inventory"][0]["positions"]
            self.assertNotIn(1, positions)
            self.assertIn(5, positions)

    def test_swap_preserves_both_records_position_count(self):
        """Swap must not change position counts on either record."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[3]),
            ])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=3,
                date_str="2026-02-10", action="move",
            )
            data = load_yaml(yp)
            self.assertEqual(1, len(data["inventory"][0]["positions"]))
            self.assertEqual(1, len(data["inventory"][1]["positions"]))

    def test_add_entry_creates_record_with_specified_positions(self):
        """After add, the new tube records must cover exactly the requested positions."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_add_entry(
                yaml_path=yp,
                box=2, positions=[10, 11, 12],
                frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "clone-new"},
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            new_ids = set(result.get("result", {}).get("new_ids") or [])
            new_recs = [rec for rec in data.get("inventory", []) if rec.get("id") in new_ids]
            self.assertEqual(3, len(new_recs))
            self.assertEqual({10, 11, 12}, {int(rec["positions"][0]) for rec in new_recs})
            self.assertTrue(all(len(rec.get("positions") or []) == 1 for rec in new_recs))

    def test_no_double_occupancy_after_add(self):
        """Adding to a position already occupied must be rejected."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[5])])
            result = tool_add_entry(
                yaml_path=yp,
                box=1, positions=[5],
                frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "conflict"},
            )
            self.assertFalse(result["ok"])


# ── Batch same-record edge cases ────────────────────────────────────


class BatchSameRecordTests(unittest.TestCase):
    """All same-record batch scenarios that previously had a bug."""

    def test_takeout_all_positions_of_one_record(self):
        """Batch takeout across multiple tubes should consume each tube independently."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[2]),
                make_record(3, box=1, positions=[3]),
            ])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 1), (2, 2), (3, 3)],
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            self.assertEqual([], data["inventory"][0]["positions"])
            self.assertEqual([], data["inventory"][1]["positions"])
            self.assertEqual([], data["inventory"][2]["positions"])

    def test_takeout_two_of_three_positions(self):
        """Taking out 2 of 3 tubes should leave the untouched tube unchanged."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[10]),
                make_record(2, box=1, positions=[20]),
                make_record(3, box=1, positions=[30]),
            ])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 10), (3, 30)],
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            self.assertEqual([], data["inventory"][0]["positions"])
            self.assertEqual([20], data["inventory"][1]["positions"])
            self.assertEqual([], data["inventory"][2]["positions"])

    def test_mixed_records_batch(self):
        """Batch targeting different records + same record together."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[2]),
                make_record(3, box=1, positions=[3]),
                make_record(4, box=1, positions=[4]),
            ])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 1), (2, 2), (4, 4)],
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            # IDs 1,2,4 are consumed; ID 3 untouched.
            by_id = {int(rec.get("id")): rec for rec in data.get("inventory", [])}
            self.assertEqual([], by_id[1]["positions"])
            self.assertEqual([], by_id[2]["positions"])
            self.assertEqual([3], by_id[3]["positions"])
            self.assertEqual([], by_id[4]["positions"])

    def test_batch_duplicate_position_same_record_detected(self):
        """Trying to remove the same position twice should fail on the second one."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 1), (1, 1)],
                date_str="2026-02-10", action="取出",
            )
            # The second (1,1) should fail validation because position 1
            # was already removed by the first entry.
            self.assertFalse(result["ok"])


# ── Audit trail invariants ──────────────────────────────────────────


class AuditTrailTests(unittest.TestCase):
    """Every write operation must produce an audit trail entry."""

    def test_successful_add_writes_audit(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            tool_add_entry(
                yaml_path=yp,
                box=1, positions=[1],
                frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "audit-test"},
            )
            rows = _read_audit(td)
            add_rows = [r for r in rows if r.get("action") == "add_entry"]
            self.assertGreaterEqual(len(add_rows), 1)
            last = add_rows[-1]
            self.assertEqual("success", last.get("status"))

    def test_successful_thaw_writes_audit(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=1,
                date_str="2026-02-10", action="取出",
            )
            rows = _read_audit(td)
            thaw_rows = [r for r in rows if r.get("action") == "record_thaw"]
            self.assertGreaterEqual(len(thaw_rows), 1)

    def test_successful_batch_writes_audit(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[2]),
            ])
            tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 1), (2, 2)],
                date_str="2026-02-10", action="取出",
            )
            rows = _read_audit(td)
            batch_rows = [r for r in rows if r.get("action") == "batch_thaw"]
            self.assertGreaterEqual(len(batch_rows), 1)

    def test_failed_add_writes_failed_audit(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            tool_add_entry(
                yaml_path=yp,
                box=99, positions=[1],  # invalid box
                frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "x"},
            )
            rows = _read_audit(td)
            failed = [r for r in rows if r.get("status") == "failed"]
            self.assertGreaterEqual(len(failed), 1)


# ── Boundary values on tool_api ─────────────────────────────────────


class BoundaryValueTests(unittest.TestCase):
    def test_position_at_min_max_boundary(self):
        """Operations at position=1 and position=81 should work."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[81]),
            ])

            r1 = tool_record_thaw(
                yaml_path=yp, record_id=1, position=1,
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(r1["ok"])

            r2 = tool_record_thaw(
                yaml_path=yp, record_id=2, position=81,
                date_str="2026-02-10", action="取出",
            )
            self.assertTrue(r2["ok"])

            data = load_yaml(yp)
            self.assertEqual([], data["inventory"][0]["positions"])
            self.assertEqual([], data["inventory"][1]["positions"])

    def test_position_zero_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=0,
                date_str="2026-02-10",
            )
            self.assertFalse(result["ok"])

    def test_position_82_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=82,
                date_str="2026-02-10",
            )
            self.assertFalse(result["ok"])

    def test_box_at_min_max(self):
        """Add entry to box 1 and box 5 (boundaries)."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            r1 = tool_add_entry(
                yaml_path=yp,
                box=1, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "box1"},
            )
            self.assertTrue(r1["ok"])

            r5 = tool_add_entry(
                yaml_path=yp,
                box=5, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "box5"},
            )
            self.assertTrue(r5["ok"])

    def test_box_zero_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            result = tool_add_entry(
                yaml_path=yp,
                box=0, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "x"},
            )
            self.assertFalse(result["ok"])

    def test_box_six_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            result = tool_add_entry(
                yaml_path=yp,
                box=6, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": "x"},
            )
            self.assertFalse(result["ok"])


# ── Error path tests ────────────────────────────────────────────────


class ErrorPathTests(unittest.TestCase):
    def test_thaw_nonexistent_record(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=999, position=1,
                date_str="2026-02-10",
            )
            self.assertFalse(result["ok"])

    def test_thaw_position_not_in_record(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=2,
                date_str="2026-02-10",
            )
            self.assertFalse(result["ok"])

    def test_move_to_same_position_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=1,
                date_str="2026-02-10", action="move",
            )
            self.assertFalse(result["ok"])

    def test_batch_nonexistent_record_fails(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(999, 1)],
                date_str="2026-02-10", action="取出",
            )
            self.assertFalse(result["ok"])

    def test_batch_position_not_in_record_fails(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 50)],
                date_str="2026-02-10", action="取出",
            )
            self.assertFalse(result["ok"])

    def test_nonexistent_yaml_path_fails(self):
        result = tool_record_thaw(
            yaml_path="/tmp/nonexistent_test_yaml.yaml",
            record_id=1, position=1,
            date_str="2026-02-10",
        )
        self.assertFalse(result["ok"])

    def test_add_with_empty_cell_line_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            result = tool_add_entry(
                yaml_path=yp,
                box=1, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "", "short_name": "x"},
            )
            self.assertFalse(result["ok"])

    def test_add_with_empty_short_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [])
            result = tool_add_entry(
                yaml_path=yp,
                box=1, positions=[1], frozen_at="2026-02-10",
                fields={"parent_cell_line": "K562", "short_name": ""},
            )
            self.assertFalse(result["ok"])


# ── Cross-box move tests ──────────────────────────────────────────


class CrossBoxMoveTests(unittest.TestCase):
    """Tests for the to_box parameter in move operations."""

    def test_record_thaw_move_cross_box_updates_box_field(self):
        """Move with to_box should update the record's box field."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=2, positions=[5])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=5, to_position=4,
                to_box=1,
                date_str="2026-02-10", action="move",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            rec = data["inventory"][0]
            self.assertEqual(1, rec["box"])
            self.assertIn(4, rec["positions"])
            self.assertNotIn(5, rec["positions"])

    def test_record_thaw_move_cross_box_rejects_occupied_target(self):
        """Cross-box move to an occupied position should be rejected."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=2, positions=[5]),
                make_record(2, box=1, positions=[4]),
            ])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=5, to_position=4,
                to_box=1,
                date_str="2026-02-10", action="move",
            )
            self.assertFalse(result["ok"])

    def test_record_thaw_move_same_box_swap_still_works(self):
        """Same-box swap should still work after adding to_box support."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=1, positions=[2]),
            ])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=2,
                date_str="2026-02-10", action="move",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            self.assertIn(2, data["inventory"][0]["positions"])
            self.assertIn(1, data["inventory"][1]["positions"])

    def test_batch_move_cross_box_multiple_records(self):
        """Batch cross-box move using 4-tuple entries."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=2, positions=[5]),
                make_record(2, box=3, positions=[10]),
            ])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 5, 4, 1), (2, 10, 5, 1)],
                date_str="2026-02-10", action="move",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            self.assertEqual(1, data["inventory"][0]["box"])
            self.assertEqual([4], data["inventory"][0]["positions"])
            self.assertEqual(1, data["inventory"][1]["box"])
            self.assertEqual([5], data["inventory"][1]["positions"])

    def test_batch_move_cross_box_multiple_tubes(self):
        """Move multiple tubes to a new box in one batch."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [
                make_record(1, box=2, positions=[5]),
                make_record(2, box=2, positions=[6]),
                make_record(3, box=2, positions=[7]),
            ])
            result = tool_batch_thaw(
                yaml_path=yp,
                entries=[(1, 5, 1, 1), (2, 6, 2, 1), (3, 7, 3, 1)],
                date_str="2026-02-10", action="move",
            )
            self.assertTrue(result["ok"])
            data = load_yaml(yp)
            by_id = {int(rec.get("id")): rec for rec in data.get("inventory", [])}
            self.assertEqual(1, by_id[1]["box"])
            self.assertEqual([1], by_id[1]["positions"])
            self.assertEqual(1, by_id[2]["box"])
            self.assertEqual([2], by_id[2]["positions"])
            self.assertEqual(1, by_id[3]["box"])
            self.assertEqual([3], by_id[3]["positions"])

    def test_parse_batch_entries_4part_format(self):
        """parse_batch_entries should support 'id:from->to:box' format."""
        result = parse_batch_entries("4:5->4:1")
        self.assertEqual([(4, 5, 4, 1)], result)

    def test_parse_batch_entries_4part_multiple(self):
        result = parse_batch_entries("4:5->4:1,5:10->2:1")
        self.assertEqual([(4, 5, 4, 1), (5, 10, 2, 1)], result)

    def test_cross_box_move_event_records_from_and_to_box(self):
        """The thaw_event for a cross-box move should contain from_box and to_box."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=2, positions=[5])])
            tool_record_thaw(
                yaml_path=yp, record_id=1, position=5, to_position=4,
                to_box=1,
                date_str="2026-02-10", action="move",
            )
            data = load_yaml(yp)
            events = data["inventory"][0].get("thaw_events", [])
            self.assertEqual(1, len(events))
            ev = events[0]
            self.assertEqual(2, ev.get("from_box"))
            self.assertEqual(1, ev.get("to_box"))

    def test_cross_box_move_invalid_box_rejected(self):
        """Cross-box move with out-of-range to_box should be rejected."""
        with tempfile.TemporaryDirectory() as td:
            yp = _seed(td, [make_record(1, box=1, positions=[1])])
            result = tool_record_thaw(
                yaml_path=yp, record_id=1, position=1, to_position=1,
                to_box=99,
                date_str="2026-02-10", action="move",
            )
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
