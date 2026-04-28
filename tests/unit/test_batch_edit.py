"""Unit tests for batch edit execution path."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import run_plan
from lib.yaml_ops import load_yaml
from tests.managed_paths import ManagedPathTestCase


def _make_data():
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9, "box_count": 1, "box_numbers": [1]},
            "cell_line_required": False,
        },
        "inventory": [
            {"id": 1, "box": 1, "position": 1, "frozen_at": "2026-01-01", "cell_line": "A", "note": ""},
            {"id": 2, "box": 1, "position": 2, "frozen_at": "2026-01-01", "cell_line": "B", "note": ""},
            {"id": 3, "box": 1, "position": 3, "frozen_at": "2026-01-01", "cell_line": "C", "note": ""},
        ],
    }


def _edit_item(record_id, position, fields):
    return {
        "action": "edit",
        "box": 1,
        "position": position,
        "record_id": record_id,
        "label": f"edit-{record_id}",
        "source": "human",
        "payload": {
            "record_id": record_id,
            "fields": dict(fields),
        },
    }


class BatchEditTests(ManagedPathTestCase):
    def test_run_plan_batches_multiple_edits_into_one_write(self):
        yaml_path = self.ensure_dataset_yaml("batch_edit", _make_data())
        items = [
            _edit_item(1, 1, {"note": "n1"}),
            _edit_item(2, 2, {"note": "n2"}),
            _edit_item(3, 3, {"note": "n3"}),
        ]

        with patch("lib.tool_api_impl.write_batch_edit.write_yaml", wraps=__import__(
            "lib.yaml_ops",
            fromlist=["write_yaml"],
        ).write_yaml) as write_mock:
            result = run_plan(str(yaml_path), items, bridge=MagicMock(), mode="execute")

        self.assertTrue(result["ok"], result.get("summary"))
        self.assertEqual(3, result["stats"]["ok"])
        self.assertEqual(1, write_mock.call_count)

        data = load_yaml(str(yaml_path))
        notes = {rec["id"]: rec.get("note") for rec in data["inventory"]}
        self.assertEqual({1: "n1", 2: "n2", 3: "n3"}, notes)

    def test_batch_edit_is_atomic_when_one_entry_fails(self):
        yaml_path = self.ensure_dataset_yaml("batch_edit_atomic", _make_data())
        items = [
            _edit_item(1, 1, {"note": "n1"}),
            _edit_item(999, 9, {"note": "missing"}),
        ]

        with patch("lib.tool_api_impl.write_batch_edit.write_yaml") as write_mock:
            result = run_plan(str(yaml_path), items, bridge=MagicMock(), mode="execute")

        self.assertFalse(result["ok"])
        self.assertEqual(0, write_mock.call_count)

        data = load_yaml(str(yaml_path))
        notes = {rec["id"]: rec.get("note") for rec in data["inventory"]}
        self.assertEqual({1: "", 2: "", 3: ""}, notes)


if __name__ == "__main__":
    unittest.main()

