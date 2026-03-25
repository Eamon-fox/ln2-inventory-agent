"""Unit tests for app storage helpers."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import app_storage


class AppStorageTests(unittest.TestCase):
    def test_remap_inventory_yaml_path_preserves_dataset_relative_path(self):
        remapped = app_storage.remap_inventory_yaml_path(
            "/tmp/source/inventories/demo/inventory.yaml",
            source_root="/tmp/source",
            target_root="/tmp/target",
        )
        expected = os.path.abspath(
            os.path.join("/tmp/target", "inventories", "demo", "inventory.yaml")
        )
        self.assertEqual(expected, remapped)

    def test_migrate_data_root_copies_inventories_and_migrate(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            Path(source_dir, "inventories", "demo").mkdir(parents=True, exist_ok=True)
            Path(source_dir, "inventories", "demo", "inventory.yaml").write_text(
                "meta: {}\ninventory: []\n",
                encoding="utf-8",
            )
            Path(source_dir, "migrate", "output").mkdir(parents=True, exist_ok=True)
            Path(source_dir, "migrate", "output", "migration_checklist.md").write_text(
                "# checklist\n",
                encoding="utf-8",
            )

            app_storage.migrate_data_root(source_dir, target_dir)

            self.assertTrue(os.path.isfile(Path(target_dir, "inventories", "demo", "inventory.yaml")))
            self.assertTrue(os.path.isfile(Path(target_dir, "migrate", "output", "migration_checklist.md")))

    def test_migrate_data_root_rewrites_inventory_origin_and_audit_paths(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            dataset_dir = Path(source_dir, "inventories", "demo")
            dataset_dir.mkdir(parents=True, exist_ok=True)
            source_yaml = dataset_dir / "inventory.yaml"
            source_backup = dataset_dir / "backups" / "inventory.yaml.seed.bak"
            source_backup.parent.mkdir(parents=True, exist_ok=True)
            source_backup.write_text("meta: {}\ninventory: []\n", encoding="utf-8")
            source_yaml.write_text(
                yaml.safe_dump(
                    {
                        "meta": {
                            "inventory_instance_id": "demo-instance",
                            "instance_origin_path": str(source_yaml.resolve()),
                        },
                        "inventory": [],
                    },
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                ),
                encoding="utf-8",
            )
            audit_path = dataset_dir / "audit" / "events.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "action": "seed",
                                "yaml_path": str(source_yaml.resolve()),
                                "backup_path": str(source_backup.resolve()),
                            },
                            ensure_ascii=False,
                        ),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            app_storage.migrate_data_root(source_dir, target_dir)

            target_yaml = Path(target_dir, "inventories", "demo", "inventory.yaml")
            target_backup = Path(target_dir, "inventories", "demo", "backups", "inventory.yaml.seed.bak")
            target_audit = Path(target_dir, "inventories", "demo", "audit", "events.jsonl")

            payload = yaml.safe_load(target_yaml.read_text(encoding="utf-8")) or {}
            meta = payload.get("meta") or {}
            self.assertEqual(
                str(target_yaml.resolve()),
                str(Path(str(meta.get("instance_origin_path") or "")).resolve()),
            )
            self.assertEqual("demo-instance", meta.get("inventory_instance_id"))

            lines = [line for line in target_audit.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(lines))
            event = json.loads(lines[0])
            self.assertEqual(
                str(target_yaml.resolve()),
                str(Path(str(event.get("yaml_path") or "")).resolve()),
            )
            self.assertEqual(
                str(target_backup.resolve()),
                str(Path(str(event.get("backup_path") or "")).resolve()),
            )

    def test_migrate_data_root_preserves_blank_and_invalid_audit_lines(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            dataset_dir = Path(source_dir, "inventories", "demo")
            dataset_dir.mkdir(parents=True, exist_ok=True)
            source_yaml = dataset_dir / "inventory.yaml"
            source_yaml.write_text("meta: {}\ninventory: []\n", encoding="utf-8")
            audit_path = dataset_dir / "audit" / "events.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(
                (
                    json.dumps({"yaml_path": str(source_yaml.resolve())}, ensure_ascii=False)
                    + "\n"
                    + "not-json\n"
                    + "\n"
                ),
                encoding="utf-8",
            )

            app_storage.migrate_data_root(source_dir, target_dir)

            target_audit = Path(target_dir, "inventories", "demo", "audit", "events.jsonl")
            content = target_audit.read_text(encoding="utf-8")
            self.assertIn("not-json\n", content)
            self.assertTrue(content.endswith("\n\n"))
            first_line = content.splitlines()[0]
            event = json.loads(first_line)
            self.assertEqual(
                str(Path(target_dir, "inventories", "demo", "inventory.yaml").resolve()),
                str(Path(str(event.get("yaml_path") or "")).resolve()),
            )


if __name__ == "__main__":
    unittest.main()
