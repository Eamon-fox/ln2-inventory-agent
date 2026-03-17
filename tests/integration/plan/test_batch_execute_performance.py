"""Integration tests for batch plan execution performance and correctness.

Verifies that 100+ add operations execute efficiently via the batch
optimization in plan_executor, and that the final YAML state is correct.
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import preflight_plan, run_plan
from lib.yaml_ops import load_yaml, write_yaml
from tests.managed_paths import ManagedPathTestCase


def _make_data(records=None):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9, "box_count": 5, "box_numbers": [1, 2, 3, 4, 5]},
            "cell_line_required": False,
        },
        "inventory": list(records or []),
    }


def _make_add_item(box, position, frozen_at="2026-02-10"):
    return {
        "action": "add",
        "box": box,
        "position": position,
        "record_id": None,
        "label": f"test-add-{box}-{position}",
        "source": "human",
        "payload": {
            "box": box,
            "positions": [position],
            "frozen_at": frozen_at,
            "fields": {
                "cell_line": "K562",
                "note": f"batch-test-{box}-{position}",
            },
        },
    }


def _make_takeout_item(record_id, box, position):
    return {
        "action": "takeout",
        "box": box,
        "position": position,
        "record_id": record_id,
        "label": f"rec-{record_id}",
        "source": "human",
        "payload": {
            "record_id": record_id,
            "position": position,
            "date_str": "2026-02-10",
            "action": "Takeout",
        },
    }


class TestBatchExecutePerformance(ManagedPathTestCase):
    """Performance and correctness tests for 100+ batch operations."""

    def test_100_adds_execute_under_5_seconds(self):
        """100 add operations should execute in well under 5 seconds."""
        yaml_path = self.ensure_dataset_yaml("perf_100", _make_data())
        bridge = MagicMock()

        # Generate 100 adds across boxes 1-5, 20 per box
        items = []
        for box in range(1, 6):
            for pos in range(1, 21):
                items.append(_make_add_item(box=box, position=pos))

        start = time.monotonic()
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
        elapsed = time.monotonic() - start

        self.assertTrue(result["ok"], f"Batch execution failed: {result.get('summary')}")
        self.assertEqual(100, result["stats"]["ok"])
        self.assertEqual(0, result["stats"]["blocked"])

        # Verify all records were written correctly
        data = load_yaml(str(yaml_path))
        self.assertEqual(100, len(data["inventory"]))

        # Performance assertion: should be well under 5 seconds
        self.assertLess(elapsed, 5.0, f"Batch execution took {elapsed:.2f}s, expected < 5s")

    def test_200_adds_execute_under_10_seconds(self):
        """200 add operations should execute in well under 10 seconds."""
        yaml_path = self.ensure_dataset_yaml("perf_200", _make_data())
        bridge = MagicMock()

        items = []
        for box in range(1, 6):
            for pos in range(1, 41):
                items.append(_make_add_item(box=box, position=pos))

        start = time.monotonic()
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
        elapsed = time.monotonic() - start

        self.assertTrue(result["ok"])
        self.assertEqual(200, result["stats"]["ok"])

        data = load_yaml(str(yaml_path))
        self.assertEqual(200, len(data["inventory"]))

        self.assertLess(elapsed, 10.0, f"Batch execution took {elapsed:.2f}s, expected < 10s")

    def test_batch_add_atomicity_on_conflict(self):
        """If any add in the batch fails validation, none should be written."""
        # Position 5 is already occupied
        yaml_path = self.ensure_dataset_yaml(
            "atomic",
            _make_data([{"id": 1, "box": 1, "position": 5, "frozen_at": "2026-01-01", "cell_line": "X"}]),
        )
        bridge = MagicMock()

        items = [
            _make_add_item(box=1, position=10),  # valid
            _make_add_item(box=1, position=20),  # valid
            _make_add_item(box=1, position=5),   # conflicts with existing
        ]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        self.assertFalse(result["ok"])
        # Original data should be unchanged
        data = load_yaml(str(yaml_path))
        self.assertEqual(1, len(data["inventory"]))
        self.assertEqual(1, data["inventory"][0]["id"])

    def test_batch_records_have_unique_sequential_ids(self):
        """All records created in a batch should have unique, sequential IDs."""
        yaml_path = self.ensure_dataset_yaml("ids", _make_data())
        bridge = MagicMock()

        items = []
        for pos in range(1, 51):
            items.append(_make_add_item(box=1, position=pos))

        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
        self.assertTrue(result["ok"])

        data = load_yaml(str(yaml_path))
        ids = [r["id"] for r in data["inventory"]]
        self.assertEqual(50, len(ids))
        self.assertEqual(len(set(ids)), len(ids), "IDs must be unique")
        self.assertEqual(ids, sorted(ids), "IDs should be sequential")

    def test_batch_produces_audit_events(self):
        """Batch execution should produce audit events for traceability."""
        yaml_path = self.ensure_dataset_yaml("audit", _make_data())
        bridge = MagicMock()

        items = [
            _make_add_item(box=1, position=1),
            _make_add_item(box=1, position=2),
            _make_add_item(box=1, position=3),
        ]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
        self.assertTrue(result["ok"])

        from lib.yaml_ops import read_audit_events
        events = read_audit_events(str(yaml_path))
        # Should have at least the add_entry events
        add_events = [e for e in events if e.get("action") == "add_entry"]
        self.assertGreaterEqual(len(add_events), 1, "At least one audit event for add_entry expected")

    def test_mixed_adds_and_takeouts_batch(self):
        """Mixed operations: batch adds + batch takeouts in a single plan."""
        # Seed with records to take out
        records = [
            {"id": i, "box": 1, "position": i, "frozen_at": "2026-01-01", "cell_line": "K562"}
            for i in range(1, 6)
        ]
        yaml_path = self.ensure_dataset_yaml("mixed", _make_data(records))
        bridge = MagicMock()
        bridge.takeout.return_value = {"ok": True}

        # 50 adds (box 2) + 5 takeouts (box 1)
        items = []
        for pos in range(1, 51):
            items.append(_make_add_item(box=2, position=pos))
        for i in range(1, 6):
            items.append(_make_takeout_item(record_id=i, box=1, position=i))

        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        # Adds should succeed
        add_results = [r for r in result["items"] if r.get("item", {}).get("action") == "add"]
        ok_adds = sum(1 for r in add_results if r.get("ok"))
        self.assertEqual(50, ok_adds)

    def test_preflight_100_adds_validates_all(self):
        """Preflight mode should validate all 100 items individually."""
        yaml_path = self.ensure_dataset_yaml("preflight_100", _make_data())
        bridge = MagicMock()

        items = []
        for box in range(1, 6):
            for pos in range(1, 21):
                items.append(_make_add_item(box=box, position=pos))

        result = preflight_plan(str(yaml_path), items, bridge=bridge)

        self.assertTrue(result["ok"])
        self.assertEqual(100, result["stats"]["ok"])
        self.assertEqual(0, result["stats"]["blocked"])

    def test_cross_item_conflict_in_batch(self):
        """Two items targeting the same position should be detected."""
        yaml_path = self.ensure_dataset_yaml("cross_conflict", _make_data())
        bridge = MagicMock()

        items = [
            _make_add_item(box=1, position=1),
            _make_add_item(box=1, position=1),  # duplicate
            _make_add_item(box=1, position=2),  # valid
        ]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        self.assertTrue(result["blocked"])
        # Nothing should have been written (atomic)
        blocked_count = sum(1 for r in result["items"] if r.get("blocked"))
        self.assertGreaterEqual(blocked_count, 1)


if __name__ == "__main__":
    unittest.main()
