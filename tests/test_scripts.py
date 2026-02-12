"""
Integration tests for scripts/ layer of ln2-inventory-agent.

Tests CLI scripts by executing them via subprocess and verifying:
- Exit codes
- Output content
- YAML changes
- Dry-run behavior
- Help messages
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Test fixtures
def make_record(rec_id=1, box=1, positions=None, parent_cell_line="K562",
                short_name=None, frozen_at="2025-01-01", plasmid_name=None,
                plasmid_id=None, note=None, thaw_log=None):
    """Create a sample inventory record."""
    if positions is None:
        positions = [1]
    if short_name is None:
        short_name = f"rec-{rec_id}"

    record = {
        "id": rec_id,
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "box": box,
        "positions": positions,
        "frozen_at": frozen_at,
    }
    if plasmid_name is not None:
        record["plasmid_name"] = plasmid_name
    if plasmid_id is not None:
        record["plasmid_id"] = plasmid_id
    if note is not None:
        record["note"] = note
    if thaw_log is not None:
        record["thaw_log"] = thaw_log
    return record


def make_data(records, valid_cell_lines=None):
    """Create a complete inventory data dictionary."""
    data = {
        "meta": {"version": "1.0", "box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }
    if valid_cell_lines:
        data["schema"] = {"valid_cell_lines": valid_cell_lines}
    return data


def write_yaml_data(path, data):
    """Helper to write YAML data to a file.

    Args:
        path: Path object to write to
        data: Data to write (list of records or complete data dict)

    Returns:
        The written data for verification
    """
    # If data is a list, wrap it in the full structure
    if isinstance(data, list):
        yaml_content = make_data(data)
    else:
        yaml_content = data

    yaml_str = yaml.dump(yaml_content, allow_unicode=True,
                        default_flow_style=False, sort_keys=False)
    path.write_text(yaml_str, encoding="utf-8")
    return yaml_content


# ── add_entry.py Tests ───────────────────────────────────────


class AddEntryScriptTests(unittest.TestCase):
    """Tests for add_entry.py CLI script."""

    def test_add_entry_basic(self):
        """Test add_entry.py with basic parameters."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test-clone",
                    "--box", "1",
                    "--positions", "1,2",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            # Verify data was written
            data = yaml.safe_load(yaml_path.read_text())
            self.assertEqual(1, len(data["inventory"]))
            rec = data["inventory"][0]
            self.assertEqual("K562", rec["parent_cell_line"])
            self.assertEqual("test-clone", rec["short_name"])
            self.assertEqual([1, 2], rec["positions"])

    def test_add_entry_dry_run(self):
        """Test add_entry.py with dry-run flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test-clone",
                    "--box", "1",
                    "--positions", "1,2",
                    "--frozen-at", "2026-02-10",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("预览", result.stdout)
            # Verify no data was written
            data = yaml.safe_load(yaml_path.read_text())
            self.assertEqual(0, len(data["inventory"]))

    def test_add_entry_help(self):
        """Test add_entry.py --help."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "add_entry.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )

        self.assertEqual(0, result.returncode)
        self.assertIn("--parent-cell-line", result.stdout)

    def test_add_entry_with_plasmid(self):
        """Test add_entry.py with plasmid information."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test",
                    "--plasmid-name", "pGEMT-test",
                    "--plasmid-id", "p001",
                    "--note", "test note",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            data = yaml.safe_load(yaml_path.read_text())
            rec = data["inventory"][0]
            self.assertEqual("pGEMT-test", rec["plasmid_name"])
            self.assertEqual("p001", rec["plasmid_id"])
            self.assertEqual("test note", rec["note"])

    def test_add_entry_position_range(self):
        """Test add_entry.py with position range."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test",
                    "--box", "1",
                    "--positions", "10-12",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            data = yaml.safe_load(yaml_path.read_text())
            rec = data["inventory"][0]
            self.assertEqual([10, 11, 12], rec["positions"])

    def test_add_entry_invalid_box(self):
        """Test add_entry.py with invalid box."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test",
                    "--box", "99",  # Invalid box
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)

    def test_add_entry_position_conflict(self):
        """Test add_entry.py with position conflict."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "test2",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("位置冲突", result.stdout)

    def test_add_entry_missing_required_arg(self):
        """Test add_entry.py missing required argument."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    # Missing --short-name, --box, --positions, --frozen-at
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── record_thaw.py Tests ───────────────────────────────────────


class RecordThawScriptTests(unittest.TestCase):
    """Tests for record_thaw.py CLI script."""

    def test_record_thaw_takeout_valid(self):
        """Test record_thaw.py with valid takeout."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1, 2])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            data = yaml.safe_load(yaml_path.read_text())
            # The script uses thaw_events instead of thaw_log
            self.assertIn("thaw_events", data["inventory"][0])
            self.assertEqual([2], data["inventory"][0]["positions"])

    def test_record_thaw_with_note(self):
        """Test record_thaw.py with note."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1, 2])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--date", "2026-02-10",
                    "--note", "test thaw",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("test thaw", result.stdout)

    def test_record_thaw_move_valid(self):
        """Test record_thaw.py with move operation."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1, 2])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--to-position", "50",
                    "--action", "move",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_record_thaw_move_missing_to_position(self):
        """Test record_thaw.py move without to_position."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--action", "move",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("to-position", result.stdout)

    def test_record_thaw_invalid_position(self):
        """Test record_thaw.py with position not in record."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "99",  # Not in record
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)

    def test_record_thaw_dry_run(self):
        """Test record_thaw.py dry-run mode."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1, 2])
            ])
            original_data = yaml.safe_load(yaml_path.read_text())

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--date", "2026-02-10",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("预览", result.stdout)
            current_data = yaml.safe_load(yaml_path.read_text())
            self.assertEqual(original_data, current_data)

    def test_record_thaw_nonexistent_id(self):
        """Test record_thaw.py with non-existent ID."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "999",
                    "--position", "1",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── batch_thaw.py Tests ───────────────────────────────────────


