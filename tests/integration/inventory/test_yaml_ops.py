"""
Module: test_yaml_ops
Layer: integration/inventory
Covers: lib/yaml_ops.py

YAML 读写、审计日志与备份
"""

import json
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.inventory_paths import InventoryPathError, create_managed_dataset_yaml_path
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


@contextmanager
def managed_inventory_root(prefix):
    with tempfile.TemporaryDirectory(prefix=prefix) as install_dir, patch(
        "lib.inventory_paths.get_install_dir",
        return_value=install_dir,
    ):
        yield Path(install_dir)


def _managed_yaml(dataset_name):
    return Path(create_managed_dataset_yaml_path(dataset_name))


class YamlOpsWriteTests(unittest.TestCase):
    def test_write_yaml_persists_inventory(self):
        with managed_inventory_root("ln2_yaml_ops_"):
            yaml_path = _managed_yaml("write-persist")
            data = make_data([])

            write_yaml(data, path=str(yaml_path))

            self.assertTrue(yaml_path.exists())
            loaded = load_yaml(str(yaml_path))
            self.assertEqual([], loaded.get("inventory", []))

    def test_load_yaml_repairs_utf8_gbk_mojibake_values(self):
        with managed_inventory_root("ln2_yaml_repair_"):
            yaml_path = _managed_yaml("repair-values")
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
        with managed_inventory_root("ln2_yaml_repair_mixed_"):
            yaml_path = _managed_yaml("repair-mixed")
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
        with managed_inventory_root("ln2_yaml_keep_valid_"):
            yaml_path = _managed_yaml("keep-valid")
            original_note = "\u8bb0\u5f55 #20 (id=20): thaw_events[1] has invalid action"

            data = make_data([make_record(1, box=1, position=1)])
            data["inventory"][0]["note"] = original_note

            with open(yaml_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)

            loaded = load_yaml(str(yaml_path))
            rec = loaded.get("inventory", [])[0]
            self.assertEqual(original_note, rec.get("note"))


