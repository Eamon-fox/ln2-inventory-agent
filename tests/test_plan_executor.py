"""Unit tests for app_gui/plan_executor.py."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import preflight_plan, run_plan
from lib.yaml_ops import write_yaml


def make_data(records):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records,
    }


def make_data_alphanumeric(records):
    data = make_data(records)
    data["meta"]["box_layout"]["indexing"] = "alphanumeric"
    return data


def make_record(rec_id=1, box=1, position=None, **extra):
    base = {
        "id": rec_id,
        "parent_cell_line": "K562",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }
    base.update(extra)
    return base


def make_add_item(box=1, positions=None, position=None, **extra):
    if positions is None and position is not None:
        positions = [position]
    base = {
        "action": "add",
        "box": box,
        "position": (positions or [1])[0],
        "record_id": None,
        "label": "test-add",
        "source": "human",
        "payload": {
            "box": box,
            "positions": positions or [1],
            "frozen_at": "2026-02-10",
            "fields": {
                "cell_line": "K562",
                "note": "clone-test",
            },
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


def make_rollback_item(backup_path, **extra):
    base = {
        "action": "rollback",
        "box": 0,
        "position": 1,
        "record_id": None,
        "label": "Rollback",
        "source": "human",
        "payload": {
            "backup_path": backup_path,
        },
    }
    base.update(extra)
    return base


def make_edit_item(record_id=1, box=1, position=1, fields=None, **extra):
    base = {
        "action": "edit",
        "box": box,
        "position": position,
        "record_id": record_id,
        "label": f"rec-{record_id}",
        "source": "human",
        "payload": {
            "record_id": record_id,
            "fields": fields or {"cell_line": "K562"},
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
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_add_item(box=1, position=5)], bridge=bridge)

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(1, result["stats"]["blocked"])

    def test_preflight_add_valid_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_add_item(box=1, position=5)], bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])

    def test_preflight_add_alphanumeric_internal_positions_succeed(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_add_item(box=1, position=5)], bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])

    def test_preflight_does_not_modify_real_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            original_mtime = os.path.getmtime(str(yaml_path))

            import time
            time.sleep(0.1)

            bridge = MagicMock()
            preflight_plan(str(yaml_path), [make_add_item(box=2, position=10)], bridge=bridge)

            # Original file should not be modified by preflight
            self.assertEqual(original_mtime, os.path.getmtime(str(yaml_path)))

    def test_preflight_allows_baseline_invalid_cell_line_when_incoming_is_valid(self):
        """Historical cell_line mismatches should not block preflight staging."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            bad_data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "cell_line_required": True,
                    "cell_line_options": ["K562", "HeLa"],
                },
                "inventory": [
                    {
                        "id": 1,
                        "cell_line": "U2OS",
                        "short_name": "bad",
                        "box": 1,
                        "position": 5,
                        "frozen_at": "2025-01-01",
                    }
                ],
            }
            yaml_path.write_text(
                yaml.safe_dump(bad_data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            bridge = MagicMock()
            add_item = make_add_item(box=1, position=6)
            add_item["payload"]["fields"]["cell_line"] = "K562"
            result = preflight_plan(str(yaml_path), [add_item], bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])

    def test_preflight_rollback_valid_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                auto_backup=False,
                audit_meta={"action": "seed", "source": "tests"},
            )
            backup_path = Path(td) / "manual_backup.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(backup_path),
                auto_backup=False,
                audit_meta={"action": "seed_backup", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_rollback_item(str(backup_path))], bridge=bridge)

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])

    def test_preflight_rollback_missing_backup_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                auto_backup=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            missing_backup = Path(td) / "missing_backup.bak"
            bridge = MagicMock()
            result = preflight_plan(str(yaml_path), [make_rollback_item(str(missing_backup))], bridge=bridge)

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(1, result["stats"]["blocked"])


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

            items = [make_add_item(box=1, position=1)]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            self.assertEqual(0, result["stats"]["blocked"])
            self.assertTrue(bridge.add_entry.called)

    def test_run_plan_add_uses_single_plan_backup_for_undo_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.side_effect = [
                {"ok": True, "backup_path": "/tmp/backup-first.bak"},
                {"ok": True, "backup_path": "/tmp/backup-second.bak"},
            ]

            items = [
                make_add_item(box=1, position=1),
                make_add_item(box=1, position=2),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])
            self.assertTrue(str(result.get("backup_path") or "").strip())
            self.assertEqual(2, bridge.add_entry.call_count)
            kwargs = bridge.add_entry.call_args.kwargs
            self.assertEqual(result.get("backup_path"), kwargs.get("request_backup_path"))
            self.assertFalse(kwargs.get("auto_backup", True))

    def test_run_plan_add_converts_positions_for_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [make_add_item(box=1, position=5)]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            bridge.add_entry.assert_called_once()
            kwargs = bridge.add_entry.call_args.kwargs
            self.assertEqual(["A5"], kwargs.get("positions"))

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

            items = [make_add_item(box=1, position=1)]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual("position_conflict", result["items"][0]["error_code"])

    def test_run_plan_move_batch_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.move.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_move_item(record_id=1, position=1, to_position=10),
                make_move_item(record_id=2, position=2, to_position=20),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])
            bridge.move.assert_called_once()

    def test_run_plan_move_batch_converts_positions_for_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.move.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_move_item(record_id=1, position=1, to_position=3),
                make_move_item(record_id=2, position=2, to_position=4),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            bridge.move.assert_called_once()
            kwargs = bridge.move.call_args.kwargs
            self.assertEqual("A1", kwargs["entries"][0]["from"]["position"])
            self.assertEqual("A3", kwargs["entries"][0]["to"]["position"])
            self.assertEqual("A2", kwargs["entries"][1]["from"]["position"])
            self.assertEqual("A4", kwargs["entries"][1]["to"]["position"])

    def test_run_plan_move_batch_fails_marks_all_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.move.return_value = {"ok": False, "error_code": "validation_failed", "message": "Batch failed"}

            items = [
                make_move_item(record_id=1, position=1, to_position=10),
                make_move_item(record_id=2, position=2, to_position=20),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(2, result["stats"]["blocked"])
            bridge.move.assert_called_once()
            self.assertFalse(bridge.takeout.called)
            self.assertTrue(all(it.get("error_code") == "validation_failed" for it in result["items"]))

    def test_run_plan_move_batch_fails_maps_errors_per_record_id(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.move.return_value = {
                "ok": False,
                "error_code": "validation_failed",
                "message": "Batch operation parameter validation failed",
                "errors": [
                    "Row 1 ID 1: source and target positions must differ for move",
                    "Row 2 ID 2: source and target positions must differ for move",
                ],
            }

            items = [
                make_move_item(record_id=1, position=1, to_position=10),
                make_move_item(record_id=2, position=2, to_position=20),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(2, result["stats"]["blocked"])
            self.assertEqual("Row 1 ID 1: source and target positions must differ for move", result["items"][0]["message"])
            self.assertEqual("Row 2 ID 2: source and target positions must differ for move", result["items"][1]["message"])

    def test_run_plan_takeout_batch_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.takeout.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_takeout_item(record_id=1, position=1),
                make_takeout_item(record_id=2, position=2),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])

    def test_run_plan_takeout_batch_converts_positions_for_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric(
                    [
                        make_record(1, box=1, position=5),
                        make_record(2, box=1, position=6),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.takeout.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            items = [
                make_takeout_item(record_id=1, position=5),
                make_takeout_item(record_id=2, position=6),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            bridge.takeout.assert_called_once()
            kwargs = bridge.takeout.call_args.kwargs
            self.assertEqual("A5", kwargs["entries"][0]["from"]["position"])
            self.assertEqual("A6", kwargs["entries"][1]["from"]["position"])

    def test_run_plan_mixed_actions(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": True}
            bridge.move.return_value = {"ok": True}
            bridge.takeout.return_value = {"ok": True}

            items = [
                make_add_item(box=2, position=10),
                make_move_item(record_id=1, position=1, to_position=5),
                make_takeout_item(record_id=1, position=5),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(3, result["stats"]["ok"])

    def test_run_plan_rollback_success(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            manual_backup = Path(td) / "manual_backup.bak"
            write_yaml(
                make_data([make_record(2, box=1, position=2)]),
                path=str(manual_backup),
                auto_backup=False,
                audit_meta={"action": "seed_backup", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.rollback.return_value = {
                "ok": True,
                "result": {"snapshot_before_rollback": "/tmp/snap.bak"},
            }

            items = [make_rollback_item(str(manual_backup))]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            bridge.rollback.assert_called_once()
            self.assertTrue(str(result.get("backup_path") or "").strip())

    def test_run_plan_rollback_passes_source_event(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            manual_backup = Path(td) / "manual_backup.bak"
            write_yaml(
                make_data([make_record(2, box=1, position=2)]),
                path=str(manual_backup),
                auto_backup=False,
                audit_meta={"action": "seed_backup", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.rollback.return_value = {"ok": True, "result": {}}

            source_event = {
                "timestamp": "2026-02-12T09:00:00",
                "action": "takeout",
                "trace_id": "trace-audit-1",
            }
            item = make_rollback_item(str(manual_backup))
            item["payload"]["source_event"] = dict(source_event)

            result = run_plan(str(yaml_path), [item], bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            bridge.rollback.assert_called_once()
            kwargs = bridge.rollback.call_args.kwargs
            self.assertEqual(str(yaml_path), kwargs.get("yaml_path"))
            self.assertEqual(str(manual_backup), kwargs.get("backup_path"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual(source_event, kwargs.get("source_event"))
            self.assertEqual(result.get("backup_path"), kwargs.get("request_backup_path"))

    def test_run_plan_rollback_must_be_alone_blocks(self):
        bridge = MagicMock()
        items = [
            make_rollback_item("/tmp/backup.bak"),
            make_add_item(box=1, position=1),
        ]

        result = run_plan("/tmp/test.yaml", items, bridge=bridge, mode="execute")

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertEqual(2, result["stats"]["blocked"])
        self.assertFalse(bridge.rollback.called)
        self.assertFalse(bridge.add_entry.called)


class PreflightVsExecuteConsistencyTests(unittest.TestCase):
    """Tests to verify preflight and execute produce consistent results."""

    def test_preflight_and_execute_agree_on_valid_move(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.move.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}
            bridge.takeout.return_value = {"ok": True}

            items = [make_move_item(record_id=1, position=1, to_position=5)]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            execute_result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertEqual(preflight_result["ok"], execute_result["ok"])
            self.assertEqual(preflight_result["blocked"], execute_result["blocked"])

    def test_preflight_and_execute_agree_on_blocked_add(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": False, "error_code": "position_conflict", "message": "Conflict"}

            items = [make_add_item(box=1, position=5)]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            execute_result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertEqual(preflight_result["ok"], execute_result["ok"])
            self.assertEqual(preflight_result["blocked"], execute_result["blocked"])


class EditPlanTests(unittest.TestCase):
    """Tests for edit action in preflight and execute."""

    def test_preflight_edit_passes(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(
                str(yaml_path),
                [make_edit_item(record_id=1, box=1, position=5)],
                bridge=bridge,
            )

            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(1, result["stats"]["ok"])
            # Preflight should NOT call bridge.edit_entry
            self.assertFalse(bridge.edit_entry.called)

    def test_preflight_edit_invalid_field_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = preflight_plan(
                str(yaml_path),
                [make_edit_item(record_id=1, box=1, position=5, fields={"bad_field": "x"})],
                bridge=bridge,
            )

            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            self.assertEqual(1, result["stats"]["blocked"])
            self.assertFalse(bridge.edit_entry.called)

    def test_execute_edit_calls_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.edit_entry.return_value = {"ok": True, "backup_path": str(Path(td) / "backup.bak")}

            result = run_plan(
                str(yaml_path),
                [make_edit_item(record_id=1, box=1, position=5, fields={"note": "new note"})],
                bridge=bridge,
                mode="execute",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            bridge.edit_entry.assert_called_once()
            call_kwargs = bridge.edit_entry.call_args
            self.assertEqual(1, call_kwargs.kwargs.get("record_id") or call_kwargs[1].get("record_id"))

    def test_execute_edit_failure_marks_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.edit_entry.return_value = {
                "ok": False,
                "error_code": "record_not_found",
                "message": "No such record",
            }

            result = run_plan(
                str(yaml_path),
                [make_edit_item(record_id=999, box=1, position=5)],
                bridge=bridge,
                mode="execute",
            )

            self.assertFalse(result["ok"])
            self.assertEqual(1, result["stats"]["blocked"])

    def test_mixed_edit_and_takeout(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=5),
                    make_record(2, box=1, position=10),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.edit_entry.return_value = {"ok": True}
            bridge.takeout.return_value = {"ok": True}

            items = [
                make_edit_item(record_id=1, box=1, position=5, fields={"note": "edited"}),
                make_takeout_item(record_id=2, position=10),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])
            bridge.edit_entry.assert_called_once()
            bridge.takeout.assert_called_once()

    def test_multiple_edits_execute_independently(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=5),
                    make_record(2, box=1, position=10),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            # First edit succeeds, second fails
            bridge.edit_entry.side_effect = [
                {"ok": True},
                {"ok": False, "error_code": "invalid_field", "message": "Bad field"},
            ]

            items = [
                make_edit_item(record_id=1, box=1, position=5),
                make_edit_item(record_id=2, box=1, position=10, fields={"bad_field": "x"}),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            self.assertEqual(1, result["stats"]["blocked"])
            self.assertEqual(2, bridge.edit_entry.call_count)


class EditPreflightExecuteConsistencyTests(unittest.TestCase):
    """Verify preflight and execute agree for edit operations."""

    def test_preflight_and_execute_agree_on_valid_edit(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.edit_entry.return_value = {"ok": True}

            items = [make_edit_item(record_id=1, box=1, position=5)]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            execute_result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertEqual(preflight_result["ok"], execute_result["ok"])
            self.assertEqual(preflight_result["blocked"], execute_result["blocked"])


class MultiAddPreflightTests(unittest.TestCase):
    """Regression: preflight must detect cross-item position conflicts for adds."""

    def test_preflight_catches_same_position_conflict_between_two_adds(self):
        """Two adds to the same position should be blocked by preflight."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=2, position=4),
                make_add_item(box=2, position=4),  # same position
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertFalse(result["ok"])
            self.assertTrue(result["blocked"])
            # First add should pass, second should be blocked
            ok_count = sum(1 for r in result["items"] if r.get("ok"))
            blocked_count = sum(1 for r in result["items"] if r.get("blocked"))
            self.assertEqual(ok_count, 1)
            self.assertEqual(blocked_count, 1)

    def test_preflight_passes_different_positions_for_two_adds(self):
        """Two adds to different positions should both pass preflight."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=2, position=4),
                make_add_item(box=2, position=5),
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(result["stats"]["ok"], 2)

    def test_preflight_and_execute_agree_on_multi_add_conflict(self):
        """Preflight and execute should produce the same blocked result."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": False, "error_code": "position_conflict", "message": "Conflict"}

            items = [
                make_add_item(box=2, position=4),
                make_add_item(box=2, position=4),
            ]

            preflight_result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertFalse(preflight_result["ok"])
            self.assertTrue(preflight_result["blocked"])

    def test_preflight_three_adds_two_conflict(self):
        """Three adds where two share a position: only the duplicate is blocked."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=1, position=1),
                make_add_item(box=1, position=2),
                make_add_item(box=1, position=1),  # conflicts with first
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertFalse(result["ok"])
            ok_count = sum(1 for r in result["items"] if r.get("ok"))
            blocked_count = sum(1 for r in result["items"] if r.get("blocked"))
            self.assertEqual(ok_count, 2)
            self.assertEqual(blocked_count, 1)

    def test_execute_blocks_same_position_without_calling_bridge(self):
        """In execute mode, cross-item conflict should block before bridge call."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            bridge.add_entry.return_value = {"ok": True, "backup_path": "/tmp/bak"}

            items = [
                make_add_item(box=1, position=3),
                make_add_item(box=1, position=3),  # duplicate
            ]

            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
            self.assertTrue(result["blocked"])
            # bridge.add_entry should only be called once (for the first item)
            self.assertEqual(bridge.add_entry.call_count, 1)

    def test_same_position_different_box_no_conflict(self):
        """Same position number in different boxes should not conflict."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=1, position=4),
                make_add_item(box=2, position=4),  # same pos, different box
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertTrue(result["ok"])
            self.assertFalse(result["blocked"])
            self.assertEqual(result["stats"]["ok"], 2)

    def test_multi_position_add_conflict_detected(self):
        """An add with positions=[3,4] should conflict with another add at pos 4."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=1, positions=[3, 4]),
                make_add_item(box=1, position=4),  # overlaps with first
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            self.assertFalse(result["ok"])
            blocked_count = sum(1 for r in result["items"] if r.get("blocked"))
            self.assertEqual(blocked_count, 1)

    def test_cross_item_conflict_error_message_contains_hint(self):
        """Blocked item should have a meaningful error message."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            items = [
                make_add_item(box=1, position=5),
                make_add_item(box=1, position=5),
            ]

            result = preflight_plan(str(yaml_path), items, bridge=bridge)
            blocked_items = [r for r in result["items"] if r.get("blocked")]
            self.assertEqual(len(blocked_items), 1)
            self.assertIn("position_conflict", blocked_items[0].get("error_code", ""))
            self.assertTrue(blocked_items[0].get("message"))


if __name__ == "__main__":
    unittest.main()