class BatchThawScriptTests(unittest.TestCase):
    """Tests for batch_thaw.py CLI script."""

    def test_batch_thaw_valid(self):
        """Test batch_thaw.py with valid entries."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1]),
                make_record(2, positions=[2]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "1:1,2:2",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("2 条记录", result.stdout)

    def test_batch_thaw_with_note(self):
        """Test batch_thaw.py with note."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1]),
                make_record(2, positions=[2]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "1:1,2:2",
                    "--date", "2026-02-10",
                    "--note", "batch thaw test",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("batch thaw test", result.stdout)

    def test_batch_thaw_move(self):
        """Test batch_thaw.py with move entries."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "1:1->5",  # Move 1 to 5
                    "--date", "2026-02-10",
                    "--action", "move",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_batch_thaw_invalid_format(self):
        """Test batch_thaw.py with invalid entry format."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "invalid-format",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)

    def test_batch_thaw_dry_run(self):
        """Test batch_thaw.py dry-run mode."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1])
            ])
            original_data = yaml.safe_load(yaml_path.read_text())

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "1:1",
                    "--date", "2026-02-10",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            current_data = yaml.safe_load(yaml_path.read_text())
            self.assertEqual(original_data, current_data)

    def test_batch_thaw_nonexistent_id(self):
        """Test batch_thaw.py with non-existent ID."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "999:1",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── query_inventory.py Tests ───────────────────────────────────────


class QueryInventoryScriptTests(unittest.TestCase):
    """Tests for query_inventory.py CLI script."""

    def test_query_inventory_basic(self):
        """Test query_inventory.py basic query."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test1"),
                make_record(2, short_name="test2"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_inventory_with_cell(self):
        """Test query_inventory.py with cell filter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, parent_cell_line="K562"),
                make_record(2, parent_cell_line="HEK293T"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--cell", "K562",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("K562", result.stdout)

    def test_query_inventory_with_box(self):
        """Test query_inventory.py with box filter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1),
                make_record(2, box=2),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--box", "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("box=1", result.stdout)

    def test_query_inventory_empty(self):
        """Test query_inventory.py --empty."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1, 2])
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--empty",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("空闲位置", result.stdout)

    def test_query_inventory_verbose(self):
        """Test query_inventory.py with verbose output."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, note="test note", plasmid_name="test-plasmid"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("test note", result.stdout)

    def test_query_inventory_no_matches(self):
        """Test query_inventory.py with no matches."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, parent_cell_line="K562"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--cell", "NONEXISTENT",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── query_recent.py Tests ─────────────────────────────────────


class QueryRecentScriptTests(unittest.TestCase):
    """Tests for query_recent.py CLI script."""

    def test_query_recent_frozen(self):
        """Test query_recent.py --frozen."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_recent_days(self):
        """Test query_recent.py with days parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                    "--days", "30",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("30 天", result.stdout)

    def test_query_recent_count(self):
        """Test query_recent.py with count parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(i, frozen_at=f"2026-02-{i:02d}") for i in range(1, 16)
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                    "--count", "5",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("5 条", result.stdout)

    def test_query_recent_verbose(self):
        """Test query_recent.py with verbose output."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, plasmid_name="test-plasmid", note="test note"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("test-plasmid", result.stdout)

    def test_query_recent_raw(self):
        """Test query_recent.py with raw output."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                    "--raw",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("原始", result.stdout)

    def test_query_recent_no_results(self):
        """Test query_recent.py with no results."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_recent.py"),
                    "--yaml", str(yaml_path),
                    "--frozen",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── search.py Tests ───────────────────────────────────────────


