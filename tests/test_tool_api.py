import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    build_actor_context,
    tool_add_entry,
    tool_adjust_box_count,
    tool_collect_timeline,
    tool_edit_entry,
    tool_export_inventory_csv,
    tool_move,
    tool_rollback,
    tool_set_box_tag,
    tool_takeout,
)
from lib.tool_api import (
    tool_get_raw_entries,
    tool_list_audit_timeline,
    tool_query_takeout_events,
    tool_recommend_positions,
    tool_search_records,
    tool_generate_stats,
    tool_list_empty_positions,
)
from lib.tool_api_write_validation import resolve_request_backup_path
from lib.yaml_ops import (
    create_yaml_backup,
    get_audit_log_path,
    load_yaml,
    read_audit_events,
    write_yaml,
)


def tool_batch_takeout(*args, **kwargs):
    return tool_takeout(*args, **kwargs)


def tool_batch_move(*args, **kwargs):
    return tool_move(*args, **kwargs)


def _flatten_single_preview(response):
    if not isinstance(response, dict):
        return response
    preview = response.get("preview")
    if not isinstance(preview, dict):
        return response
    operations = preview.get("operations")
    if not isinstance(operations, list) or len(operations) != 1:
        return response
    op = operations[0]
    if not isinstance(op, dict):
        return response
    flat_preview = dict(preview)
    for key in (
        "record_id",
        "cell_line",
        "short_name",
        "box",
        "position",
        "old_position",
        "new_position",
        "to_position",
        "swap_with_record_id",
    ):
        if key in op:
            flat_preview[key] = op.get(key)
    if "old_position" in op and "position_before" not in flat_preview:
        flat_preview["position_before"] = op.get("old_position")
    if "new_position" in op and "position_after" not in flat_preview:
        flat_preview["position_after"] = op.get("new_position")
    normalized = dict(response)
    normalized["preview"] = flat_preview
    return normalized


