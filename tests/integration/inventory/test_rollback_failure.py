"""
Module: test_rollback_failure
Layer: integration/inventory
Covers: lib/tool_api.tool_rollback with corrupted/missing/invalid backups
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import tool_rollback
from lib.yaml_ops import (
    create_yaml_backup,
    load_yaml,
    read_audit_events,
    write_yaml,
)
from tests.managed_paths import ManagedPathTestCase


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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def _write_yaml(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def _read_audit_rows(temp_dir):
    yaml_path = Path(temp_dir) / "inventory.yaml"
    if not yaml_path.exists():
        return []
    return read_audit_events(str(yaml_path))


class TestRollbackCorruptedBackup(ManagedPathTestCase):
    """Rollback with a corrupt (unparseable YAML) backup file."""

    def test_corrupt_backup_returns_error_with_code(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_corrupt_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            corrupt_backup = Path(yaml_path).parent / "backups" / "corrupt.bak"
            corrupt_backup.parent.mkdir(parents=True, exist_ok=True)
            _write_raw(corrupt_backup, "{{not: valid: [yaml")

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(corrupt_backup),
            )

            self.assertFalse(result["ok"])
            self.assertIn(result["error_code"], ("backup_parse_failed", "backup_load_failed"))

    def test_corrupt_backup_preserves_original_data(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_corrupt_preserve_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            original_data = _valid_data([_valid_record()])
            write_yaml(
                original_data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            corrupt_backup = Path(yaml_path).parent / "backups" / "corrupt.bak"
            corrupt_backup.parent.mkdir(parents=True, exist_ok=True)
            _write_raw(corrupt_backup, "not yaml at all: {{{")

            tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(corrupt_backup),
            )

            current = load_yaml(str(yaml_path))
            self.assertEqual(len(current["inventory"]), 1)
            self.assertEqual(current["inventory"][0]["id"], 1)


class TestRollbackEmptyBackup(ManagedPathTestCase):
    """Rollback with an empty backup file."""

    def test_empty_backup_returns_specific_error(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_empty_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            empty_backup = Path(yaml_path).parent / "backups" / "empty.bak"
            empty_backup.parent.mkdir(parents=True, exist_ok=True)
            empty_backup.write_text("", encoding="utf-8")

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(empty_backup),
            )

            self.assertFalse(result["ok"])
            self.assertIn(result["error_code"], ("backup_empty", "backup_load_failed", "backup_parse_failed"))


class TestRollbackMissingBackup(ManagedPathTestCase):
    """Rollback with a backup path that does not exist."""

    def test_missing_backup_returns_not_found(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_missing_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            missing_path = Path(yaml_path).parent / "backups" / "does_not_exist.bak"
            missing_path.parent.mkdir(parents=True, exist_ok=True)

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(missing_path),
            )

            self.assertFalse(result["ok"])
            self.assertIn("not_found", result.get("error_code", ""))


class TestRollbackInvalidIntegrity(ManagedPathTestCase):
    """Rollback with a backup that fails integrity checks."""

    def test_invalid_box_in_backup_blocks_rollback(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_invalid_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bad_backup = Path(yaml_path).parent / "backups" / "bad_integrity.bak"
            bad_backup.parent.mkdir(parents=True, exist_ok=True)
            _write_yaml(bad_backup, _valid_data([_valid_record(box=99)]))

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(bad_backup),
            )

            self.assertFalse(result["ok"])
            self.assertIn(result["error_code"], ("rollback_backup_invalid", "backup_integrity_failed"))

    def test_failed_audit_logged(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_audit_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bad_backup = Path(yaml_path).parent / "backups" / "bad_audit.bak"
            bad_backup.parent.mkdir(parents=True, exist_ok=True)
            _write_yaml(bad_backup, _valid_data([_valid_record(box=99)]))

            tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(bad_backup),
            )

            rows = _read_audit_rows(td)
            rollback_rows = [r for r in rows if r.get("action") == "rollback"]
            self.assertGreaterEqual(len(rollback_rows), 1)
            last_rollback = rollback_rows[-1]
            self.assertEqual("failed", last_rollback.get("status"))


class TestRollbackAlternativeBackups(ManagedPathTestCase):
    """Verify that failed rollback suggests alternative backup points."""

    def test_suggests_alternatives_on_corrupt_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_alt_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record()]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            good_backup = create_yaml_backup(str(yaml_path))
            self.assertIsNotNone(good_backup)

            corrupt_backup = Path(yaml_path).parent / "backups" / "corrupt.bak"
            _write_raw(corrupt_backup, "{{invalid yaml")

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(corrupt_backup),
            )

            self.assertFalse(result["ok"])
            alt = result.get("alternative_backups", [])
            self.assertGreaterEqual(len(alt), 1)
            alt_paths = [a["path"] for a in alt]
            self.assertIn(good_backup, alt_paths)


class TestRollbackSuccessPath(ManagedPathTestCase):
    """Verify successful rollback still works after our changes."""

    def test_rollback_to_valid_backup_succeeds(self):
        with tempfile.TemporaryDirectory(prefix="ln2_rb_success_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _valid_data([_valid_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            backup = create_yaml_backup(str(yaml_path))
            self.assertIsNotNone(backup)

            write_yaml(
                _valid_data([
                    _valid_record(1, box=1, position=1),
                    _valid_record(2, box=1, position=2),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "add", "source": "tests"},
            )

            self.assertEqual(len(load_yaml(str(yaml_path))["inventory"]), 2)

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(backup),
            )

            self.assertTrue(result["ok"])
            restored = load_yaml(str(yaml_path))
            self.assertEqual(len(restored["inventory"]), 1)


if __name__ == "__main__":
    unittest.main()
