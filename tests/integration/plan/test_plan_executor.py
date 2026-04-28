"""
Module: test_plan_executor
Layer: integration/plan
Covers: lib/plan_executor.py

计划执行引擎与操作编排的集成测试
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_executor import preflight_plan, run_plan
from app_gui.tool_bridge import GuiToolBridge
from lib.yaml_ops import load_yaml, write_yaml
from tests.managed_paths import ManagedPathTestCase


def make_data(records):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records,
    }


def _write_raw_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


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


class PreflightPlanTests(ManagedPathTestCase):
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
            _write_raw_yaml(
                str(backup_path),
                make_data([make_record(1, box=1, position=1)]),
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


class RunPlanExecuteTests(ManagedPathTestCase):
    """Tests for run_plan in execute mode."""

    def test_run_plan_empty_returns_ok(self):
        result = run_plan("/tmp/test.yaml", [], bridge=None, mode="execute")
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["stats"]["total"])

    def test_run_plan_add_success(self):
        yaml_path = self.ensure_dataset_yaml("add_success", make_data([]))

        bridge = MagicMock()

        items = [make_add_item(box=1, position=1)]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["stats"]["ok"])
        self.assertEqual(0, result["stats"]["blocked"])
        # Batch add bypasses bridge.add_entry; verify YAML was updated
        from lib.yaml_ops import load_yaml
        data = load_yaml(str(yaml_path))
        self.assertEqual(1, len(data["inventory"]))

    def test_run_plan_add_uses_single_plan_backup_for_undo_anchor(self):
        yaml_path = self.ensure_dataset_yaml("add_backup", make_data([]))

        bridge = MagicMock()

        items = [
            make_add_item(box=1, position=1),
            make_add_item(box=1, position=2),
        ]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["stats"]["ok"])
        self.assertTrue(str(result.get("backup_path") or "").strip())
        # Verify both records were written via batch
        from lib.yaml_ops import load_yaml
        data = load_yaml(str(yaml_path))
        self.assertEqual(2, len(data["inventory"]))

    def test_run_plan_add_converts_positions_for_alphanumeric_layout(self):
        yaml_path = self.ensure_dataset_yaml("add_alpha", make_data_alphanumeric([]))

        bridge = MagicMock()

        items = [make_add_item(box=1, position=5)]
        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

        self.assertTrue(result["ok"])
        # Verify the record was written with correct internal position
        from lib.yaml_ops import load_yaml
        data = load_yaml(str(yaml_path))
        self.assertEqual(1, len(data["inventory"]))
        self.assertEqual(5, data["inventory"][0]["position"])

    def test_run_plan_add_blocked(self):
        # Seed with an existing record at position 1
        yaml_path = self.ensure_dataset_yaml(
            "add_blocked",
            make_data([make_record(1, box=1, position=1)]),
        )

        bridge = MagicMock()

        items = [make_add_item(box=1, position=1)]  # conflicts with existing
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

    def test_run_plan_move_batch_passes_execute_bridge_kwargs(self):
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

            result = run_plan(
                str(yaml_path),
                [
                    make_move_item(record_id=1, position=1, to_position=3),
                    make_move_item(record_id=2, position=2, to_position=4),
                ],
                bridge=bridge,
                mode="execute",
            )

            self.assertTrue(result["ok"])
            kwargs = bridge.move.call_args.kwargs
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertTrue(str(kwargs.get("request_backup_path") or "").strip())
            self.assertNotIn("auto_backup", kwargs)
            self.assertNotIn("dry_run", kwargs)

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

    def test_run_plan_takeout_batch_passes_execute_bridge_kwargs(self):
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

            result = run_plan(
                str(yaml_path),
                [
                    make_takeout_item(record_id=1, position=1),
                    make_takeout_item(record_id=2, position=2),
                ],
                bridge=bridge,
                mode="execute",
            )

            self.assertTrue(result["ok"])
            kwargs = bridge.takeout.call_args.kwargs
            self.assertEqual(str(yaml_path), kwargs.get("yaml_path"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertTrue(str(kwargs.get("request_backup_path") or "").strip())
            self.assertNotIn("auto_backup", kwargs)
            self.assertNotIn("dry_run", kwargs)

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
            _write_raw_yaml(
                str(manual_backup),
                make_data([make_record(2, box=1, position=2)]),
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
            _write_raw_yaml(
                str(manual_backup),
                make_data([make_record(2, box=1, position=2)]),
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

    def test_run_plan_rollback_legacy_bridge_without_request_backup_path(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            manual_backup = Path(td) / "manual_backup.bak"
            _write_raw_yaml(
                str(manual_backup),
                make_data([make_record(2, box=1, position=2)]),
            )

            class _LegacyRollbackBridge:
                def __init__(self):
                    self.calls = []

                def rollback(self, yaml_path, backup_path=None, execution_mode=None, source_event=None):
                    self.calls.append(
                        {
                            "yaml_path": yaml_path,
                            "backup_path": backup_path,
                            "execution_mode": execution_mode,
                            "source_event": source_event,
                        }
                    )
                    return {"ok": True, "result": {}}

            bridge = _LegacyRollbackBridge()
            source_event = {
                "timestamp": "2026-02-12T09:00:00",
                "action": "takeout",
                "trace_id": "trace-audit-legacy",
            }
            item = make_rollback_item(str(manual_backup))
            item["payload"]["source_event"] = dict(source_event)

            result = run_plan(str(yaml_path), [item], bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(1, len(bridge.calls))
            self.assertEqual(str(yaml_path), bridge.calls[0]["yaml_path"])
            self.assertEqual(str(manual_backup), bridge.calls[0]["backup_path"])
            self.assertEqual("execute", bridge.calls[0]["execution_mode"])
            self.assertEqual(source_event, bridge.calls[0]["source_event"])

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


class PreflightVsExecuteConsistencyTests(ManagedPathTestCase):
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


class EditPlanTests(ManagedPathTestCase):
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

    def test_execute_edit_updates_record_without_gui_bridge_edit_call(self):
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=5, note="old note")]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bridge = MagicMock()
            result = run_plan(
                str(yaml_path),
                [make_edit_item(record_id=1, box=1, position=5, fields={"note": "new note"})],
                bridge=bridge,
                mode="execute",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["stats"]["ok"])
            self.assertFalse(bridge.edit_entry.called)
            current = load_yaml(str(yaml_path))
            self.assertEqual("new note", current["inventory"][0]["note"])

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
            bridge.takeout.return_value = {"ok": True}

            items = [
                make_edit_item(record_id=1, box=1, position=5, fields={"note": "edited"}),
                make_takeout_item(record_id=2, position=10),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["stats"]["ok"])
            current = load_yaml(str(yaml_path))
            self.assertEqual("edited", current["inventory"][0]["note"])
            bridge.takeout.assert_called_once()

    def test_multiple_edits_execute_atomically(self):
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

            items = [
                make_edit_item(record_id=1, box=1, position=5),
                make_edit_item(record_id=2, box=1, position=10, fields={"bad_field": "x"}),
            ]
            result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")

            self.assertFalse(result["ok"])
            self.assertEqual(0, result["stats"]["ok"])
            self.assertEqual(2, result["stats"]["blocked"])
            self.assertEqual("batch_validation_failed", result["items"][0]["error_code"])
            self.assertEqual("forbidden_fields", result["items"][1]["error_code"])


class EditPreflightExecuteConsistencyTests(ManagedPathTestCase):
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


class RunPlanExecuteRealGuiBridgeTests(ManagedPathTestCase):
    def _seed_managed_yaml(self, dataset_name, records):
        yaml_path = Path(self.ensure_dataset_yaml(dataset_name))
        write_yaml(
            make_data(records),
            path=str(yaml_path),
            audit_meta={"action": "seed", "source": "tests"},
        )
        return yaml_path

    def test_execute_edit_succeeds_with_real_gui_bridge(self):
        yaml_path = self._seed_managed_yaml(
            "real-gui-bridge-edit",
            [make_record(1, box=1, position=5, note="old note")],
        )
        bridge = GuiToolBridge(session_id="real-edit")

        result = run_plan(
            str(yaml_path),
            [make_edit_item(record_id=1, box=1, position=5, fields={"note": "new note"})],
            bridge=bridge,
            mode="execute",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["stats"]["ok"])
        current = load_yaml(str(yaml_path))
        self.assertEqual("new note", current["inventory"][0]["note"])

    def test_execute_move_succeeds_with_real_gui_bridge(self):
        yaml_path = self._seed_managed_yaml(
            "real-gui-bridge-move",
            [make_record(1, box=1, position=5)],
        )
        bridge = GuiToolBridge(session_id="real-move")

        result = run_plan(
            str(yaml_path),
            [make_move_item(record_id=1, box=1, position=5, to_position=6)],
            bridge=bridge,
            mode="execute",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["stats"]["ok"])
        current = load_yaml(str(yaml_path))
        self.assertEqual(6, current["inventory"][0]["position"])

    def test_execute_takeout_succeeds_with_real_gui_bridge(self):
        yaml_path = self._seed_managed_yaml(
            "real-gui-bridge-takeout",
            [make_record(1, box=1, position=5)],
        )
        bridge = GuiToolBridge(session_id="real-takeout")

        result = run_plan(
            str(yaml_path),
            [make_takeout_item(record_id=1, box=1, position=5)],
            bridge=bridge,
            mode="execute",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["stats"]["ok"])
        current = load_yaml(str(yaml_path))
        self.assertIsNone(current["inventory"][0]["position"])

    def test_execute_rollback_succeeds_with_real_gui_bridge(self):
        from lib import tool_api_write_adapter as _write_adapter

        yaml_path = self._seed_managed_yaml(
            "real-gui-bridge-rollback",
            [make_record(1, box=1, position=5, note="before edit")],
        )
        edit_result = _write_adapter.edit_entry(
            yaml_path=str(yaml_path),
            record_id=1,
            fields={"note": "after edit"},
            execution_mode="execute",
            source="tests",
            backup_event_source="tests",
        )
        self.assertTrue(edit_result["ok"])
        backup_path = str(edit_result.get("backup_path") or "").strip()
        self.assertTrue(backup_path)

        bridge = GuiToolBridge(session_id="real-rollback")
        result = run_plan(
            str(yaml_path),
            [make_rollback_item(backup_path)],
            bridge=bridge,
            mode="execute",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["stats"]["ok"])
        response = (result["items"][0] or {}).get("response") or {}
        restored_from = ((response.get("result") or {}).get("restored_from") or "").strip()
        self.assertEqual(backup_path, restored_from)


class MultiAddPreflightTests(ManagedPathTestCase):
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
        """In execute mode, cross-item conflict should block the conflicting item."""
        yaml_path = self.ensure_dataset_yaml("conflict_exec", make_data([]))

        bridge = MagicMock()

        items = [
            make_add_item(box=1, position=3),
            make_add_item(box=1, position=3),  # duplicate
        ]

        result = run_plan(str(yaml_path), items, bridge=bridge, mode="execute")
        self.assertTrue(result["blocked"])
        # The conflicting item should be blocked
        blocked_count = sum(1 for r in result["items"] if r.get("blocked"))
        self.assertGreaterEqual(blocked_count, 1)

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

    def test_preflight_multi_add_uses_batch_fast_path_on_success(self):
        yaml_path = self.ensure_dataset_yaml("preflight_add_fast_path", make_data([]))
        bridge = MagicMock()
        items = [
            make_add_item(box=1, position=1),
            make_add_item(box=1, position=2),
        ]

        from app_gui import plan_executor as _executor

        with patch.object(
            _executor._write_adapter,
            "batch_add_entries",
            return_value={"ok": True, "count": 2},
        ) as batch_mock, patch.object(_executor, "_preflight_add_entry") as single_mock:
            result = preflight_plan(str(yaml_path), items, bridge=bridge)

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["stats"]["ok"])
        batch_mock.assert_called_once()
        single_mock.assert_not_called()

    def test_preflight_multi_takeout_uses_batch_fast_path_on_success(self):
        yaml_path = self.ensure_dataset_yaml(
            "preflight_takeout_fast_path",
            make_data([
                make_record(1, box=1, position=1),
                make_record(2, box=1, position=2),
            ]),
        )
        bridge = MagicMock()
        items = [
            make_takeout_item(record_id=1, box=1, position=1),
            make_takeout_item(record_id=2, box=1, position=2),
        ]

        from app_gui import plan_executor as _executor

        with patch.object(
            _executor,
            "_preflight_takeout",
            return_value={"ok": True},
        ) as takeout_mock:
            result = preflight_plan(str(yaml_path), items, bridge=bridge)

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["stats"]["ok"])
        self.assertEqual(1, takeout_mock.call_count)


if __name__ == "__main__":
    unittest.main()

