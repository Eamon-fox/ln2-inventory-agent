"""Unit tests for app_gui/plan_executor.py."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import preflight_plan, run_plan
from lib.yaml_ops import write_yaml


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def make_record(rec_id=1, box=1, positions=None, **extra):
    base = {
        "id": rec_id,
        "parent_cell_line": "K562",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }
    base.update(extra)
    return base


def make_add_item(box=1, positions=None, **extra):
    base = {
        "action": "add",
        "box": box,
        "position": (positions or [1])[0],
        "record_id": None,
        "label": "test-add",
        "source": "human",
        "payload": {
            "parent_cell_line": "K562",
            "short_name": "clone-test",
            "box": box,
            "positions": positions or [1],
            "frozen_at": "2026-02-10",
        },
    }
    base.update(extra)
    return base


def make_move_item(record_id=1, position=1, to_position=2, box=1, **extra):
    base = {
        "action": "move",
        "box": box,
        "position": position,
        "to_position": to_position,
        "record_id": record_id,
        "label": f"rec-{record_id}",
        "source": "human",
        "payload": {
            "record_id": record_id,
            "position": position,
            "to_position": to_position,
            "date_str": "2026-02-10",
            "action": "Move",
        },
    }
    base.update(extra)
    return base


def make_takeout_item(record_id=1, position=1, box=1, **extra):
    base = {
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
    base.update(extra)
    return base


class PreflightPlanTests(unittest.TestCase):
    """Tests for preflight_plan function."""

    def test_preflight_empty_plan_returns_ok(self):
        result = preflight_plan("/tmp/nonexistent.yaml", [], bridge=None)
        self.assertTrue(result["ok"])
        self.assertFalse(result["blocked"])
        self.assertEqual(0, result["stats"]["total"])

    def test_preflight_missing_yaml_returns_blocked(self):
        items = [make_add_item()]
        result = preflight_plan("/tmp/nonexistent_test_yaml_12345.yaml", items, bridge=None)
        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual("yaml_not_found", result["items"][0]["error_code"])

    def test_preflight_add_position_conflict_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[5])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_add_item(box=1, positions=[5])], bridge=bridge)

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(1, result["stats"]["blocked"])

    def test_preflight_add_valid_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_add_item(box=1, positions=[5])], bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])

    def test_preflight_does_not_modify_real_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            original_mtime = os.path.getmtime(str(yaml_path))

            import time
            time.sleep(0.1)

            bridge = MagicMock()
            preflight_plan(str(yaml_path), [make_add_item(box=2, positions=[10])], bridge=bridge)

            # Original file should not be modified by preflight
            self.assertEqual(original_mtime, os.path.getmtime(str(yaml_path)))


class RunPlanExecuteTests(unittest.TestCase):
    """Tests for run_plan in execute mode."""

    def test_run_plan_empty_returns_ok(self):
        result = run_plan("/tmp/test.yaml", [], bridge=None, mode="execute")
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["stats"]["total"])

    def test_run_plan_add_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [make_add_item(box=1, positions=[1])]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            self.assertEqual(0, result["stats"]["blocked"])
            self.assertTrue(bridge.add_entry.called)

    def test_run_plan_add_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": False, "error_code": "position_conflict", "message": "Conflict"}

            items = [make_add_item(box=1, positions=[1])]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual("position_conflict", result["items"][0]["error_code"])

    def test_run_plan_move_batch_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[2]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.batch_thaw.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_move_item(record_id=1, position=1, to_position=10),
                make_move_item(record_id=2, position=2, to_position=20),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])
            bridge.batch_thaw.assert_called_once()

    def test_run_plan_move_batch_fails_marks_all_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[2]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.batch_thaw.return_value = {"ok": False, "error_code": "validation_failed", "message": "Batch failed"}

            items = [
                make_move_item(record_id=1, position=1, to_position=10),
                make_move_item(record_id=2, position=2, to_position=20),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(2, result["stats"]["blocked"])
            bridge.batch_thaw.assert_called_once()
            self.assertFalse(bridge.record_thaw.called)
            self.assertTrue(all(it.get("error_code") == "validation_failed" for it in result["items"]))

    def test_run_plan_takeout_batch_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[2]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.batch_thaw.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_takeout_item(record_id=1, position=1),
                make_takeout_item(record_id=2, position=2),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])

    def test_run_plan_mixed_actions(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": True}
            bridge.batch_thaw.return_value = {"ok": True}

            items = [
                make_add_item(box=2, positions=[10]),
                make_move_item(record_id=1, position=1, to_position=5),
                make_takeout_item(record_id=1, position=5),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(3, result["stats"]["ok"])


class PreflightVsExecuteConsistencyTests(unittest.TestCase):
    """Tests to verify preflight and execute produce consistent results."""

    def test_preflight_and_execute_agree_on_valid_move(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.batch_thaw.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}
            bridge.record_thaw.return_value = {"ok": True}

            items = [make_move_item(record_id=1, position=1, to_position=5)]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            execute_result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertEqual(preflight_result["ok"], execute_result["ok"])
            self.assertEqual(preflight_result["blocked"], execute_result["blocked"])

    def test_preflight_and_execute_agree_on_blocked_add(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[5])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": False, "error_code": "position_conflict", "message": "Conflict"}

            items = [make_add_item(box=1, positions=[5])]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            execute_result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertEqual(preflight_result["ok"], execute_result["ok"])
            self.assertEqual(preflight_result["blocked"], execute_result["blocked"])


class MoveSwapTests(unittest.TestCase):
    """Tests for swap detection and holistic move validation."""

    def test_simple_swap_passes_validation(self):
        """A simple swap (A@9->18, B@18->9) should pass holistic validation."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(3, box=1, positions=[9]),
                    make_record(10, box=1, positions=[18]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.batch_thaw.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_move_item(record_id=3, position=9, to_position=18, box=1),
                make_move_item(record_id=10, position=18, to_position=9, box=1),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])

    def test_preflight_swap_passes(self):
        """Preflight should pass for swap operations."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[5]),
                    make_record(2, box=1, positions=[10]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()

            items = [
                make_move_item(record_id=1, position=5, to_position=10, box=1),
                make_move_item(record_id=2, position=10, to_position=5, box=1),
            ]
            result = preflight_plan(str(yaml_path), items, bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])

    def test_move_to_occupied_non_swap_blocked(self):
        """Move to occupied position (not part of swap) should be blocked."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[5]),
                    make_record(2, box=1, positions=[10]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()

            items = [
                make_move_item(record_id=1, position=5, to_position=10, box=1),
            ]
            result = preflight_plan(str(yaml_path), items, bridge=bridge)

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])


if __name__ == "__main__":
    unittest.main()
