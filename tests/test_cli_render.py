import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.cli_render import format_record_verbose, iter_entry_yaml_lines, print_raw_entries


class CliRenderTests(unittest.TestCase):
    def test_format_record_verbose_contains_core_fields(self):
        record = {
            "id": 7,
            "parent_cell_line": "K562",
            "short_name": "clone-7",
            "plasmid_name": "pA",
            "plasmid_id": "PA-7",
            "box": 2,
            "positions": [3, 4],
            "frozen_at": "2026-02-12",
            "thaw_log": "Takeout@2026-02-13",
            "note": "important",
        }

        text = format_record_verbose(record)

        self.assertIn("K562", text)
        self.assertIn("clone-7", text)
        self.assertIn("Takeout@2026-02-13", text)
        self.assertIn("important", text)

    def test_iter_entry_yaml_lines_strips_yaml_list_prefix(self):
        entry = {"id": 1, "parent_cell_line": "K562", "positions": [1, 2]}
        lines = list(iter_entry_yaml_lines(entry))

        self.assertTrue(lines)
        self.assertFalse(lines[0].startswith("- "))
        self.assertIn("id: 1", lines[0])

    def test_print_raw_entries_emits_split_records(self):
        entries = [
            {"id": 1, "parent_cell_line": "A"},
            {"id": 2, "parent_cell_line": "B"},
        ]

        buf = io.StringIO()
        with redirect_stdout(buf):
            print_raw_entries(entries)
        output = buf.getvalue()

        self.assertIn("# === ID 1 ===", output)
        self.assertIn("# === ID 2 ===", output)
        self.assertIn("\n\n# === ID 2 ===", output)


if __name__ == "__main__":
    unittest.main()
