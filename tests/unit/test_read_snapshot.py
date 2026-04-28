"""Unit tests for YAML read snapshot caching."""

import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.yaml_ops import (
    clear_read_snapshot,
    current_read_snapshot_id,
    load_yaml,
    read_snapshot_context,
)


class ReadSnapshotTests(unittest.TestCase):
    def test_read_snapshot_reuses_disk_load_and_returns_deepcopy(self):
        real_open = builtins.open
        with tempfile.TemporaryDirectory() as tmp:
            yaml_path = Path(tmp) / "inventory.yaml"
            yaml_path.write_text(
                "meta:\n  box_layout:\n    rows: 9\n    cols: 9\ninventory: []\n",
                encoding="utf-8",
            )

            try:
                with patch("builtins.open", wraps=real_open) as open_mock:
                    with read_snapshot_context("unit-snapshot"):
                        first = load_yaml(str(yaml_path))
                        first["inventory"].append({"id": 1})
                        second = load_yaml(str(yaml_path))
                        self.assertEqual("unit-snapshot", current_read_snapshot_id())

                opened_inventory = [
                    call
                    for call in open_mock.call_args_list
                    if str(call.args[0]).endswith("inventory.yaml")
                ]
                self.assertEqual(1, len(opened_inventory))
                self.assertEqual([], second["inventory"])
            finally:
                clear_read_snapshot("unit-snapshot")


if __name__ == "__main__":
    unittest.main()