class YamlOpsSafetyTests(unittest.TestCase):
    def test_audit_seq_increases_monotonically(self):
        with managed_inventory_root("ln2_audit_seq_"):
            yaml_path = _managed_yaml("seq-monotonic")
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

            rows = read_audit_events(str(yaml_path))
            seqs = [int(row.get("audit_seq")) for row in rows]
            self.assertEqual([1, 2, 3], seqs)

    def test_write_yaml_creates_backup_and_audit(self):
        with managed_inventory_root("ln2_safety_"):
            yaml_path = _managed_yaml("write-safety")

            data_v1 = make_data([make_record(1, box=1, position=1)])
            write_yaml(
                data_v1,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            data_v2 = make_data(
                [
                    make_record(1, box=1, position=1),
                    make_record(2, box=2, position=3),
                    make_record(3, box=2, position=4),
                ]
            )
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
            self.assertFalse(last.get("backup_path"))
            self.assertGreater(int(last.get("audit_seq") or 0), 0)

    def test_write_yaml_meta_only_allows_required_field_missing_in_existing_records(self):
        with managed_inventory_root("ln2_yaml_meta_only_"):
            yaml_path = _managed_yaml("meta-only-write")
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 2, "box_numbers": [1, 2]},
                    "custom_fields": [
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        {"key": "passage", "label": "Passage", "type": "int", "required": True},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2025-01-01",
                        "cell_line": "K562",
                    }
                ],
            }

            write_yaml(
                data,
                path=str(yaml_path),
                audit_meta={"action": "meta_only_write", "source": "tests"},
                validation_scope="meta_only",
            )

            loaded = load_yaml(str(yaml_path))
            self.assertEqual("K562", loaded["inventory"][0]["cell_line"])

    def test_write_yaml_full_scope_still_blocks_required_field_missing(self):
        with managed_inventory_root("ln2_yaml_full_scope_"):
            yaml_path = _managed_yaml("full-scope-write")
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 2, "box_numbers": [1, 2]},
                    "custom_fields": [
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        {"key": "passage", "label": "Passage", "type": "int", "required": True},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2025-01-01",
                        "cell_line": "K562",
                    }
                ],
            }

            with self.assertRaises(ValueError):
                write_yaml(
                    data,
                    path=str(yaml_path),
                    audit_meta={"action": "full_write", "source": "tests"},
                    validation_scope="full",
                )
            self.assertFalse(yaml_path.exists())
            self.assertFalse(Path(get_audit_log_path(str(yaml_path))).exists())

    def test_audit_logs_are_isolated_per_yaml_file(self):
        with managed_inventory_root("ln2_audit_isolation_"):
            yaml_a = _managed_yaml("dataset-a")
            yaml_b = _managed_yaml("dataset-b")

            write_yaml(make_data([make_record(1, box=1, position=1)]), path=str(yaml_a))
            write_yaml(make_data([make_record(2, box=2, position=2)]), path=str(yaml_b))

            audit_a = Path(get_audit_log_path(str(yaml_a)))
            audit_b = Path(get_audit_log_path(str(yaml_b)))

            self.assertNotEqual(str(audit_a), str(audit_b))
            self.assertTrue(audit_a.exists())
            self.assertTrue(audit_b.exists())

    def test_unmanaged_yaml_paths_are_rejected_for_audit_lookup(self):
        with managed_inventory_root("ln2_audit_legacy_iso_") as install_root:
            legacy_yaml = install_root / "legacy" / "inventory.yaml"
            legacy_yaml.parent.mkdir(parents=True, exist_ok=True)
            legacy_yaml.write_text("meta: {}\ninventory: []\n", encoding="utf-8")

            with self.assertRaises(InventoryPathError):
                get_audit_log_path(str(legacy_yaml))

    def test_read_audit_events_reads_only_canonical_path(self):
        with managed_inventory_root("ln2_audit_merge_"):
            yaml_path = _managed_yaml("audit-read")
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
                "action": "takeout",
                "status": "success",
                "source": "tests",
            }
            canonical_path.write_text(
                json.dumps(canonical_event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            events = read_audit_events(str(yaml_path))
            actions = [str(ev.get("action") or "") for ev in events]
            self.assertIn("takeout", actions)

    def test_instance_guard_stable_on_same_path(self):
        with managed_inventory_root("ln2_instance_guard_stable_"):
            yaml_path = _managed_yaml("stable")
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
        with managed_inventory_root("ln2_instance_guard_copy_"):
            src_path = _managed_yaml("copy-src")
            dst_path = _managed_yaml("copy-dst")

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
            self.assertFalse(last.get("backup_path"))
            backups = list_yaml_backups(str(dst_path))
            self.assertTrue(backups)

    def test_instance_guard_copy_then_delete_origin_is_treated_as_rename(self):
        with managed_inventory_root("ln2_instance_guard_copy_del_"):
            src_path = _managed_yaml("copy-del-src")
            dst_path = _managed_yaml("copy-del-dst")

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
        with managed_inventory_root("ln2_instance_guard_rename_") as install_root:
            old_path = _managed_yaml("rename-old")
            new_path = install_root / "inventories" / "rename-new" / "inventory.yaml"

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(old_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            original_id = str((load_yaml(str(old_path)).get("meta") or {}).get("inventory_instance_id") or "")
            old_path.parent.rename(new_path.parent)

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
        with managed_inventory_root("ln2_instance_guard_backfill_"):
            yaml_path = _managed_yaml("backfill-origin")
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
        with managed_inventory_root("ln2_rollback_"):
            yaml_path = _managed_yaml("rollback-latest")

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
        with managed_inventory_root("ln2_write_guard_"):
            yaml_path = _managed_yaml("write-invalid")
            invalid = make_data([make_record(1, box=99, position=1)])

            with self.assertRaises(ValueError) as ctx:
                write_yaml(invalid, path=str(yaml_path))

            self.assertTrue(str(ctx.exception))
            self.assertFalse(yaml_path.exists())

    def test_rollback_yaml_blocks_invalid_backup(self):
        with managed_inventory_root("ln2_rollback_guard_"):
            yaml_path = _managed_yaml("rollback-invalid")

            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            invalid_backup = yaml_path.parent / "backups" / "inventory.invalid.bak"
            invalid_backup.parent.mkdir(parents=True, exist_ok=True)
            invalid_backup.write_text(
                (
                    "meta:\n"
                    "  box_layout:\n"
                    "    rows: 9\n"
                    "    cols: 9\n"
                    "inventory:\n"
                    "  - id: 1\n"
                    "    parent_cell_line: NCCIT\n"
                    "    short_name: bad\n"
                    "    box: 1\n"
                    "    position: null\n"
                    "    frozen_at: 2025-01-01\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                rollback_yaml(
                    path=str(yaml_path),
                    backup_path=str(invalid_backup),
                )

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])


if __name__ == "__main__":
    unittest.main()
