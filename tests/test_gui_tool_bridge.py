import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.tool_bridge import GuiToolBridge


class GuiToolBridgeTests(unittest.TestCase):
    def _write_inventory(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "inventory.yaml"
        path.write_text(
            """meta:
  box_layout:
    rows: 9
    cols: 9
inventory:
  - id: 5
    parent_cell_line: K562
    short_name: K562_clone12
    box: 1
    positions: [30]
    frozen_at: 2026-02-10
    plasmid_name: EGFP
    plasmid_id: P-001
""",
            encoding="utf-8",
        )
        return tmp, path

    def test_query_inventory_accepts_legacy_filter_names(self):
        tmp, path = self._write_inventory()
        self.addCleanup(tmp.cleanup)
        bridge = GuiToolBridge()

        response = bridge.query_inventory(
            str(path),
            parent_cell_line="K562",
            short_name="clone12",
            plasmid_name="EGFP",
            plasmid_id="P-001",
            box=1,
            position=30,
        )

        self.assertTrue(response.get("ok"))
        self.assertEqual(1, response.get("result", {}).get("count"))

    def test_query_inventory_ignores_unknown_filter_names(self):
        """Unknown field filters don't crash, they just filter (no match = 0 results)."""
        tmp, path = self._write_inventory()
        self.addCleanup(tmp.cleanup)
        bridge = GuiToolBridge()

        response = bridge.query_inventory(str(path), cell="K562", unknown="ignored")

        self.assertTrue(response.get("ok"))
        # 'cell' and 'unknown' are not actual record keys, so no records match
        self.assertEqual(0, response.get("result", {}).get("count"))

    def test_export_inventory_csv_writes_full_snapshot(self):
        tmp, path = self._write_inventory()
        self.addCleanup(tmp.cleanup)
        bridge = GuiToolBridge()

        output_path = Path(tmp.name) / "full_export.csv"
        response = bridge.export_inventory_csv(str(path), str(output_path))

        self.assertTrue(response.get("ok"))
        self.assertTrue(output_path.exists())

        with output_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))

        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual("id", rows[0][0])
        self.assertIn("cell_line", rows[0])
        self.assertEqual("5", rows[1][0])


if __name__ == "__main__":
    unittest.main()
