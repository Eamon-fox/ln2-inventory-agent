"""
Module: test_backup_throttle
Layer: integration/inventory
Covers: lib/yaml_ops.create_yaml_backup

锁定备份节流契约（详见 docs/modules/13-库存核心.md「备份与审计契约」）：

- 内容哈希未变时，`create_yaml_backup` 跳过 `shutil.copy2`，复用上一份
  备份路径。
- 时间节流窗口（默认 30 秒、`LN2_BACKUP_THROTTLE_SECONDS` 可配置）内的
  重复调用被合并成一次。
- `force=True` 或 `throttle_seconds=0` 强制写出新备份，用于专门测试或
  "I really want a snapshot now" 的调用点。
- 节流状态存在 backup 目录下的 ``.last_backup.json``，原子写入保证崩溃安
  全。
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.managed_paths import ManagedPathTestCase

from lib.yaml_ops import create_yaml_backup, list_yaml_backups


class BackupThrottleTests(ManagedPathTestCase):
    def setUp(self):
        super().setUp()
        self._prev_env = os.environ.pop("LN2_BACKUP_THROTTLE_SECONDS", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("LN2_BACKUP_THROTTLE_SECONDS", None)
        else:
            os.environ["LN2_BACKUP_THROTTLE_SECONDS"] = self._prev_env
        super().tearDown()

    def _make_yaml(self, name, payload="meta: {}\ninventory: []\n"):
        yaml_path = self.ensure_dataset_yaml(name)
        Path(yaml_path).write_text(payload, encoding="utf-8")
        return yaml_path

    def test_unchanged_content_skips_new_backup(self):
        yaml_path = self._make_yaml("throttle_unchanged")
        b1 = create_yaml_backup(str(yaml_path))
        self.assertIsNotNone(b1)
        b2 = create_yaml_backup(str(yaml_path))
        self.assertEqual(b1, b2, "hash-identical content must reuse prior backup")
        self.assertEqual(len(list_yaml_backups(str(yaml_path))), 1)

    def test_throttle_window_reuses_prior_backup_even_if_content_changed(self):
        os.environ["LN2_BACKUP_THROTTLE_SECONDS"] = "60"
        yaml_path = self._make_yaml("throttle_window")
        b1 = create_yaml_backup(str(yaml_path))
        self.assertIsNotNone(b1)

        Path(yaml_path).write_text(
            "meta: {}\ninventory:\n  - {id: 1}\n", encoding="utf-8"
        )
        b2 = create_yaml_backup(str(yaml_path))
        self.assertEqual(b1, b2, "within throttle window, second call must not create a new file")
        self.assertEqual(len(list_yaml_backups(str(yaml_path))), 1)

    def test_throttle_zero_disables_time_based_skip(self):
        os.environ["LN2_BACKUP_THROTTLE_SECONDS"] = "0"
        yaml_path = self._make_yaml("throttle_zero")
        b1 = create_yaml_backup(str(yaml_path))
        self.assertIsNotNone(b1)
        Path(yaml_path).write_text(
            "meta: {}\ninventory:\n  - {id: 1}\n", encoding="utf-8"
        )
        b2 = create_yaml_backup(str(yaml_path))
        self.assertNotEqual(b1, b2)

    def test_force_bypasses_all_throttling(self):
        yaml_path = self._make_yaml("throttle_force")
        b1 = create_yaml_backup(str(yaml_path))
        b2 = create_yaml_backup(str(yaml_path), force=True)
        self.assertNotEqual(b1, b2)

    def test_state_file_records_hash_path_mtime(self):
        yaml_path = self._make_yaml("throttle_state")
        backup_path = create_yaml_backup(str(yaml_path))
        self.assertIsNotNone(backup_path)
        state_file = Path(backup_path).parent / ".last_backup.json"
        self.assertTrue(state_file.exists())
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("path"), backup_path)
        self.assertTrue(payload.get("hash"))
        self.assertIsInstance(payload.get("mtime"), (int, float))

    def test_expired_window_plus_content_change_creates_new_backup(self):
        os.environ["LN2_BACKUP_THROTTLE_SECONDS"] = "1"
        yaml_path = self._make_yaml("throttle_expire")
        b1 = create_yaml_backup(str(yaml_path))
        self.assertIsNotNone(b1)

        state_file = Path(b1).parent / ".last_backup.json"
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        payload["mtime"] = time.time() - 120
        state_file.write_text(json.dumps(payload), encoding="utf-8")

        Path(yaml_path).write_text(
            "meta: {}\ninventory:\n  - {id: 2}\n", encoding="utf-8"
        )
        b2 = create_yaml_backup(str(yaml_path))
        self.assertNotEqual(b1, b2)


if __name__ == "__main__":
    unittest.main()
