import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.yaml_ops import (
    create_yaml_backup,
    get_audit_log_path,
    get_audit_log_paths,
    list_yaml_backups,
    load_yaml,
    read_audit_events,
    rollback_yaml,
    write_yaml,
)


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
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def make_utf8_mojibake(text):
    for enc in ("gb18030", "gbk", "cp936"):
        try:
            return text.encode("utf-8").decode(enc)
        except UnicodeDecodeError:
            continue
    raise AssertionError("Failed to synthesize mojibake sample")


class YamlOpsWriteTests(unittest.TestCase):
    def test_write_yaml_persists_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_ops_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = make_data([])

            write_yaml(data, path=str(yaml_path))

            self.assertTrue(yaml_path.exists())
            loaded = load_yaml(str(yaml_path))
            self.assertEqual([], loaded.get("inventory", []))

    def test_load_yaml_repairs_utf8_gbk_mojibake_values(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_repair_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            original = "\u4f60\u662f\u6570\u636e\u6e05\u6d17\u4e0e\u7ed3\u6784\u5316\u52a9\u624b"
            mojibake = original.encode("utf-8").decode("gb18030")

            data = make_data([make_record(1, box=1, position=1)])
            data["inventory"][0]["note"] = mojibake
            data["inventory"][0]["short_name"] = mojibake

            with open(yaml_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)

            loaded = load_yaml(str(yaml_path))
            rec = loaded.get("inventory", [])[0]
            self.assertEqual(original, rec.get("note"))
            self.assertEqual(original, rec.get("short_name"))

    def test_load_yaml_repairs_utf8_gbk_mojibake_mixed_content(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_repair_mixed_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            original_note = "\u8bb0\u5f55 #20 (id=20): thaw_events[1] has invalid action"
            mojibake_note = make_utf8_mojibake(original_note)

            data = make_data([make_record(1, box=1, position=1)])
            data["inventory"][0]["note"] = mojibake_note

            with open(yaml_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)

            loaded = load_yaml(str(yaml_path))
            rec = loaded.get("inventory", [])[0]
            self.assertEqual(original_note, rec.get("note"))

    def test_load_yaml_keeps_valid_chinese_mixed_content_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_keep_valid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            original_note = "\u8bb0\u5f55 #20 (id=20): thaw_events[1] has invalid action"

            data = make_data([make_record(1, box=1, position=1)])
            data["inventory"][0]["note"] = original_note

            with open(yaml_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)

            loaded = load_yaml(str(yaml_path))
            rec = loaded.get("inventory", [])[0]
            self.assertEqual(original_note, rec.get("note"))


class YamlOpsSafetyTests(unittest.TestCase):
    def test_write_yaml_creates_backup_and_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_safety_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            data_v1 = make_data([make_record(1, box=1, position=1)])
            write_yaml(
                data_v1,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            data_v2 = make_data([
                make_record(1, box=1, position=1),
                make_record(2, box=2, position=3),
                make_record(3, box=2, position=4),
            ])
            write_yaml(
                data_v2,
                path=str(yaml_path),
                audit_meta={"action": "add_entry", "source": "tests"},
            )

            backups = list_yaml_backups(str(yaml_path))
            self.assertEqual(1, len(backups))

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            self.assertTrue(audit_path.exists())

            lines = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)
            last = lines[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("tests", last["source"])
            self.assertIn(2, last["changed_ids"]["added"])
            self.assertTrue(last["backup_path"])
            self.assertTrue(last.get("session_id"))
            self.assertTrue(last.get("trace_id"))
            self.assertNotIn("actor_type", last)
            self.assertNotIn("actor_id", last)
            self.assertNotIn("channel", last)
            self.assertEqual("success", last.get("status"))

    def test_audit_logs_are_isolated_per_yaml_file(self):
        with tempfile.TemporaryDirectory(prefix="ln2_audit_isolation_") as temp_dir:
            yaml_a = Path(temp_dir) / "inventory_a.yaml"
            yaml_b = Path(temp_dir) / "inventory_b.yaml"

            write_yaml(make_data([make_record(1, box=1, position=1)]), path=str(yaml_a))
            write_yaml(make_data([make_record(2, box=2, position=2)]), path=str(yaml_b))

            audit_a = Path(get_audit_log_path(str(yaml_a)))
            audit_b = Path(get_audit_log_path(str(yaml_b)))

            self.assertNotEqual(str(audit_a), str(audit_b))
            self.assertTrue(audit_a.exists())
            self.assertTrue(audit_b.exists())

    def test_legacy_named_yaml_paths_get_unique_audit_targets(self):
        with tempfile.TemporaryDirectory(prefix="ln2_audit_legacy_iso_") as root_dir:
            dir_a = Path(root_dir) / "project_a"
            dir_b = Path(root_dir) / "project_b"
            dir_a.mkdir(parents=True, exist_ok=True)
            dir_b.mkdir(parents=True, exist_ok=True)

            yaml_a = dir_a / "inventory.yaml"
            yaml_b = dir_b / "inventory.yaml"

            # Write raw YAML without inventory_instance_id to exercise legacy fallback naming.
            with yaml_a.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    make_data([make_record(1)]),
                    handle,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )
            with yaml_b.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    make_data([make_record(2)]),
                    handle,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )

            audit_a = Path(get_audit_log_path(str(yaml_a)))
            audit_b = Path(get_audit_log_path(str(yaml_b)))

            self.assertNotEqual(str(audit_a), str(audit_b))

    def test_read_audit_events_reads_only_canonical_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_audit_merge_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            candidates = get_audit_log_paths(str(yaml_path))
            self.assertEqual(1, len(candidates))
            canonical_path = Path(candidates[0])
            canonical_event = {
                "timestamp": "2026-02-20T08:00:00",
                "action": "record_takeout",
                "status": "success",
                "source": "tests",
            }
            canonical_path.write_text(
                json.dumps(canonical_event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            events = read_audit_events(str(yaml_path))
            actions = [str(ev.get("action") or "") for ev in events]
            self.assertIn("record_takeout", actions)

    def test_instance_guard_stable_on_same_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_instance_guard_stable_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            first = load_yaml(str(yaml_path))
            first_meta = dict(first.get("meta") or {})
            first_id = str(first_meta.get("inventory_instance_id") or "")
            self.assertTrue(first_id)

            data2 = make_data([make_record(1, box=1, position=2)])
            data2["meta"]["inventory_instance_id"] = first_id
            write_yaml(
                data2,
                path=str(yaml_path),
                audit_meta={"action": "update", "source": "tests"},
            )

            second = load_yaml(str(yaml_path))
            second_meta = dict(second.get("meta") or {})
            self.assertEqual(first_id, str(second_meta.get("inventory_instance_id") or ""))
            self.assertEqual(str(yaml_path.resolve()), str(Path(second_meta.get("instance_origin_path")).resolve()))

            rows = read_audit_events(str(yaml_path))
            last = rows[-1]
            details = last.get("details") or {}
            self.assertNotIn("instance_guard_decision", details)

    def test_instance_guard_copy_forks_identity_when_origin_exists(self):
        with tempfile.TemporaryDirectory(prefix="ln2_instance_guard_copy_") as temp_dir:
            src_path = Path(temp_dir) / "inventory.yaml"
            dst_path = Path(temp_dir) / "inventory_copy.yaml"

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(src_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            src_id = str((load_yaml(str(src_path)).get("meta") or {}).get("inventory_instance_id") or "")
            self.assertTrue(src_id)

            shutil.copy2(src_path, dst_path)
            dst_data = load_yaml(str(dst_path))
            dst_data["inventory"][0]["position"] = 2
            write_yaml(
                dst_data,
                path=str(dst_path),
                audit_meta={"action": "edit_copy", "source": "tests"},
            )

            src_after = load_yaml(str(src_path))
            dst_after = load_yaml(str(dst_path))
            src_after_id = str((src_after.get("meta") or {}).get("inventory_instance_id") or "")
            dst_after_meta = dict(dst_after.get("meta") or {})
            dst_after_id = str(dst_after_meta.get("inventory_instance_id") or "")

            self.assertEqual(src_id, src_after_id)
            self.assertNotEqual(src_after_id, dst_after_id)
            self.assertEqual(str(dst_path.resolve()), str(Path(dst_after_meta.get("instance_origin_path")).resolve()))

            rows = read_audit_events(str(dst_path))
            last = rows[-1]
            details = last.get("details") or {}
            self.assertEqual("forked_copy", details.get("instance_guard_decision"))
            self.assertEqual(src_after_id, details.get("instance_guard_old_id"))
            self.assertEqual(dst_after_id, details.get("instance_guard_new_id"))
            self.assertEqual(str(src_path.resolve()), details.get("instance_guard_origin_path_before"))
            self.assertEqual(str(dst_path.resolve()), details.get("instance_guard_origin_path_after"))
            self.assertEqual(dst_after_id, last.get("inventory_instance_id"))
            backup_path = str(last.get("backup_path") or "")
            self.assertIn(dst_after_id, backup_path)

    def test_instance_guard_copy_then_delete_origin_is_treated_as_rename(self):
        with tempfile.TemporaryDirectory(prefix="ln2_instance_guard_copy_del_") as temp_dir:
            src_path = Path(temp_dir) / "inventory.yaml"
            dst_path = Path(temp_dir) / "inventory_copy.yaml"

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(src_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            original_id = str((load_yaml(str(src_path)).get("meta") or {}).get("inventory_instance_id") or "")
            shutil.copy2(src_path, dst_path)
            src_path.unlink()

            dst_data = load_yaml(str(dst_path))
            dst_data["inventory"][0]["position"] = 3
            write_yaml(
                dst_data,
                path=str(dst_path),
                audit_meta={"action": "touch", "source": "tests"},
            )

            dst_after = load_yaml(str(dst_path))
            dst_meta = dict(dst_after.get("meta") or {})
            self.assertEqual(original_id, str(dst_meta.get("inventory_instance_id") or ""))
            self.assertEqual(str(dst_path.resolve()), str(Path(dst_meta.get("instance_origin_path")).resolve()))

            rows = read_audit_events(str(dst_path))
            last = rows[-1]
            details = last.get("details") or {}
            self.assertEqual("adopted_rename", details.get("instance_guard_decision"))
            self.assertEqual(original_id, details.get("instance_guard_old_id"))
            self.assertEqual(original_id, details.get("instance_guard_new_id"))

    def test_instance_guard_rename_keeps_identity_and_updates_origin(self):
        with tempfile.TemporaryDirectory(prefix="ln2_instance_guard_rename_") as temp_dir:
            old_path = Path(temp_dir) / "inventory.yaml"
            new_path = Path(temp_dir) / "renamed_inventory.yaml"

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(old_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            original_id = str((load_yaml(str(old_path)).get("meta") or {}).get("inventory_instance_id") or "")
            old_path.rename(new_path)

            renamed_data = load_yaml(str(new_path))
            renamed_data["inventory"][0]["position"] = 4
            write_yaml(
                renamed_data,
                path=str(new_path),
                audit_meta={"action": "rename_touch", "source": "tests"},
            )

            renamed_after = load_yaml(str(new_path))
            renamed_meta = dict(renamed_after.get("meta") or {})
            self.assertEqual(original_id, str(renamed_meta.get("inventory_instance_id") or ""))
            self.assertEqual(str(new_path.resolve()), str(Path(renamed_meta.get("instance_origin_path")).resolve()))

            rows = read_audit_events(str(new_path))
            last = rows[-1]
            details = last.get("details") or {}
            self.assertEqual("adopted_rename", details.get("instance_guard_decision"))

    def test_instance_guard_backfills_missing_origin_without_fork(self):
        with tempfile.TemporaryDirectory(prefix="ln2_instance_guard_backfill_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            payload = make_data([make_record(1, box=1, position=1)])
            payload["meta"]["inventory_instance_id"] = "instance-legacy-no-origin"
            with open(yaml_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False, width=120)

            loaded = load_yaml(str(yaml_path))
            loaded["inventory"][0]["position"] = 2
            write_yaml(
                loaded,
                path=str(yaml_path),
                audit_meta={"action": "legacy_touch", "source": "tests"},
            )

            after = load_yaml(str(yaml_path))
            meta = dict(after.get("meta") or {})
            self.assertEqual("instance-legacy-no-origin", str(meta.get("inventory_instance_id") or ""))
            self.assertEqual(str(yaml_path.resolve()), str(Path(meta.get("instance_origin_path")).resolve()))

            rows = read_audit_events(str(yaml_path))
            last = rows[-1]
            details = last.get("details") or {}
            self.assertNotIn("instance_guard_decision", details)

    def test_rollback_yaml_restores_latest_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rollback_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            data_v1 = make_data([make_record(1, box=1, position=1)])
            data_v2 = make_data([make_record(1, box=1, position=9)])

            write_yaml(data_v1, path=str(yaml_path))
            write_yaml(data_v2, path=str(yaml_path))
            restore_target = list_yaml_backups(str(yaml_path))[0]

            current = load_yaml(str(yaml_path))
            self.assertEqual(9, current["inventory"][0]["position"])

            request_backup_path = create_yaml_backup(str(yaml_path))
            result = rollback_yaml(
                path=str(yaml_path),
                backup_path=str(restore_target),
                request_backup_path=str(request_backup_path),
                audit_meta={"source": "tests"},
            )

            restored = load_yaml(str(yaml_path))
            self.assertEqual(1, restored["inventory"][0]["position"])
            self.assertTrue(Path(result["restored_from"]).exists())
            self.assertEqual(str(Path(request_backup_path).resolve()), str(Path(result["snapshot_before_rollback"]).resolve()))

    def test_write_yaml_rejects_invalid_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_write_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            invalid = make_data([make_record(1, box=99, position=1)])

            with self.assertRaises(ValueError) as ctx:
                write_yaml(invalid, path=str(yaml_path))

            self.assertIn("完整性校验失败", str(ctx.exception))
            self.assertFalse(yaml_path.exists())

    def test_rollback_yaml_blocks_invalid_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rollback_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            invalid_backup = Path(temp_dir) / "inventory.invalid.bak"
            invalid_backup.write_text(
                "meta:\n  box_layout:\n    rows: 9\n    cols: 9\ninventory:\n  - id: 1\n    parent_cell_line: NCCIT\n    short_name: bad\n    box: 1\n    position: null\n    frozen_at: 2025-01-01\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                rollback_yaml(
                    path=str(yaml_path),
                    backup_path=str(invalid_backup),
                )

            self.assertIn("回滚被阻止", str(ctx.exception))
            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])


if __name__ == "__main__":
    unittest.main()
