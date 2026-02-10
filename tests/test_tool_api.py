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
    tool_batch_thaw,
    tool_collect_timeline,
    tool_record_thaw,
    tool_rollback,
)
from lib.tool_api import (
    tool_get_raw_entries,
    tool_query_inventory,
    tool_query_thaw_events,
    tool_recommend_positions,
    tool_search_records,
)
from lib.yaml_ops import load_yaml, write_yaml


def make_record(rec_id=1, box=1, positions=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def write_raw_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def read_audit_rows(temp_dir):
    audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
    if not audit_path.exists():
        return []
    return [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class ToolApiTests(unittest.TestCase):
    def test_tool_add_entry_writes_actor_metadata(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            actor = build_actor_context(
                actor_type="agent",
                channel="agent",
                actor_id="react-bot",
                session_id="sess-test",
                trace_id="trace-test",
            )
            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-2",
                box=1,
                positions=[2, 3],
                frozen_at="2026-02-10",
                note="from test",
                actor_context=actor,
                source="tests/test_tool_api.py",
                auto_html=False,
                auto_server=False,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["new_id"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(2, len(current["inventory"]))

            audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
            lines = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last = lines[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("tool_add_entry", last["tool_name"])
            self.assertEqual("agent", last["actor_type"])
            self.assertEqual("agent", last["channel"])
            self.assertEqual("react-bot", last["actor_id"])
            self.assertEqual("sess-test", last["session_id"])
            self.assertEqual("trace-test", last["trace_id"])

    def test_tool_record_thaw_dry_run_no_write(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1, 2])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=1,
                date_str="2026-02-10",
                dry_run=True,
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])

            current = load_yaml(str(yaml_path))
            self.assertEqual([1, 2], current["inventory"][0]["positions"])

            audit_path = Path(temp_dir) / "ln2_inventory_audit.jsonl"
            lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(lines))

    def test_tool_batch_thaw_updates_multiple_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        make_record(2, box=1, positions=[2]),
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_batch_thaw(
                yaml_path=str(yaml_path),
                entries=[(1, 1), (2, 2)],
                date_str="2026-02-10",
                action="取出",
                source="tests/test_tool_api.py",
                auto_html=False,
                auto_server=False,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["count"])

            current = load_yaml(str(yaml_path))
            self.assertEqual([], current["inventory"][0]["positions"])
            self.assertEqual([], current["inventory"][1]["positions"])

    def test_tool_record_thaw_move_updates_positions_and_appends_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1, 2])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=1,
                to_position=3,
                date_str="2026-02-10",
                action="move",
                note="reorg",
                auto_html=False,
                auto_server=False,
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual(3, result["preview"]["to_position"])
            self.assertEqual([1, 2], result["preview"]["positions_before"])
            self.assertEqual([3, 2], result["preview"]["positions_after"])

            current = load_yaml(str(yaml_path))
            self.assertEqual([3, 2], current["inventory"][0]["positions"])
            events = current["inventory"][0].get("thaw_events") or []
            self.assertEqual(1, len(events))
            self.assertEqual("move", events[-1].get("action"))
            self.assertEqual([1], events[-1].get("positions"))
            self.assertEqual(1, events[-1].get("from_position"))
            self.assertEqual(3, events[-1].get("to_position"))

    def test_tool_record_thaw_move_swaps_with_occupied_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_swap_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        make_record(2, box=1, positions=[2]),
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=1,
                to_position=2,
                date_str="2026-02-10",
                action="移动",
                auto_html=False,
                auto_server=False,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["preview"].get("swap_with_record_id"))

            current = load_yaml(str(yaml_path))
            self.assertEqual([2], current["inventory"][0]["positions"])
            self.assertEqual([1], current["inventory"][1]["positions"])

            source_events = current["inventory"][0].get("thaw_events") or []
            swap_events = current["inventory"][1].get("thaw_events") or []
            self.assertEqual(1, len(source_events))
            self.assertEqual(1, len(swap_events))
            self.assertEqual(2, source_events[-1].get("to_position"))
            self.assertEqual(1, swap_events[-1].get("to_position"))

    def test_tool_record_thaw_move_requires_to_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_require_to_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=1,
                date_str="2026-02-10",
                action="move",
                auto_html=False,
                auto_server=False,
            )

            self.assertFalse(result["ok"])
            self.assertEqual("invalid_move_target", result["error_code"])

    def test_tool_batch_thaw_move_updates_positions_and_swaps(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        make_record(2, box=1, positions=[2]),
                        make_record(3, box=1, positions=[3]),
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_batch_thaw(
                yaml_path=str(yaml_path),
                entries="1:1->2,3:3->4",
                date_str="2026-02-10",
                action="移动",
                auto_html=False,
                auto_server=False,
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual(2, result["result"]["count"])
            self.assertEqual([1, 2, 3], result["result"]["affected_record_ids"])

            current = load_yaml(str(yaml_path))
            self.assertEqual([2], current["inventory"][0]["positions"])
            self.assertEqual([1], current["inventory"][1]["positions"])
            self.assertEqual([4], current["inventory"][2]["positions"])

            self.assertEqual(1, len(current["inventory"][0].get("thaw_events") or []))
            self.assertEqual(1, len(current["inventory"][1].get("thaw_events") or []))
            self.assertEqual(1, len(current["inventory"][2].get("thaw_events") or []))

    def test_tool_batch_thaw_move_rejects_non_move_entry_shape(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_shape_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_batch_thaw(
                yaml_path=str(yaml_path),
                entries=[(1, 1)],
                date_str="2026-02-10",
                action="move",
                auto_html=False,
                auto_server=False,
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])

    def test_tool_add_entry_rejects_duplicate_ids_in_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_dup_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        make_record(1, box=1, positions=[2]),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-3",
                box=1,
                positions=[3],
                frozen_at="2026-02-10",
                auto_html=False,
                auto_server=False,
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("重复的 ID" in err for err in result.get("errors", [])))

            rows = read_audit_rows(temp_dir)
            self.assertEqual(1, len(rows))
            last = rows[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("integrity_validation_failed", (last.get("error") or {}).get("error_code"))

    def test_tool_add_entry_invalid_date_writes_failed_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_date_audit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-invalid-date",
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                auto_html=False,
                auto_server=False,
            )

            self.assertFalse(result["ok"])
            self.assertEqual("invalid_date", result["error_code"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("invalid_date", (last.get("error") or {}).get("error_code"))

    def test_tool_record_thaw_rejects_malformed_thaw_events(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_events_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            broken = make_record(1, box=1, positions=[1, 2])
            broken["thaw_events"] = "broken"
            write_raw_yaml(yaml_path, make_data([broken]))

            result = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=1,
                date_str="2026-02-10",
                auto_html=False,
                auto_server=False,
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("thaw_events" in err for err in result.get("errors", [])))

    def test_tool_add_entry_rejects_invalid_date_box_and_positions(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_invalid_args_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            bad_date = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-bad-date",
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                auto_html=False,
                auto_server=False,
            )
            self.assertFalse(bad_date["ok"])
            self.assertEqual("invalid_date", bad_date["error_code"])

            bad_box = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-bad-box",
                box=99,
                positions=[2],
                frozen_at="2026-02-10",
                auto_html=False,
                auto_server=False,
            )
            self.assertFalse(bad_box["ok"])
            self.assertEqual("invalid_box", bad_box["error_code"])

            bad_pos = tool_record_thaw(
                yaml_path=str(yaml_path),
                record_id=1,
                position=999,
                date_str="2026-02-10",
                auto_html=False,
                auto_server=False,
            )
            self.assertFalse(bad_pos["ok"])
            self.assertEqual("invalid_position", bad_pos["error_code"])

    def test_tool_add_entry_rejects_existing_position_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_conflict_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, positions=[10]),
                        make_record(2, box=1, positions=[10]),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                parent_cell_line="K562",
                short_name="clone-4",
                box=1,
                positions=[11],
                frozen_at="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("位置冲突" in err for err in result.get("errors", [])))

    def test_tool_rollback_blocks_invalid_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_rollback_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            good = make_data([make_record(1, box=1, positions=[1])])
            write_yaml(good, path=str(yaml_path), auto_html=False, auto_server=False)

            bad_backup = Path(temp_dir) / "manual_invalid_backup.yaml"
            bad_payload = make_data([make_record(1, box=99, positions=[1])])
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

    def test_tool_query_inventory_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "plasmid_name": "pX",
                            "plasmid_id": "p2",
                            "box": 2,
                            "positions": [10, 11],
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_query_inventory(str(yaml_path), cell="k562", box=2, position=10)
            self.assertTrue(response["ok"])
            records = response["result"]["records"]
            self.assertEqual(1, len(records))
            self.assertEqual(2, records[0]["id"])

    def test_tool_search_records_keywords(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, positions=[1]),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "dTAG clone",
                            "box": 1,
                            "positions": [2],
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(str(yaml_path), query="k562 clone", mode="keywords")
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])

    def test_tool_query_thaw_events_single_date_and_action(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[2])
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "thaw", "positions": [1]},
                {"date": "2026-02-11", "action": "takeout", "positions": [2]},
                {"date": "2026-02-12", "action": "move", "positions": [2]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_query_thaw_events(
                str(yaml_path),
                date="2026-02-10",
                action="复苏",
            )
            self.assertTrue(response["ok"])
            payload = response["result"]
            self.assertEqual(1, payload["record_count"])
            self.assertEqual(1, payload["event_count"])
            self.assertEqual("thaw", payload["records"][0]["events"][0]["action"])

            move_response = tool_query_thaw_events(
                str(yaml_path),
                date="2026-02-12",
                action="移动",
            )
            self.assertTrue(move_response["ok"])
            move_payload = move_response["result"]
            self.assertEqual(1, move_payload["event_count"])
            self.assertEqual("move", move_payload["records"][0]["events"][0]["action"])

    def test_tool_collect_timeline_includes_move_counts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_timeline_move_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[2])
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "move", "positions": [1]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            response = tool_collect_timeline(str(yaml_path), all_history=True)
            self.assertTrue(response["ok"])
            summary = response["result"]["summary"]
            self.assertEqual(1, summary["move"])
            self.assertGreaterEqual(summary["total_ops"], 1)

    def test_tool_recommend_positions_and_raw_entries(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_misc_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1, 2, 3])]),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
                audit_meta={"action": "seed", "source": "tests"},
            )

            rec_response = tool_recommend_positions(str(yaml_path), count=2)
            self.assertTrue(rec_response["ok"])
            self.assertGreaterEqual(len(rec_response["result"]["recommendations"]), 1)

            raw_response = tool_get_raw_entries(str(yaml_path), [1, 99])
            self.assertTrue(raw_response["ok"])
            self.assertEqual([99], raw_response["result"]["missing_ids"])


if __name__ == "__main__":
    unittest.main()