class SearchScriptTests(unittest.TestCase):
    """Tests for search.py CLI script."""

    def test_search_basic(self):
        """Test search.py basic search."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test-tag"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "search.py"),
                    "--yaml", str(yaml_path),
                    "tag",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_search_case_insensitive(self):
        """Test search.py case-insensitive."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="TEST-UPPER"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "search.py"),
                    "--yaml", str(yaml_path),
                    "test-upper",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_search_verbose(self):
        """Test search.py with verbose output."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, plasmid_name="test-plasmid", note="test note"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "search.py"),
                    "--yaml", str(yaml_path),
                    "test",
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("test-plasmid", result.stdout)

    def test_search_no_results(self):
        """Test search.py with no matching results."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "search.py"),
                    "--yaml", str(yaml_path),
                    "NonexistentTerm",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── smart_search.py Tests ───────────────────────────────────────


class SmartSearchScriptTests(unittest.TestCase):
    """Tests for smart_search.py CLI script."""

    def test_smart_search_basic(self):
        """Test smart_search.py basic search."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test-clone"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "smart_search.py"),
                    "--yaml", str(yaml_path),
                    "test",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_smart_search_keywords(self):
        """Test smart_search.py with keywords flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="k562-test"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "smart_search.py"),
                    "--yaml", str(yaml_path),
                    "-k", "k562 test",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_smart_search_raw(self):
        """Test smart_search.py with raw output."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test-raw"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "smart_search.py"),
                    "--yaml", str(yaml_path),
                    "test-raw",
                    "--raw",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_smart_search_max(self):
        """Test smart_search.py with max limit."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(i, short_name=f"test-{i}") for i in range(100)
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "smart_search.py"),
                    "--yaml", str(yaml_path),
                    "test",
                    "--max", "10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_smart_search_no_results(self):
        """Test smart_search.py with no matches."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "smart_search.py"),
                    "--yaml", str(yaml_path),
                    "nonexistent",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── stats.py Tests ───────────────────────────────────────────


class StatsScriptTests(unittest.TestCase):
    """Tests for stats.py CLI script."""

    def test_stats_basic(self):
        """Test stats.py basic execution."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1, 2]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "stats.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("液氮罐库存统计", result.stdout)

    def test_stats_visual(self):
        """Test stats.py --visual flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, positions=[1]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "stats.py"),
                    "--yaml", str(yaml_path),
                    "--visual",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_stats_box(self):
        """Test stats.py with specific box."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "stats.py"),
                    "--yaml", str(yaml_path),
                    "--box", "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("盒子 1", result.stdout)

    def test_stats_empty(self):
        """Test stats.py with empty inventory."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "stats.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)


# ── recommend_position.py Tests ───────────────────────────────────


class RecommendPositionScriptTests(unittest.TestCase):
    """Tests for recommend_position.py CLI script."""

    def test_recommend_position_basic(self):
        """Test recommend_position.py basic execution."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recommend_position.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_recommend_position_count(self):
        """Test recommend_position.py with count parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recommend_position.py"),
                    "--yaml", str(yaml_path),
                    "--count", "5",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_recommend_position_box(self):
        """Test recommend_position.py with box preference."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recommend_position.py"),
                    "--yaml", str(yaml_path),
                    "--box", "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_recommend_position_invalid_count(self):
        """Test recommend_position.py with invalid count."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recommend_position.py"),
                    "--yaml", str(yaml_path),
                    "--count", "0",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── validate.py Tests ───────────────────────────────────────────


class ValidateScriptTests(unittest.TestCase):
    """Tests for validate.py CLI script."""

    def test_validate_valid_data(self):
        """Test validate.py with valid data."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_validate_empty(self):
        """Test validate.py with empty inventory."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_validate_strict(self):
        """Test validate.py with strict mode."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate.py"),
                    "--yaml", str(yaml_path),
                    "--strict",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)


