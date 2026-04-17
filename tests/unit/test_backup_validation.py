"""
Module: test_backup_validation
Layer: unit
Covers: lib/yaml_ops.validate_backup_file, list_alternative_backups
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.managed_paths import ManagedPathTestCase

from lib.yaml_ops import (
    create_yaml_backup,
    list_alternative_backups,
    validate_backup_file,
    write_yaml,
)


def _valid_data(records=None):
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "cell_line_required": False,
        },
        "inventory": records or [],
    }


def _valid_record(rec_id=1, box=1, position=1):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position,
        "frozen_at": "2025-01-01",
    }


def _write_raw(path, content):
    Path(path).write_text(content, encoding="utf-8")


def _write_yaml(path, data):
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


class TestValidateBackupFile(ManagedPathTestCase):
    """Unit tests for validate_backup_file."""

    def test_valid_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_valid_") as td:
            bp = Path(td) / "inventory.yaml.20250101-120000.bak"
            _write_yaml(bp, _valid_data([_valid_record()]))

            result = validate_backup_file(str(bp))

            self.assertTrue(result["valid"])
            self.assertIsNone(result["error"])
            self.assertIsNone(result["error_code"])
            self.assertIsNotNone(result["data"])
            self.assertIn("inventory", result["data"])

    def test_nonexistent_file(self):
        result = validate_backup_file("/no/such/path/backup.bak")

        self.assertFalse(result["valid"])
        self.assertEqual("backup_not_found", result["error_code"])
        self.assertIn("not found", result["error"])

    def test_empty_file(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_empty_") as td:
            bp = Path(td) / "empty.bak"
            bp.write_text("", encoding="utf-8")

            result = validate_backup_file(str(bp))

            self.assertFalse(result["valid"])
            self.assertEqual("backup_empty", result["error_code"])
            self.assertIn("empty", result["error"].lower())

    def test_invalid_yaml(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_badyaml_") as td:
            bp = Path(td) / "corrupt.bak"
            _write_raw(bp, "{{{{not valid yaml: [}")

            result = validate_backup_file(str(bp))

            self.assertFalse(result["valid"])
            self.assertEqual("backup_parse_failed", result["error_code"])

    def test_yaml_not_dict(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_list_") as td:
            bp = Path(td) / "list.bak"
            _write_raw(bp, "- item1\n- item2\n")

            result = validate_backup_file(str(bp))

            self.assertFalse(result["valid"])
            self.assertEqual("backup_invalid_structure", result["error_code"])
            self.assertIn("mapping", result["error"].lower())

    def test_missing_inventory_key(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_nokey_") as td:
            bp = Path(td) / "noinventory.bak"
            _write_yaml(bp, {"meta": {"box_layout": {"rows": 9, "cols": 9}}})

            result = validate_backup_file(str(bp))

            self.assertFalse(result["valid"])
            self.assertEqual("backup_missing_inventory", result["error_code"])

    def test_integrity_failure(self):
        """Backup with invalid box number should fail integrity check."""
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_integrity_") as td:
            bp = Path(td) / "badbox.bak"
            _write_yaml(bp, _valid_data([_valid_record(box=99)]))

            result = validate_backup_file(str(bp))

            self.assertFalse(result["valid"])
            self.assertEqual("backup_integrity_failed", result["error_code"])

    def test_directory_not_file(self):
        with tempfile.TemporaryDirectory(prefix="ln2_vbf_dir_") as td:
            result = validate_backup_file(td)

            self.assertFalse(result["valid"])
            self.assertEqual("backup_not_file", result["error_code"])


class TestListAlternativeBackups(ManagedPathTestCase):
    """Unit tests for list_alternative_backups."""

    def test_excludes_specified_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_alt_exclude_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_yaml(yaml_path, _valid_data())
            write_yaml(_valid_data(), path=str(yaml_path))

            # force=True produces two distinct backups; the throttle-based
            # default would short-circuit the second call.
            b1 = create_yaml_backup(str(yaml_path), force=True)
            self.assertIsNotNone(b1)
            b2 = create_yaml_backup(str(yaml_path), force=True)
            self.assertIsNotNone(b2)
            self.assertNotEqual(b1, b2)

            alternatives = list_alternative_backups(str(yaml_path), exclude_path=b1)

            alt_paths = [a["path"] for a in alternatives]
            self.assertNotIn(b1, alt_paths)
            self.assertIn(b2, alt_paths)

    def test_empty_when_no_backups(self):
        with tempfile.TemporaryDirectory(prefix="ln2_alt_empty_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_yaml(yaml_path, _valid_data())
            write_yaml(_valid_data(), path=str(yaml_path), auto_backup=False)

            alternatives = list_alternative_backups(str(yaml_path))

            self.assertEqual([], alternatives)

    def test_respects_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_alt_limit_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_yaml(yaml_path, _valid_data())
            write_yaml(_valid_data(), path=str(yaml_path))

            for _ in range(5):
                create_yaml_backup(str(yaml_path))

            alternatives = list_alternative_backups(str(yaml_path), limit=2)

            self.assertLessEqual(len(alternatives), 2)

    def test_entries_have_path_and_mtime(self):
        with tempfile.TemporaryDirectory(prefix="ln2_alt_fields_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            _write_yaml(yaml_path, _valid_data())
            write_yaml(_valid_data(), path=str(yaml_path))

            create_yaml_backup(str(yaml_path))

            alternatives = list_alternative_backups(str(yaml_path))

            self.assertGreaterEqual(len(alternatives), 1)
            entry = alternatives[0]
            self.assertIn("path", entry)
            self.assertIn("mtime", entry)
            self.assertTrue(os.path.exists(entry["path"]))


if __name__ == "__main__":
    unittest.main()
