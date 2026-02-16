import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.yaml_ops import (
    get_audit_log_path,
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


class YamlOpsWriteTests(unittest.TestCase):
    def test_write_yaml_persists_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_yaml_ops_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = make_data([])

            write_yaml(data, path=str(yaml_path))

            self.assertTrue(yaml_path.exists())
            loaded = load_yaml(str(yaml_path))
            self.assertEqual([], loaded.get("inventory", []))


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
            self.assertIn("actor_type", last)
            self.assertIn("channel", last)
            self.assertTrue(last.get("session_id"))
            self.assertTrue(last.get("trace_id"))
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

    def test_rollback_yaml_restores_latest_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rollback_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"

            data_v1 = make_data([make_record(1, box=1, position=1)])
            data_v2 = make_data([make_record(1, box=1, position=9)])

            write_yaml(data_v1, path=str(yaml_path))
            write_yaml(data_v2, path=str(yaml_path))

            current = load_yaml(str(yaml_path))
            self.assertEqual(9, current["inventory"][0]["position"])

            result = rollback_yaml(
                path=str(yaml_path),
                audit_meta={"source": "tests"},
            )

            restored = load_yaml(str(yaml_path))
            self.assertEqual(1, restored["inventory"][0]["position"])
            self.assertTrue(Path(result["restored_from"]).exists())
            self.assertTrue(Path(result["snapshot_before_rollback"]).exists())

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