# ── rollback.py Tests ───────────────────────────────────────────


class RollbackScriptTests(unittest.TestCase):
    """Tests for rollback.py CLI script."""

    def test_rollback_list(self):
        """Test rollback.py --list."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "rollback.py"),
                    "--yaml", str(yaml_path),
                    "--list",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_rollback_no_backups(self):
        """Test rollback.py with no backups."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "rollback.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("备份", result.stdout)


# ── show_raw.py Tests ───────────────────────────────────────


class ShowRawScriptTests(unittest.TestCase):
    """Tests for show_raw.py CLI script."""

    def test_show_raw_valid(self):
        """Test show_raw.py with valid ID."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, note="test note"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "show_raw.py"),
                    "--yaml", str(yaml_path),
                    "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("ID 1", result.stdout)
            self.assertIn("test note", result.stdout)

    def test_show_raw_multiple(self):
        """Test show_raw.py with multiple IDs."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, short_name="test1"),
                make_record(2, short_name="test2"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "show_raw.py"),
                    "--yaml", str(yaml_path),
                    "1",
                    "2",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("ID 1", result.stdout)
            self.assertIn("ID 2", result.stdout)

    def test_show_raw_invalid_id(self):
        """Test show_raw.py with invalid ID."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "show_raw.py"),
                    "--yaml", str(yaml_path),
                    "999",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)


# ── timeline.py Tests ───────────────────────────────────────


class TimelineScriptTests(unittest.TestCase):
    """Tests for timeline.py CLI script."""

    def test_timeline_basic(self):
        """Test timeline.py basic execution."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("[TIMELINE]", result.stdout)

    def test_timeline_days(self):
        """Test timeline.py with days parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                    "--days", "7",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("[TIMELINE]", result.stdout)

    def test_timeline_all(self):
        """Test timeline.py --all flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                    "--all",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_timeline_verbose(self):
        """Test timeline.py --verbose flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_timeline_summary(self):
        """Test timeline.py --summary flag."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, frozen_at="2026-02-10"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                    "--summary",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("[SUMMARY]", result.stdout)

    def test_timeline_empty(self):
        """Test timeline.py with empty inventory."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)


# ── check_conflicts.py Tests ─────────────────────────────────────


class CheckConflictsScriptTests(unittest.TestCase):
    """Tests for check_conflicts.py CLI script."""

    def test_check_conflicts_basic(self):
        """Test check_conflicts.py with no conflicts."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1]),
                make_record(2, box=2, positions=[2]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_conflicts.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("no active conflicts", result.stdout)

    def test_check_conflicts_with_conflicts(self):
        """Test check_conflicts.py with position conflicts."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            # Create conflict manually by writing raw YAML
            yaml_content = """
meta:
  version: 1.0
  box_layout:
    rows: 9
    cols: 9
inventory:
  - id: 1
    parent_cell_line: K562
    short_name: test1
    box: 1
    positions:
      - 1
    frozen_at: 2026-02-01
  - id: 2
    parent_cell_line: K562
    short_name: test2
    box: 1
    positions:
      - 1
    frozen_at: 2026-02-01
"""
            yaml_path.write_text(yaml_content)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_conflicts.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Returns non-zero when conflicts found
            self.assertNotEqual(0, result.returncode)
            self.assertIn("active_conflicts", result.stdout)

    def test_check_conflicts_max(self):
        """Test check_conflicts.py with max limit."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, box=1, positions=[1]),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_conflicts.py"),
                    "--yaml", str(yaml_path),
                    "--max", "2",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)


# ── query_thaw.py Tests ───────────────────────────────────────


class QueryThawScriptTests(unittest.TestCase):
    """Tests for query_thaw.py CLI script."""

    def test_query_thaw_basic(self):
        """Test query_thaw.py basic query."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, thaw_log="2026-02-10 取出 位置[1]"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_thaw_by_date(self):
        """Test query_thaw.py with date parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, thaw_log="2026-02-10 取出 位置[1]"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("2026-02-10", result.stdout)

    def test_query_thaw_by_days(self):
        """Test query_thaw.py with days parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, thaw_log="2026-02-10 取出 位置[1]"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--days", "30",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_thaw_by_action(self):
        """Test query_thaw.py with action parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, thaw_log="2026-02-10 复苏 位置[1]"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--action", "复苏",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_thaw_date_range(self):
        """Test query_thaw.py with date range."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [
                make_record(1, thaw_log="2026-02-05 取出 位置[1]"),
                make_record(2, thaw_log="2026-02-10 取出 位置[2]"),
            ])

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--start-date", "2026-02-01",
                    "--end-date", "2026-02-28",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_query_thaw_max(self):
        """Test query_thaw.py with max limit."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            records = [
                make_record(i, thaw_log=f"2026-02-{i:02d} 取出 位置[{i}]")
                for i in range(1, 11)
            ]
            write_yaml_data(yaml_path, records)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--days", "30",
                    "--max", "5",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)


