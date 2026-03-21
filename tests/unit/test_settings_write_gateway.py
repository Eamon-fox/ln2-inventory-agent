"""Unit tests for settings write gateway."""

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.inventory_paths import create_managed_dataset_yaml_path
from lib.app_storage import clear_session_data_root, set_session_data_root
from lib.settings_write_gateway import persist_custom_fields_update
from lib.yaml_ops import (
    list_yaml_backups,
    load_yaml,
    read_audit_events,
    write_yaml,
)


@contextmanager
def _managed_inventory_root(prefix):
    with tempfile.TemporaryDirectory(prefix=prefix) as install_dir:
        set_session_data_root(install_dir)
        try:
            yield Path(install_dir)
        finally:
            clear_session_data_root()


def _managed_yaml(dataset_name):
    return Path(create_managed_dataset_yaml_path(dataset_name))


class SettingsWriteGatewayTests(unittest.TestCase):
    def test_persist_custom_fields_update_creates_backup_and_audit(self):
        with _managed_inventory_root("ln2_settings_gateway_"):
            yaml_path = _managed_yaml("gateway-success")
            seed = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 2, "box_numbers": [1, 2]},
                    "custom_fields": [{"key": "cell_line", "label": "Cell Line", "type": "str"}],
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
            write_yaml(seed, path=str(yaml_path), audit_meta={"action": "seed", "source": "tests"})

            pending = load_yaml(str(yaml_path)) or {}
            pending_meta = dict(pending.get("meta") or {})
            pending_meta["custom_fields"] = [
                {"key": "type", "label": "Type", "type": "str"},
            ]
            pending_meta["display_key"] = "type"
            pending_meta["color_key"] = "type"
            pending_meta.pop("cell_line_required", None)
            pending_meta.pop("cell_line_options", None)
            pending["meta"] = pending_meta
            pending["inventory"][0]["type"] = pending["inventory"][0].pop("cell_line")

            result = persist_custom_fields_update(
                yaml_path=str(yaml_path),
                pending_data=pending,
                audit_details={
                    "op": "edit_custom_fields",
                    "added_keys": ["type"],
                    "removed_keys": ["cell_line"],
                    "renames": [{"from": "cell_line", "to": "type"}],
                },
            )

            self.assertTrue(result.get("ok"), result)
            backups = list_yaml_backups(str(yaml_path))
            self.assertTrue(backups)

            events = read_audit_events(str(yaml_path))
            actions = [str(ev.get("action") or "") for ev in events]
            self.assertIn("backup", actions)
            self.assertIn("edit_custom_fields", actions)
            edit_events = [ev for ev in events if str(ev.get("action")) == "edit_custom_fields"]
            self.assertTrue(edit_events)
            last_edit = edit_events[-1]
            details = (last_edit.get("details") or {})
            self.assertEqual("edit_custom_fields", details.get("op"))

    def test_persist_custom_fields_update_blocks_when_backup_creation_fails(self):
        with _managed_inventory_root("ln2_settings_gateway_fail_"):
            yaml_path = _managed_yaml("gateway-fail")
            seed = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9, "box_count": 2, "box_numbers": [1, 2]},
                    "custom_fields": [{"key": "cell_line", "label": "Cell Line", "type": "str"}],
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
            write_yaml(seed, path=str(yaml_path), audit_meta={"action": "seed", "source": "tests"})
            before = load_yaml(str(yaml_path))

            with patch("lib.settings_write_gateway.create_yaml_backup", return_value=None):
                result = persist_custom_fields_update(
                    yaml_path=str(yaml_path),
                    pending_data=seed,
                    audit_details={"op": "edit_custom_fields"},
                )

            self.assertFalse(result.get("ok"))
            self.assertEqual("backup_create_failed", result.get("error_code"))
            after = load_yaml(str(yaml_path))
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