def tool_record_takeout(
    yaml_path,
    record_id,
    from_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    response = tool_takeout(
        yaml_path=yaml_path,
        entries=[{"record_id": record_id, "from": from_slot}],
        date_str=date_str,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _flatten_single_preview(response)


def tool_record_move(
    yaml_path,
    record_id,
    from_slot,
    to_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    response = tool_move(
        yaml_path=yaml_path,
        entries=[{"record_id": record_id, "from": from_slot, "to": to_slot}],
        date_str=date_str,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _flatten_single_preview(response)


def make_record(rec_id=1, box=1, position=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records,
    }


def slot(box, position):
    return {"box": box, "position": position}


def takeout_entry(record_id, box, position):
    return {"record_id": record_id, "from": slot(box, position)}


def move_entry(record_id, from_box, from_position, to_box, to_position):
    return {
        "record_id": record_id,
        "from": slot(from_box, from_position),
        "to": slot(to_box, to_position),
    }


def write_raw_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def read_audit_rows(temp_dir):
    yaml_path = Path(temp_dir) / "inventory.yaml"
    if not yaml_path.exists():
        return []
    return read_audit_events(str(yaml_path))


class ToolApiTests(unittest.TestCase):
    def test_resolve_request_backup_path_appends_backup_audit_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_request_backup_event_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            request_backup = resolve_request_backup_path(
                yaml_path=str(yaml_path),
                execution_mode="execute",
                dry_run=False,
                request_backup_path=None,
                backup_event_source="tests.request_backup",
            )
            self.assertTrue(Path(request_backup).exists())

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("backup", last.get("action"))
            self.assertEqual(str(Path(request_backup).resolve()), str(Path(last.get("backup_path")).resolve()))
            self.assertGreater(int(last.get("audit_seq") or 0), 0)

    def test_tool_add_entry_writes_trace_session_metadata(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            actor = build_actor_context(
                session_id="sess-test",
                trace_id="trace-test",
            )
            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2, 3],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562", "note": "from test"},
                actor_context=actor,
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["new_id"])
            self.assertEqual([2, 3], result["result"]["new_ids"])

            current = load_yaml(str(yaml_path))
            # Tube-level model: positions [2,3] creates 2 new tube records.
            self.assertEqual(3, len(current["inventory"]))

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            lines = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last = lines[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("tool_add_entry", last["tool_name"])
            self.assertEqual("sess-test", last["session_id"])
            self.assertEqual("trace-test", last["trace_id"])
            self.assertNotIn("actor_type", last)
            self.assertNotIn("actor_id", last)
            self.assertNotIn("channel", last)

    def test_tool_record_takeout_dry_run_no_write(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                dry_run=True,
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(lines))

    def test_tool_record_takeout_blocks_agent_write_without_execute_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_gate_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            blocked = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                source="agent.react",
            )

            self.assertFalse(blocked["ok"])
            self.assertEqual("write_requires_execute_mode", blocked["error_code"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

            allowed = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                source="agent.react",
                execution_mode="execute",
                request_backup_path=str(create_yaml_backup(str(yaml_path))),
            )
            self.assertTrue(allowed["ok"])

    def test_tool_batch_takeout_updates_multiple_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_batch_takeout(
                yaml_path=str(yaml_path),
                entries=[
                    takeout_entry(1, 1, 1),
                    takeout_entry(2, 1, 2),
                ],
                date_str="2026-02-10",
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["count"])

            current = load_yaml(str(yaml_path))
            self.assertIsNone(current["inventory"][0]["position"])
            self.assertIsNone(current["inventory"][1]["position"])

    def test_tool_batch_takeout_same_record_duplicate_entry_rejected(self):
        """Tube-level model: batching the same tube twice should be rejected."""
        with tempfile.TemporaryDirectory(prefix="ln2_tool_batch_same_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [make_record(1, box=5, position=33)]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_batch_takeout(
                yaml_path=str(yaml_path),
                entries=[
                    takeout_entry(1, 5, 33),
                    takeout_entry(1, 5, 33),
                ],
                date_str="2026-02-10",
                source="tests/test_tool_api.py",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result.get("error_code"))

    def test_legacy_actions_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_takeout_canon_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            with self.assertRaises(TypeError):
                tool_record_takeout(
                    yaml_path=str(yaml_path),
                    record_id=1,
                    from_slot=slot(1, 1),
                    date_str="2026-02-10",
                    action="Thaw",
                    source="tests/test_tool_api.py",
                )

            with self.assertRaises(TypeError):
                tool_batch_takeout(
                    yaml_path=str(yaml_path),
                    entries=[takeout_entry(2, 1, 2)],
                    date_str="2026-02-10",
                    action="Discard",
                    source="tests/test_tool_api.py",
                )

            data = load_yaml(str(yaml_path))
            self.assertEqual([], data["inventory"][0].get("thaw_events") or [])
            self.assertEqual([], data["inventory"][1].get("thaw_events") or [])

    def test_tool_record_takeout_move_updates_positions_and_appends_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 3),
                date_str="2026-02-10",
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual("3", result["preview"]["to_position"])
            self.assertEqual("1", result["preview"]["position_before"])
            self.assertEqual("3", result["preview"]["position_after"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(3, current["inventory"][0]["position"])
            events = current["inventory"][0].get("thaw_events") or []
            self.assertEqual(1, len(events))
            self.assertEqual("move", events[-1].get("action"))
            self.assertEqual([1], events[-1].get("positions"))
            self.assertEqual(1, events[-1].get("from_position"))
            self.assertEqual(3, events[-1].get("to_position"))
            self.assertNotIn("note", events[-1])

    def test_tool_record_takeout_move_swaps_with_occupied_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_swap_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 2),
                date_str="2026-02-10",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["preview"].get("swap_with_record_id"))

            current = load_yaml(str(yaml_path))
            self.assertEqual(2, current["inventory"][0]["position"])
            self.assertEqual(1, current["inventory"][1]["position"])

            source_events = current["inventory"][0].get("thaw_events") or []
            swap_events = current["inventory"][1].get("thaw_events") or []
            self.assertEqual(1, len(source_events))
            self.assertEqual(1, len(swap_events))
            self.assertEqual(2, source_events[-1].get("to_position"))
            self.assertEqual(1, swap_events[-1].get("to_position"))

    def test_tool_record_takeout_move_requires_to_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_require_to_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            with self.assertRaises(TypeError):
                tool_record_move(
                    yaml_path=str(yaml_path),
                    record_id=1,
                    from_slot=slot(1, 1),
                    date_str="2026-02-10",
                )

    def test_tool_batch_takeout_move_updates_positions_and_swaps(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        make_record(3, box=1, position=3),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[
                    move_entry(1, 1, 1, 1, 2),
                    move_entry(3, 1, 3, 1, 4),
                ],
                date_str="2026-02-10",
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual(2, result["result"]["count"])
            self.assertEqual([1, 2, 3], result["result"]["affected_record_ids"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(2, current["inventory"][0]["position"])
            self.assertEqual(1, current["inventory"][1]["position"])
            self.assertEqual(4, current["inventory"][2]["position"])

            self.assertEqual(1, len(current["inventory"][0].get("thaw_events") or []))
            self.assertEqual(1, len(current["inventory"][1].get("thaw_events") or []))
            self.assertEqual(1, len(current["inventory"][2].get("thaw_events") or []))

    def test_tool_batch_takeout_move_rejects_non_move_entry_shape(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_shape_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[{"record_id": 1, "from": slot(1, 1)}],
                date_str="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])

    def test_tool_batch_takeout_move_rejects_duplicate_targets_in_batch(self):
        """Regression: multiple moves to same target position should be rejected."""
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_dup_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(8, box=3, position=3),
                        make_record(7, box=3, position=2),
                        make_record(6, box=3, position=1),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[
                    move_entry(8, 3, 3, 3, 4),
                    move_entry(7, 3, 2, 3, 3),
                    move_entry(6, 3, 1, 3, 3),
                ],
                date_str="2026-02-14",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])
            self.assertTrue(
                any("already been moved in this request" in err for err in result.get("errors", []))
            )

    def test_tool_add_entry_rejects_duplicate_ids_in_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_dup_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(1, box=1, position=2),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[3],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("Duplicate ID" in err for err in result.get("errors", [])))

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 1)
            matched = [row for row in rows if row.get("action") == "add_entry" and row.get("status") == "failed"]
            self.assertTrue(matched)
            last = matched[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("integrity_validation_failed", (last.get("error") or {}).get("error_code"))

    def test_tool_add_entry_invalid_date_writes_failed_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_date_audit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("invalid_date", result["error_code"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("invalid_date", (last.get("error") or {}).get("error_code"))

    def test_tool_record_takeout_rejects_malformed_thaw_events(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_events_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            broken = make_record(1, box=1, position=1)
            broken["thaw_events"] = "broken"
            write_raw_yaml(yaml_path, make_data([broken]))

            result = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("thaw_events" in err for err in result.get("errors", [])))

    def test_tool_add_entry_rejects_invalid_date_box_and_positions(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_invalid_args_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            bad_date = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                fields={"cell_line": "K562"},
            )
            self.assertFalse(bad_date["ok"])
            self.assertEqual("invalid_date", bad_date["error_code"])

            bad_box = tool_add_entry(
                yaml_path=str(yaml_path),
                box=99,
                positions=[2],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )
            self.assertFalse(bad_box["ok"])
            self.assertEqual("invalid_box", bad_box["error_code"])

            bad_pos = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 999),
                date_str="2026-02-10",
            )
            self.assertFalse(bad_pos["ok"])
            self.assertEqual("validation_failed", bad_pos["error_code"])

    def test_tool_add_entry_rejects_existing_position_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_conflict_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, position=10),
                        make_record(2, box=1, position=10),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[11],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("Position conflict" in err for err in result.get("errors", [])))

    def test_tool_rollback_blocks_invalid_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_rollback_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            good = make_data([make_record(1, box=1, position=1)])
            write_yaml(good, path=str(yaml_path))

            bad_backup = Path(temp_dir) / "manual_invalid_backup.yaml"
            bad_payload = make_data([make_record(1, box=99, position=1)])
            write_raw_yaml(bad_backup, bad_payload)

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(bad_backup),
            )

            self.assertFalse(result["ok"])
            self.assertEqual("rollback_backup_invalid", result["error_code"])
            self.assertEqual(str(bad_backup), result["backup_path"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("rollback", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("rollback_backup_invalid", (last.get("error") or {}).get("error_code"))

    def test_tool_rollback_writes_requested_from_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_rollback_event_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=9)]),
                path=str(yaml_path),
                audit_meta={"action": "takeout", "source": "tests"},
            )

            source_event = {
                "timestamp": "2026-02-12T09:00:00",
                "action": "takeout",
                "trace_id": "trace-audit-1",
                "session_id": "session-audit-1",
            }
            backup_path = create_yaml_backup(str(yaml_path))
            self.assertIsNotNone(backup_path)
            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(backup_path),
                source_event=source_event,
            )

            self.assertTrue(result["ok"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 3)
            last = rows[-1]
            self.assertEqual("rollback", last["action"])
            self.assertEqual("success", last.get("status"))

            details = last.get("details") or {}
            requested_from_event = details.get("requested_from_event") or {}
            self.assertEqual("2026-02-12T09:00:00", requested_from_event.get("timestamp"))
            self.assertEqual("takeout", requested_from_event.get("action"))
            self.assertEqual("trace-audit-1", requested_from_event.get("trace_id"))
            self.assertEqual("session-audit-1", requested_from_event.get("session_id"))

    def test_tool_export_inventory_csv_writes_full_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_export_csv_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            output_path = Path(temp_dir) / "full_inventory.csv"
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                },
                "inventory": [
                    {
                        "id": 2,
                        "cell_line": "HeLa",
                        "short_name": "hela-a",
                        "box": 2,
                        "position": 9,
                        "frozen_at": "2026-02-10",
                        "passage_number": 7,
                    },
                    {
                        "id": 1,
                        "short_name": "k562-a",
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-09",
                        "note": "中文备注",
                    },
                ],
            }
            write_yaml(data, path=str(yaml_path), audit_meta={"action": "seed", "source": "tests"})

            response = tool_export_inventory_csv(
                yaml_path=str(yaml_path),
                output_path=str(output_path),
            )

            self.assertTrue(response["ok"])
            self.assertTrue(output_path.exists())
            self.assertEqual(2, response["result"]["count"])
            self.assertIn("box", response["result"]["columns"])
            self.assertIn("position", response["result"]["columns"])
            self.assertNotIn("location", response["result"]["columns"])
            self.assertIn("cell_line", response["result"]["columns"])
            self.assertIn("passage_number", response["result"]["columns"])

            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(2, len(rows))
            # Sorted by box/position/id, so id=1 comes first.
            self.assertEqual("1", rows[0]["id"])
            self.assertEqual("1", rows[0]["box"])
            self.assertEqual("2", rows[0]["position"])
            self.assertEqual("", rows[0]["cell_line"])
            self.assertEqual("2", rows[1]["id"])
            self.assertEqual("2", rows[1]["box"])
            self.assertEqual("9", rows[1]["position"])
            self.assertEqual("HeLa", rows[1]["cell_line"])
            self.assertEqual("7", rows[1]["passage_number"])
            self.assertEqual("中文备注", rows[0]["note"])

    def test_tool_export_inventory_csv_requires_output_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_export_csv_path_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_export_inventory_csv(
                yaml_path=str(yaml_path),
                output_path="",
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_output_path", response["error_code"])

    def test_tool_search_records_keywords(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "dTAG clone",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(str(yaml_path), query="k562 clone", mode="keywords")
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])

    def test_tool_search_records_by_box_and_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_slot_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=2, position=15),
                        make_record(2, box=2, position=14),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="rec-1",
                box=2,
                position=15,
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])
            self.assertEqual([1], response["result"]["slot_lookup"]["record_ids"])

    def test_tool_generate_stats_with_box_returns_active_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [2],
                                }
                            ],
                        },
                        make_record(4, box=2, position=1),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=1,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(1, result.get("box"))
            self.assertEqual(2, result.get("box_record_count"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2], ids)

    def test_tool_generate_stats_include_inactive_returns_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_inactive_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [2],
                                }
                            ],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=1,
                include_inactive=True,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(1, result.get("box"))
            self.assertEqual(3, result.get("box_record_count"))
            self.assertTrue(result.get("include_inactive"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2, 3], ids)

    def test_tool_generate_stats_default_record_count_excludes_taken_out(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_record_count_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [2]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(2, result.get("record_count"))
            preview = result.get("inventory_preview", [])
            self.assertEqual([1, 2], [item.get("id") for item in preview])
            self.assertFalse(result.get("include_inactive"))

    def test_tool_generate_stats_rejects_invalid_box(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=99,
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_box", response["error_code"])

    def test_tool_generate_stats_includes_inventory_preview_when_within_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_preview_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = [make_record(i, box=1, position=i) for i in range(1, 6)]
            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(5, result.get("record_count"))
            self.assertFalse(result.get("inventory_omitted"))
            self.assertEqual(100, result.get("inventory_limit"))
            self.assertEqual(5, len(result.get("inventory_preview", [])))
            self.assertNotIn("inventory", (result.get("data") or {}))

    def test_tool_generate_stats_omits_inventory_preview_when_over_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_omit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = []
            for idx in range(1, 102):
                box = ((idx - 1) // 81) + 1
                position = ((idx - 1) % 81) + 1
                records.append(make_record(idx, box=box, position=position))

            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(101, result.get("record_count"))
            self.assertTrue(result.get("inventory_omitted"))
            self.assertEqual("record_count_exceeds_limit", result.get("inventory_omitted_reason"))
            self.assertEqual(100, result.get("inventory_limit"))
            self.assertNotIn("inventory_preview", result)
            self.assertNotIn("inventory", (result.get("data") or {}))
            self.assertGreaterEqual(len(result.get("next_actions", [])), 2)

    def test_tool_generate_stats_box_records_still_return_when_over_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_large_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = []
            for idx in range(1, 131):
                box = ((idx - 1) // 65) + 1
                position = ((idx - 1) % 65) + 1
                records.append(make_record(idx, box=box, position=position))

            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=2,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(2, result.get("box"))
            self.assertEqual(65, result.get("box_record_count"))
            self.assertEqual(65, len(result.get("box_records", [])))
            self.assertTrue(result.get("inventory_omitted"))

    def test_tool_search_records_requires_non_empty_query(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_query_required_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="   ",
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertEqual("未输入检索词", response["message"])

    def test_tool_search_records_supports_location_shortcut_query(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_shortcut_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=2, position=15)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="2:15",
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["records"][0]["id"])
            self.assertEqual("2:15", response["result"]["applied_filters"]["query_shortcut"])
            self.assertEqual(2, response["result"]["applied_filters"]["box"])
            self.assertEqual("15", response["result"]["applied_filters"]["position"])

    def test_tool_search_records_record_id_with_query_filter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_rid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 7,
                            "parent_cell_line": "K562",
                            "short_name": "K562_main",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 8,
                            "parent_cell_line": "NCCIT",
                            "short_name": "NCCIT_main",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                record_id=7,
                query="K562",
                mode="keywords",
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(7, response["result"]["records"][0]["id"])

    def test_tool_search_records_default_excludes_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_active_default_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 7,
                            "parent_cell_line": "K562",
                            "short_name": "K562_active",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 8,
                            "parent_cell_line": "K562",
                            "short_name": "K562_taken",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [1]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
            )
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual([7], [item.get("id") for item in response["result"]["records"]])
            self.assertTrue(response["result"]["applied_filters"]["active_only"])

            include_inactive = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                active_only=False,
            )
            self.assertTrue(include_inactive["ok"])
            self.assertEqual(1, include_inactive["result"]["total_count"])
            self.assertEqual([8], [item.get("id") for item in include_inactive["result"]["records"]])

    def test_tool_query_takeout_events_single_date_and_action(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, position=2)
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "takeout", "positions": [1]},
                {"date": "2026-02-11", "action": "takeout", "positions": [2]},
                {"date": "2026-02-12", "action": "move", "positions": [2]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_query_takeout_events(
                str(yaml_path),
                date="2026-02-10",
                action="鍙栧嚭",
            )
            self.assertTrue(response["ok"])
            payload = response["result"]
            self.assertEqual(1, payload["record_count"])
            self.assertEqual(1, payload["event_count"])
            self.assertEqual("takeout", payload["records"][0]["events"][0]["action"])

            move_response = tool_query_takeout_events(
                str(yaml_path),
                date="2026-02-12",
                action="绉诲姩",
            )
            self.assertTrue(move_response["ok"])
            move_payload = move_response["result"]
            self.assertEqual(1, move_payload["event_count"])
            self.assertEqual("move", move_payload["records"][0]["events"][0]["action"])

    def test_tool_collect_timeline_includes_move_counts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_timeline_move_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, position=2)
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "move", "positions": [1]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
            )

            response = tool_collect_timeline(str(yaml_path), all_history=True)
            self.assertTrue(response["ok"])
            summary = response["result"]["summary"]
            self.assertEqual(1, summary["move"])
            self.assertGreaterEqual(summary["total_ops"], 1)

    def test_tool_list_audit_timeline_defaults_to_latest_50_rows(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_timeline_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            for idx in range(55):
                write_yaml(
                    make_data([make_record(1, box=1, position=1)]),
                    path=str(yaml_path),
                    audit_meta={"action": "touch", "source": "tests", "details": {"seq": idx}},
                )

            response = tool_list_audit_timeline(str(yaml_path))
            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(50, result["limit"])
            self.assertEqual(0, result["offset"])
            self.assertEqual(50, len(result["items"]))
            self.assertGreaterEqual(result["total"], 55)
            self.assertTrue(all(it.get("timestamp") for it in result["items"]))
            seqs = [int(it.get("audit_seq")) for it in result["items"]]
            self.assertEqual(seqs, sorted(seqs, reverse=True))

            all_rows_response = tool_list_audit_timeline(
                str(yaml_path),
                limit=None,
            )
            self.assertTrue(all_rows_response["ok"])
            all_result = all_rows_response["result"]
            self.assertIsNone(all_result["limit"])
            self.assertEqual(all_result["total"], len(all_result["items"]))
            self.assertGreaterEqual(len(all_result["items"]), 55)
            all_seqs = [int(it.get("audit_seq")) for it in all_result["items"]]
            self.assertEqual(all_seqs, sorted(all_seqs, reverse=True))

    def test_tool_list_audit_timeline_supports_action_filter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_timeline_filter_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "backup", "source": "tests"},
            )

            response = tool_list_audit_timeline(
                str(yaml_path),
                limit=10,
                action_filter="backup",
            )
            self.assertTrue(response["ok"])
            items = response["result"]["items"]
            self.assertGreaterEqual(len(items), 1)
            self.assertTrue(all(str(item.get("action")) == "backup" for item in items))

    def test_tool_list_audit_timeline_sorts_by_audit_seq_not_timestamp(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_seq_sort_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=2)]),
                path=str(yaml_path),
                audit_meta={"action": "touch_1", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=3)]),
                path=str(yaml_path),
                audit_meta={"action": "touch_2", "source": "tests"},
            )

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(rows), 3)
            # Intentionally scramble timestamps to ensure ordering follows audit_seq only.
            rows[0]["timestamp"] = "2099-12-31T23:59:59"
            rows[-1]["timestamp"] = "2000-01-01T00:00:00"
            audit_path.write_text(
                "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows),
                encoding="utf-8",
            )

            response = tool_list_audit_timeline(str(yaml_path), limit=None)
            self.assertTrue(response["ok"])
            items = response["result"]["items"]
            seqs = [int(item.get("audit_seq")) for item in items]
            self.assertEqual(seqs, sorted(seqs, reverse=True))
            self.assertEqual(max(seqs), int(items[0].get("audit_seq")))

    def test_tool_recommend_positions_and_raw_entries(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_misc_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                    make_record(3, box=1, position=3),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            rec_response = tool_recommend_positions(str(yaml_path), count=2)
            self.assertTrue(rec_response["ok"])
            self.assertGreaterEqual(len(rec_response["result"]["recommendations"]), 1)

            raw_response = tool_get_raw_entries(str(yaml_path), [1, 99])
            self.assertTrue(raw_response["ok"])
            self.assertEqual([99], raw_response["result"]["missing_ids"])


class TestToolEditEntry(unittest.TestCase):
    def test_edit_entry_updates_allowed_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "2026-02-01"},
            )
            self.assertTrue(result["ok"])
            self.assertEqual("2025-01-01", result["result"]["before"]["frozen_at"])
            self.assertEqual("2026-02-01", result["result"]["after"]["frozen_at"])

            data = load_yaml(str(yaml_path))
            rec = data["inventory"][0]
            self.assertEqual("2026-02-01", rec["frozen_at"])

    def test_edit_entry_rejects_forbidden_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"box": 2, "short_name": "x"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("forbidden_fields", result["error_code"])

    def test_edit_entry_rejects_nonexistent_record(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=999,
                fields={"frozen_at": "2026-02-01"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("record_not_found", result["error_code"])

    def test_edit_entry_validates_date(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "not-a-date"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("invalid_date", result["error_code"])

    def test_edit_entry_writes_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "2026-02-01"},
                actor_context=build_actor_context(),
            )

            rows = read_audit_rows(temp_dir)
            edit_rows = [r for r in rows if r.get("action") == "edit_entry"]
            self.assertTrue(len(edit_rows) >= 1)
            self.assertEqual("success", edit_rows[-1].get("status"))

    def test_edit_entry_rejects_empty_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("no_fields", result["error_code"])


# ---------------------------------------------------------------------------
# Integration tests: non-default box layouts (10x10, 8x12, custom box_count)
# ---------------------------------------------------------------------------

def make_data_custom(records, rows=9, cols=9, box_count=None, indexing=None):
    """Build YAML data dict with custom box_layout."""
    layout = {"rows": rows, "cols": cols}
    if box_count is not None:
        layout["box_count"] = box_count
    if indexing is not None:
        layout["indexing"] = indexing
    return {"meta": {"box_layout": layout, "cell_line_required": False}, "inventory": records}


class TestCustomLayout10x10(unittest.TestCase):
    """Integration: 10x10 grid with 8 boxes."""

    def _seed(self, records, rows=10, cols=10, box_count=8):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inv.yaml")
        write_raw_yaml(p, make_data_custom(records, rows, cols, box_count))
        return p, d

    def test_add_entry_position_100(self):
        """Position 100 should be valid in a 10x10 grid."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[100],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_position_101_rejected(self):
        """Position 101 should be rejected in a 10x10 grid."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[101],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertFalse(result["ok"])

    def test_add_entry_box_8_valid(self):
        """Box 8 should be valid with box_count=8."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=8, positions=[1],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_box_9_rejected(self):
        """Box 9 should be rejected with box_count=8."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=9, positions=[1],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertFalse(result["ok"])

    def test_stats_reports_correct_capacity(self):
        """Stats should report 10x10x8 = 800 total capacity."""
        p, _ = self._seed([make_record(1, box=1, position=1)])
        result = tool_generate_stats(p)
        self.assertTrue(result["ok"])
        self.assertEqual(800, result["result"]["total_capacity"])

    def test_list_empty_box_8(self):
        """list_empty_positions should work for box 8."""
        p, _ = self._seed([])
        result = tool_list_empty_positions(p, box=8)
        self.assertTrue(result["ok"])
        self.assertEqual(100, result["result"]["boxes"][0]["empty_count"])

    def test_list_empty_box_9_rejected(self):
        """list_empty_positions should reject box 9."""
        p, _ = self._seed([])
        result = tool_list_empty_positions(p, box=9)
        self.assertFalse(result["ok"])

    def test_recommend_positions_10x10(self):
        """recommend_positions should work with 10x10 grid."""
        p, _ = self._seed([])
        result = tool_recommend_positions(p, count=3)
        self.assertTrue(result["ok"])
        for rec in result["result"]["recommendations"]:
            for pos in rec["positions"]:
                self.assertLessEqual(int(pos), 100)

    def test_thaw_then_move_high_position(self):
        """Record at position 95 can be moved to position 100."""
        rec = make_record(1, box=1, position=95)
        p, _ = self._seed([rec])
        result = tool_record_move(
            p,
            record_id=1,
            from_slot=slot(1, 95),
            to_slot=slot(1, 100),
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))
        data = load_yaml(p)
        self.assertEqual(100, data["inventory"][0]["position"])