# ── Script Integration Tests ───────────────────────────────────


class TestScriptIntegration(unittest.TestCase):
    """Tests for script workflow integration."""

    def test_add_then_query_workflow(self):
        """Test add -> query workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "integration-test",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Query it back
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--cell", "K562",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("integration-test", result.stdout)

    def test_add_then_show_raw_workflow(self):
        """Test add -> show_raw workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "show-raw-test",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                    "--note", "integration test note",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Show raw
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "show_raw.py"),
                    "--yaml", str(yaml_path),
                    "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("show-raw-test", result.stdout)
            self.assertIn("integration test note", result.stdout)

    def test_add_then_thaw_workflow(self):
        """Test add -> thaw workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "thaw-test",
                    "--box", "1",
                    "--positions", "1,2",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Thaw one position
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_batch_add_then_batch_thaw_workflow(self):
        """Test batch add -> batch thaw workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add multiple records
            for i in range(1, 4):
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "add_entry.py"),
                        "--yaml", str(yaml_path),
                        "--parent-cell-line", "K562",
                        "--short-name", f"batch-test-{i}",
                        "--box", "1",
                        "--positions", str(i * 10),
                        "--frozen-at", "2026-02-10",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(ROOT),
                )

            # Batch thaw
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "batch_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--entries", "1:10,2:20,3:30",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_search_then_show_raw_workflow(self):
        """Test search -> show_raw workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "search-result-test",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Search
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "search.py"),
                    "--yaml", str(yaml_path),
                    "search-result",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_add_then_validate_workflow(self):
        """Test add -> validate workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "validate-test",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Validate
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_add_then_stats_workflow(self):
        """Test add -> stats workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add records
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "stats-test",
                    "--box", "1",
                    "--positions", "1,2,3",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Get stats
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "stats.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("K562", result.stdout)

    def test_add_then_recommend_workflow(self):
        """Test add -> recommend workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add a record
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "recommend-test",
                    "--box", "1",
                    "--positions", "1,2",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Get recommendations
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "recommend_position.py"),
                    "--yaml", str(yaml_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_cross_box_move_workflow(self):
        """Test cross-box move workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add records in different boxes
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "cross-box-1",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "cross-box-2",
                    "--box", "2",
                    "--positions", "1",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Perform move (cross-box: 1:1->2:50)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "record_thaw.py"),
                    "--yaml", str(yaml_path),
                    "--id", "1",
                    "--position", "1",
                    "--to-position", "50",
                    "--action", "move",
                    "--date", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_timeline_workflow(self):
        """Test timeline collection workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add entries on different dates
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "day1",
                    "--box", "1",
                    "--positions", "1",
                    "--frozen-at", "2026-02-05",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "HEK293T",
                    "--short-name", "day2",
                    "--box", "1",
                    "--positions", "2",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Query timeline
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "timeline.py"),
                    "--yaml", str(yaml_path),
                    "--days", "30",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)

    def test_conflict_detection_workflow(self):
        """Test conflict detection workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add first entry
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "first",
                    "--box", "1",
                    "--positions", "10,11",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Try to add conflicting entry
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "conflict",
                    "--box", "1",
                    "--positions", "10,12",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("位置冲突", result.stdout)

    def test_empty_positions_workflow(self):
        """Test empty positions query workflow."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml_data(yaml_path, [])

            # Add entry that occupies some positions
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "add_entry.py"),
                    "--yaml", str(yaml_path),
                    "--parent-cell-line", "K562",
                    "--short-name", "occupied",
                    "--box", "1",
                    "--positions", "1,2,3",
                    "--frozen-at", "2026-02-10",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            # Query empty positions
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "query_inventory.py"),
                    "--yaml", str(yaml_path),
                    "--empty",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("空闲位置", result.stdout)


if __name__ == "__main__":
    unittest.main()
