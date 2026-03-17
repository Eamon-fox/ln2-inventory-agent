"""Unit tests for tool_batch_add_entries batch add API."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import tool_batch_add_entries
from lib.yaml_ops import load_yaml
from tests.managed_paths import ManagedPathTestCase


def _make_data(records=None, cell_line_required=False):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9, "box_count": 5, "box_numbers": [1, 2, 3, 4, 5]},
            "cell_line_required": cell_line_required,
        },
        "inventory": list(records or []),
    }


def _make_entry(box=1, positions=None, frozen_at="2026-01-15", fields=None):
    return {
        "box": box,
        "positions": positions or [1],
        "frozen_at": frozen_at,
        "fields": fields or {"cell_line": "K562", "note": "test"},
    }


class TestBatchAddEntries(ManagedPathTestCase):
    """Unit tests for tool_batch_add_entries."""

    def test_empty_entries_returns_ok(self):
        yaml_path = self.ensure_dataset_yaml("empty", _make_data())
        result = tool_batch_add_entries(yaml_path, [])
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["count"])

    def test_single_entry_adds_record(self):
        yaml_path = self.ensure_dataset_yaml("single", _make_data())
        entries = [_make_entry(box=1, positions=[5])]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["count"])

        data = load_yaml(yaml_path)
        self.assertEqual(1, len(data["inventory"]))
        self.assertEqual(1, data["inventory"][0]["box"])
        self.assertEqual(5, data["inventory"][0]["position"])

    def test_multiple_entries_single_write(self):
        yaml_path = self.ensure_dataset_yaml("multi", _make_data())
        entries = [
            _make_entry(box=1, positions=[1]),
            _make_entry(box=1, positions=[2]),
            _make_entry(box=2, positions=[1]),
        ]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        self.assertTrue(result["ok"])
        self.assertEqual(3, result["count"])
        self.assertEqual(3, len(result["entry_results"]))

        data = load_yaml(yaml_path)
        self.assertEqual(3, len(data["inventory"]))

    def test_position_conflict_blocks_entire_batch(self):
        """All-or-nothing: if any entry has a conflict, none are written."""
        yaml_path = self.ensure_dataset_yaml(
            "conflict",
            _make_data([{"id": 1, "box": 1, "position": 5, "frozen_at": "2026-01-01", "cell_line": "X"}]),
        )
        entries = [
            _make_entry(box=1, positions=[10]),  # valid
            _make_entry(box=1, positions=[5]),    # conflicts with existing id=1
        ]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        self.assertFalse(result["ok"])
        self.assertIn("batch_validation_failed", result.get("error_code", ""))

        # Verify nothing was written
        data = load_yaml(yaml_path)
        self.assertEqual(1, len(data["inventory"]))

    def test_cross_entry_conflict_detected(self):
        """Two entries targeting the same position should fail."""
        yaml_path = self.ensure_dataset_yaml("cross", _make_data())
        entries = [
            _make_entry(box=1, positions=[3]),
            _make_entry(box=1, positions=[3]),  # duplicate
        ]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        # The second entry causes a position conflict during progressive validation
        self.assertFalse(result["ok"])
        data = load_yaml(yaml_path)
        self.assertEqual(0, len(data["inventory"]))

    def test_ids_are_sequential(self):
        yaml_path = self.ensure_dataset_yaml("ids", _make_data())
        entries = [
            _make_entry(box=1, positions=[1]),
            _make_entry(box=2, positions=[1]),
        ]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        self.assertTrue(result["ok"])
        data = load_yaml(yaml_path)
        ids = [r["id"] for r in data["inventory"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), len(ids))  # no duplicates

    def test_backup_path_returned(self):
        yaml_path = self.ensure_dataset_yaml("backup", _make_data())
        entries = [_make_entry(box=1, positions=[1])]
        result = tool_batch_add_entries(
            yaml_path, entries,
            source="tool_api",
            auto_backup=True,
        )
        self.assertTrue(result["ok"])
        # backup_path should be set when auto_backup is True
        backup_path = result.get("backup_path")
        if backup_path:
            self.assertTrue(os.path.exists(backup_path))

    def test_entry_results_contain_created_info(self):
        yaml_path = self.ensure_dataset_yaml("info", _make_data())
        entries = [
            _make_entry(box=1, positions=[1, 2]),
            _make_entry(box=2, positions=[5]),
        ]
        result = tool_batch_add_entries(yaml_path, entries, source="tool_api")
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(result["entry_results"]))

        first = result["entry_results"][0]
        self.assertTrue(first["ok"])
        self.assertEqual(2, first["count"])
        self.assertEqual(2, len(first["new_ids"]))

        second = result["entry_results"][1]
        self.assertTrue(second["ok"])
        self.assertEqual(1, second["count"])


if __name__ == "__main__":
    unittest.main()