class TestCustomLayout8x12(unittest.TestCase):
    """Integration: 8x12 grid (96 slots, like microplates)."""

    def _seed(self, records):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inv.yaml")
        write_raw_yaml(p, make_data_custom(records, rows=8, cols=12, box_count=3))
        return p, d

    def test_add_entry_position_96(self):
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[96],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "HeLa"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_position_97_rejected(self):
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[97],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "HeLa"},
        )
        self.assertFalse(result["ok"])

    def test_stats_capacity_288(self):
        """8x12x3 = 288 total capacity."""
        p, _ = self._seed([])
        result = tool_generate_stats(p)
        self.assertTrue(result["ok"])
        self.assertEqual(288, result["result"]["total_capacity"])

    def test_batch_takeout_high_positions(self):
        """Batch thaw records at positions > 81 (old default limit)."""
        recs = [
            make_record(1, box=1, position=85),
            make_record(2, box=1, position=90),
        ]
        p, _ = self._seed(recs)
        result = tool_batch_takeout(
            p,
            entries=[takeout_entry(1, 1, 85), takeout_entry(2, 1, 90)],
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual(2, result["result"]["count"])


class TestValidatorsWithLayout(unittest.TestCase):
    """Integration: validators respect per-dataset layout."""

    def test_validate_inventory_10x10(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=1, position=100)
        data = make_data_custom([rec], rows=10, cols=10, box_count=5)
        errors, warnings = validate_inventory(data)
        self.assertEqual([], errors)

    def test_validate_inventory_rejects_101_in_10x10(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=1, position=101)
        data = make_data_custom([rec], rows=10, cols=10, box_count=5)
        errors, _ = validate_inventory(data)
        self.assertTrue(any("101" in e for e in errors))

    def test_validate_inventory_rejects_box_6_with_box_count_5(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=6, position=1)
        data = make_data_custom([rec], rows=9, cols=9, box_count=5)
        errors, _ = validate_inventory(data)
        self.assertTrue(any("box" in e.lower() for e in errors))

    def test_parse_positions_alphanumeric(self):
        from lib.validators import parse_positions
        layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        result = parse_positions("A1,B3", layout)
        self.assertEqual([1, 12], result)

    def test_parse_positions_alphanumeric_rejects_numeric_input(self):
        from lib.validators import parse_positions
        layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        with self.assertRaises(ValueError):
            parse_positions("1,2", layout)


class TestAdjustBoxCount(unittest.TestCase):
    def _seed(self, records, layout):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inv.yaml")
        write_raw_yaml(p, {"meta": {"box_layout": dict(layout)}, "inventory": list(records)})
        return p, d

    def test_add_boxes_updates_box_numbers_and_count(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_adjust_box_count(
            p,
            operation="add",
            count=2,
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 3, 4, 5, 6, 7], layout.get("box_numbers"))
        self.assertEqual(7, layout.get("box_count"))
        self.assertEqual(9, layout.get("rows"))
        self.assertEqual(9, layout.get("cols"))

    def test_remove_middle_box_requires_mode(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=3,
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("renumber_mode_required", result.get("error_code"))

    def test_remove_middle_box_keep_gaps(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=3,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 4, 5], layout.get("box_numbers"))
        self.assertEqual(4, layout.get("box_count"))

        empty = tool_list_empty_positions(p)
        self.assertTrue(empty["ok"])
        self.assertEqual(["1", "2", "4", "5"], [b["box"] for b in empty["result"]["boxes"]])

    def test_add_boxes_preserves_existing_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 3,
                "box_tags": {"1": "LN2-A", "2": "Virus"},
            },
        )
        result = tool_adjust_box_count(
            p,
            operation="add",
            count=2,
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"1": "LN2-A", "2": "Virus"}, layout.get("box_tags"))

    def test_remove_middle_box_keep_gaps_updates_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_tags": {"2": "A", "3": "B", "4": "C"},
            },
        )
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=3,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"2": "A", "4": "C"}, layout.get("box_tags"))

    def test_remove_middle_box_renumber_remaps_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_tags": {"2": "A", "4": "C", "5": "D"},
            },
        )
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=3,
            renumber_mode="renumber_contiguous",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 3, 4], layout.get("box_numbers"))
        self.assertEqual({"2": "A", "3": "C", "4": "D"}, layout.get("box_tags"))

    def test_set_box_tag_updates_and_clears(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 3})
        result = tool_set_box_tag(
            p,
            box=2,
            tag=" -80 second shelf ",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"2": "-80 second shelf"}, layout.get("box_tags"))

        clear_result = tool_set_box_tag(
            p,
            box=2,
            tag="",
            auto_backup=False,
        )
        self.assertTrue(clear_result["ok"], clear_result.get("message"))
        data_after = load_yaml(p)
        self.assertNotIn("box_tags", data_after["meta"]["box_layout"])

    def test_set_box_tag_rejects_multiline(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 2})
        result = tool_set_box_tag(
            p,
            box=1,
            tag="line1\nline2",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tag", result.get("error_code"))

    def test_set_box_tag_rejects_too_long(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 2})
        result = tool_set_box_tag(
            p,
            box=1,
            tag="x" * 81,
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tag", result.get("error_code"))

    def test_remove_non_empty_box_blocked(self):
        records = [make_record(1, box=2, position=1)]
        p, _ = self._seed(records, {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=2,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("box_not_empty", result.get("error_code"))

    def test_remove_box_with_only_historical_records_reports_reason(self):
        records = [
            {
                "id": 1,
                "parent_cell_line": "NCCIT",
                "short_name": "hist-only",
                "box": 2,
                "position": None,
                "frozen_at": "2025-01-01",
                "thaw_events": [
                    {"date": "2025-01-10", "action": "takeout", "positions": [1]},
                ],
            }
        ]
        p, _ = self._seed(records, {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_adjust_box_count(
            p,
            operation="remove",
            box=2,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("box_not_empty", result.get("error_code"))
        self.assertIn("historical", str(result.get("message", "")).lower())
        self.assertEqual([], result.get("active_blocking_record_ids"))
        self.assertEqual([1], result.get("historical_blocking_record_ids"))

    def test_record_takeout_cross_box_respects_box_numbers(self):
        records = [make_record(1, box=1, position=1)]
        p, _ = self._seed(
            records,
            {"rows": 9, "cols": 9, "box_count": 4, "box_numbers": [1, 2, 4, 5]},
        )
        result = tool_record_move(
            p,
            record_id=1,
            from_slot=slot(1, 1),
            to_slot=slot(3, 2),
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_box", result.get("error_code"))


if __name__ == "__main__":
    unittest.main()

