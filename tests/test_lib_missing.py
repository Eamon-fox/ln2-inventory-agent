"""Missing unit tests for lib/ layer modules.

Tests for:
- yaml_ops.py: backup, warnings, diff functions
- validators.py: date normalization, action validation, conflict checks
- operations.py: find_record, check_conflicts, get_next_id
- takeout_parser.py: normalization, extraction, position activity
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.yaml_ops import (
    _diff_record_ids,
    create_yaml_backup,
    emit_capacity_warnings,
    get_yaml_size_warning,
    list_yaml_backups,
    write_yaml,
)
from lib.validators import (
    check_duplicate_ids,
    check_position_conflicts,
    format_chinese_date,
    normalize_action,
    normalize_date_arg,
    parse_date,
    validate_action,
    validate_box,
    validate_inventory,
    validate_position,
    validate_record,
)
from lib.takeout_parser import (
    ACTION_LABEL,
    extract_events,
    is_position_active,
    normalize_action as thaw_normalize_action,
)
from lib.operations import (
    check_position_conflicts as ops_check_position_conflicts,
    find_record_by_id,
    get_next_id,
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


# --- yaml_ops.py Tests ---


class YamlOpsBackupTests(unittest.TestCase):
    """Test backup and utility functions in yaml_ops.py."""

    def test_create_yaml_backup_none_when_source_missing(self):
        """create_yaml_backup should return None when source file doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "nonexistent.yaml"
            result = create_yaml_backup(str(fake_path))
            self.assertIsNone(result)

    def test_create_yaml_backup_with_naming_conflict(self):
        """Test backup creation when timestamp collision occurs."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "test.yaml"
            yaml_path.write_text("data")

            # Create first backup
            result1 = create_yaml_backup(str(yaml_path), keep=0)
            self.assertIsNotNone(result1)

            # Get timestamp from backup filename
            import re
            match = re.search(r'\d{8}-\d{6}', result1)
            self.assertIsNotNone(match)
            timestamp = match.group()

            # Simulate collision by creating a file with same timestamp
            import shutil
            backup_dir = Path(result1).parent
            conflict_file = backup_dir / f"test.{timestamp}.bak"
            shutil.copy2(result1, conflict_file)

            # Create second backup - should use .1 suffix
            result2 = create_yaml_backup(str(yaml_path), keep=0)
            self.assertIsNotNone(result2)
            self.assertIn(".1.", Path(result2).name)

    def test_keep_zero_does_not_delete_old_backups(self):
        """Test keep=0 doesn't delete old backups."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "test.yaml"
            yaml_path.write_text("data")

            result1 = create_yaml_backup(str(yaml_path), keep=0)
            result2 = create_yaml_backup(str(yaml_path), keep=0)

            # Both backups should still exist
            self.assertTrue(Path(result1).exists())
            self.assertTrue(Path(result2).exists())

            backups = list_yaml_backups(str(yaml_path))
            self.assertGreaterEqual(len(backups), 2)

    def test_write_yaml_without_auto_backup(self):
        """write_yaml with auto_backup=False should not create backup."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "test.yaml"
            data = make_data([make_record(1)])
            result = write_yaml(data, path=str(yaml_path), auto_backup=False)
            self.assertIsNone(result)
            self.assertTrue(yaml_path.exists())


class YamlOpsWarningTests(unittest.TestCase):
    """Test warning functions."""

    def test_emit_capacity_warnings_total_empty(self):
        """Test total empty capacity warning."""
        data = make_data([])
        warnings = emit_capacity_warnings(data, total_empty_threshold=500, box_empty_threshold=5)
        self.assertEqual(1, len(warnings))
        self.assertIn("405", warnings[0])  # 5 boxes * 81 positions = 405

    def test_emit_capacity_warnings_box_empty(self):
        """Test box-specific capacity warning."""
        data = make_data([make_record(i, box=1, position=i) for i in range(1, 81)])
        warnings = emit_capacity_warnings(data, total_empty_threshold=0, box_empty_threshold=5)
        self.assertEqual(1, len(warnings))
        self.assertIn("1", warnings[0])  # 81 - 80 = 1

    def test_emit_yaml_size_warning_large_file(self):
        """Test YAML size warning for large file."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "large.yaml"
            # Create a file > 1MB
            yaml_path.write_text("x" * (2 * 1024 * 1024))
            warning = get_yaml_size_warning(path=str(yaml_path), warn_mb=1)
            self.assertIsNotNone(warning)
            self.assertIn("MB", warning)

    def test_emit_yaml_size_warning_small_file(self):
        """Test YAML size warning returns None for small file."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "small.yaml"
            yaml_path.write_text("small")
            warning = get_yaml_size_warning(path=str(yaml_path), warn_mb=10)
            self.assertIsNone(warning)


class DiffRecordIdsTests(unittest.TestCase):
    """Test _diff_record_ids functionality."""

    def test_diff_records_added(self):
        """Test detecting added records."""
        before = [make_record(1)]
        after = [make_record(1), make_record(2)]
        diff = _diff_record_ids(before, after)
        self.assertEqual([2], diff["added"])
        self.assertEqual([], diff["removed"])
        self.assertEqual([], diff["updated"])

    def test_diff_records_removed(self):
        """Test detecting removed records."""
        before = [make_record(1), make_record(2)]
        after = [make_record(1)]
        diff = _diff_record_ids(before, after)
        self.assertEqual([], diff["added"])
        self.assertEqual([2], diff["removed"])
        self.assertEqual([], diff["updated"])

    def test_diff_records_updated(self):
        """Test detecting updated records."""
        before = [make_record(1)]
        after = [make_record(1)]
        after[0]["note"] = "updated"
        diff = _diff_record_ids(before, after)
        self.assertEqual([], diff["added"])
        self.assertEqual([], diff["removed"])
        self.assertEqual([1], diff["updated"])

    def test_diff_records_no_changes(self):
        """Test no changes detection."""
        records = [make_record(1), make_record(2)]
        diff = _diff_record_ids(records, records)
        self.assertEqual([], diff["added"])
        self.assertEqual([], diff["removed"])
        self.assertEqual([], diff["updated"])


# --- validators.py Tests ---


class ValidatorsDateTests(unittest.TestCase):
    """Test date validation and normalization."""

    def test_parse_date_valid_formats(self):
        """Test parsing various valid date formats."""
        self.assertIsNotNone(parse_date("2025-01-01"))
        self.assertIsNotNone(parse_date("2024-12-31"))
        self.assertIsNone(parse_date("2025/01/01"))  # Wrong format
        self.assertIsNone(parse_date("invalid"))

    def test_normalize_date_arg_today(self):
        """Test 'today' normalization."""
        result = normalize_date_arg("today")
        self.assertIsNotNone(result)
        # Should be in YYYY-MM-DD format
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_normalize_date_arg_chinese_today(self):
        """Test '今天' normalization."""
        result = normalize_date_arg("今天")
        self.assertIsNotNone(result)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_normalize_date_arg_none(self):
        """Test None normalization."""
        result = normalize_date_arg(None)
        self.assertIsNotNone(result)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_normalize_date_arg_empty_string(self):
        """Test empty string normalization."""
        result = normalize_date_arg("")
        self.assertIsNotNone(result)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_normalize_date_arg_invalid_format(self):
        """Test invalid date format returns None."""
        result = normalize_date_arg("invalid-date")
        self.assertIsNone(result)

    def test_format_chinese_date_without_weekday(self):
        """Test Chinese date formatting without weekday."""
        result = format_chinese_date("2025-01-01", weekday=False)
        self.assertEqual("2025年01月01日", result)

    def test_format_chinese_date_with_weekday(self):
        """Test Chinese date formatting with weekday."""
        result = format_chinese_date("2025-01-01", weekday=True)
        self.assertIn("2025年01月01日", result)
        self.assertIn("(周", result)


class ValidatorsActionTests(unittest.TestCase):
    """Test action validation."""

    def test_validate_action_valid_actions(self):
        """Test all valid action types."""
        from lib.config import VALID_ACTIONS
        for action in VALID_ACTIONS:
            self.assertTrue(validate_action(action))

    def test_validate_action_invalid(self):
        """Test invalid action returns False."""
        self.assertFalse(validate_action("invalid_action"))
        self.assertFalse(validate_action(""))


class ValidatorsDuplicateIdsTests(unittest.TestCase):
    """Test duplicate ID checking."""

    def test_check_duplicate_ids_no_duplicates(self):
        """Test with no duplicate IDs."""
        records = [make_record(1), make_record(2), make_record(3)]
        errors = check_duplicate_ids(records)
        self.assertEqual([], errors)

    def test_check_duplicate_ids_with_duplicates(self):
        """Test with duplicate IDs."""
        records = [make_record(1), make_record(2), make_record(1)]
        errors = check_duplicate_ids(records)
        self.assertEqual(1, len(errors))
        self.assertIn("Duplicate ID 1", errors[0])

    def test_check_duplicate_ids_multiple_duplicates(self):
        """Test with multiple duplicate IDs."""
        records = [make_record(1), make_record(2), make_record(1), make_record(2)]
        errors = check_duplicate_ids(records)
        self.assertEqual(2, len(errors))


class ValidatorsPositionConflictsTests(unittest.TestCase):
    """Test position conflict checking."""

    def test_check_position_conflicts_no_conflicts(self):
        """Test with no position conflicts."""
        records = [make_record(1, box=1, position=1), make_record(2, box=1, position=2)]
        errors = check_position_conflicts(records)
        self.assertEqual([], errors)

    def test_check_position_conflicts_with_conflicts(self):
        """Test with position conflicts."""
        records = [
            make_record(1, box=1, position=5),
            make_record(2, box=1, position=5),
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(1, len(errors))
        self.assertIn("Position conflict", errors[0])

    def test_check_position_conflicts_multiple_boxes(self):
        """Test conflicts don't span boxes."""
        records = [
            make_record(1, box=1, position=5),
            make_record(2, box=2, position=5),
        ]
        errors = check_position_conflicts(records)
        self.assertEqual([], errors)  # Same position but different boxes is OK

    def test_check_position_conflicts_ignores_invalid_numeric_types(self):
        """Invalid box/position types should not crash conflict checking."""
        records = [
            make_record(1, box="abc", position=5),
            make_record(2, box=1, position=5),
            make_record(3, box=1, position=5),
        ]
        errors = check_position_conflicts(records)
        self.assertEqual(1, len(errors))
        self.assertIn("Box 1 Position 5", errors[0])


class ValidatorsRecordTests(unittest.TestCase):
    """Test record validation optional fields."""

    def test_validate_record_with_optional_fields(self):
        """Test that optional fields like plasmid_name don't cause errors."""
        records = [make_record(1)]
        records[0]["plasmid_name"] = "pX"
        records[0]["plasmid_id"] = "p2"
        records[0]["note"] = "test note"
        errors, warnings = validate_record(records[0])
        self.assertEqual([], errors)

    def test_validate_record_missing_optional_fields(self):
        """Test that missing optional fields is OK."""
        record = make_record(1)
        # Remove optional fields
        for field in ["plasmid_name", "plasmid_id", "note"]:
            if field in record:
                del record[field]
        errors, warnings = validate_record(record)
        self.assertEqual([], errors)

    def test_validate_record_rejects_bool_for_core_integer_fields(self):
        """id/box/position should reject booleans even though bool is int subclass."""
        record = make_record(1)
        record["id"] = True
        record["box"] = True
        record["position"] = True
        errors, _warnings = validate_record(record)
        self.assertTrue(any("'id' must be a positive integer" in e for e in errors))
        self.assertTrue(any("'box' must be an integer" in e for e in errors))
        self.assertTrue(any("'position' must be an integer" in e for e in errors))

    def test_validate_inventory_non_numeric_box_returns_errors_not_exception(self):
        """validate_inventory should return structured errors for bad box type."""
        data = make_data([make_record(1, box="abc", position=1)])
        errors, _warnings = validate_inventory(data)
        self.assertTrue(any("'box' must be an integer" in e for e in errors))

    def test_validate_box_and_position_reject_bool(self):
        """Field-level validators should treat bool as invalid integer input."""
        self.assertFalse(validate_box(True))
        self.assertFalse(validate_position(True))


# --- operations.py Tests ---


class OperationsTests(unittest.TestCase):
    """Test operations module functions."""

    def test_find_record_by_id_existing(self):
        """Test finding existing record."""
        records = [make_record(1), make_record(2)]
        idx, rec = find_record_by_id(records, 2)
        self.assertIsNotNone(idx)
        self.assertIsNotNone(rec)
        self.assertEqual(1, idx)  # Index 1
        self.assertEqual(2, rec["id"])

    def test_find_record_by_id_not_found(self):
        """Test finding non-existent record."""
        records = [make_record(1)]
        idx, rec = find_record_by_id(records, 999)
        self.assertIsNone(idx)
        self.assertIsNone(rec)

    def test_find_record_by_id_empty_list(self):
        """Test with empty records list."""
        idx, rec = find_record_by_id([], 1)
        self.assertIsNone(idx)
        self.assertIsNone(rec)

    def test_check_position_conflicts_operations(self):
        """Test operations.check_position_conflicts."""
        records = [
            make_record(1, box=1, position=5),
            make_record(2, box=1, position=5),
        ]
        conflicts = ops_check_position_conflicts(records, box=1, positions=[5])
        self.assertEqual(2, len(conflicts))  # Both records have position 5 in box 1
        for conflict in conflicts:
            self.assertIn("id", conflict)
            self.assertIn("short_name", conflict)
            self.assertIn("position", conflict)
            self.assertEqual(5, conflict["position"])

    def test_get_next_id_empty_inventory(self):
        """Test get_next_id with empty inventory."""
        next_id = get_next_id([])
        self.assertEqual(1, next_id)

    def test_get_next_id_single_record(self):
        """Test get_next_id with single record."""
        records = [make_record(5)]
        next_id = get_next_id(records)
        self.assertEqual(6, next_id)

    def test_get_next_id_multiple_records(self):
        """Test get_next_id finds max ID + 1."""
        records = [make_record(3), make_record(5), make_record(1)]
        next_id = get_next_id(records)
        self.assertEqual(6, next_id)

    def test_get_next_id_with_gaps(self):
        """Test get_next_id handles ID gaps correctly."""
        records = [make_record(1), make_record(5)]
        next_id = get_next_id(records)
        self.assertEqual(6, next_id)  # Should be max + 1


# --- takeout_parser.py Tests ---


class ThawParserNormalizationTests(unittest.TestCase):
    """Test thaw event normalization."""

    def test_normalize_action_all_chinese(self):
        """Test normalizing supported Chinese action variants."""
        self.assertEqual("takeout", thaw_normalize_action("鍙栧嚭"))
        self.assertEqual("move", thaw_normalize_action("绉诲姩"))
        self.assertIsNone(thaw_normalize_action("澶嶈嫃"))
        self.assertIsNone(thaw_normalize_action("鎵旀帀"))

    def test_normalize_action_all_english(self):
        """Test normalizing supported English action variants."""
        self.assertEqual("takeout", thaw_normalize_action("takeout"))
        self.assertEqual("move", thaw_normalize_action("move"))
        self.assertIsNone(thaw_normalize_action("thaw"))
        self.assertIsNone(thaw_normalize_action("discard"))

    def test_normalize_action_case_insensitive(self):
        """Test case-insensitive normalization."""
        self.assertEqual("takeout", thaw_normalize_action("Takeout"))
        self.assertEqual("takeout", thaw_normalize_action("TAKEOUT"))

    def test_action_label_all_keys(self):
        """Test ACTION_LABEL has entries for all canonical actions."""
        for action in ["takeout", "move"]:
            self.assertIn(action, ACTION_LABEL)
            self.assertIsInstance(ACTION_LABEL[action], str)

    def test_action_label_values(self):
        """Test ACTION_LABEL provides meaningful labels."""
        self.assertEqual("取出", ACTION_LABEL["takeout"])
        self.assertEqual("移动", ACTION_LABEL["move"])


class ThawParserExtractionTests(unittest.TestCase):
    """Test thaw event extraction."""

    def test_extract_events_with_history(self):
        """Test extracting events from record with history."""
        record = make_record(1, position=1)
        record["thaw_events"] = [
            {"date": "2025-01-15", "action": "takeout", "positions": [1]},
            {"date": "2025-01-16", "action": "move", "positions": [1]},
        ]
        events = extract_events(record)
        self.assertEqual(2, len(events))

    def test_extract_events_without_history(self):
        """Test extracting events from record without history."""
        record = make_record(1, position=1)
        events = extract_events(record)
        self.assertEqual([], events)

    def test_extract_events_with_move_events(self):
        """Test that move events are included."""
        record = make_record(1, position=1)
        record["thaw_events"] = [
            {"date": "2025-01-15", "action": "move", "positions": [1], "from_position": 1, "to_position": 5},
        ]
        events = extract_events(record)
        self.assertEqual(1, len(events))


class ThawParserActivityTests(unittest.TestCase):
    """Test position activity checking."""

    def test_is_position_active_true(self):
        """Test active position returns True."""
        record = make_record(1, position=2)
        self.assertTrue(is_position_active(record, 2))

    def test_is_position_active_false(self):
        """Test inactive position (thawed) returns False."""
        record = make_record(1, position=3)
        record["thaw_events"] = [
            {"date": "2025-01-15", "action": "takeout", "positions": [1]},
        ]
        self.assertFalse(is_position_active(record, 1))

    def test_is_position_active_after_move(self):
        """Test position after move is active."""
        record = make_record(1, position=5)
        record["thaw_events"] = [
            {"date": "2025-01-15", "action": "move", "positions": [1], "to_position": 5},
        ]
        self.assertTrue(is_position_active(record, 5))

    def test_is_position_active_empty_record(self):
        """Test empty positions record - no thawed positions means position is considered active."""
        record = make_record(1, position=None)
        self.assertTrue(is_position_active(record, 1))  # 1 is not in thawed set (empty)

    def test_is_position_active_nonexistent_position(self):
        """Test position not in thawed events is considered active."""
        record = make_record(1, position=1)
        # Position 99 was never thawed, so it's "active" from the function's perspective
        self.assertTrue(is_position_active(record, 99))


# --- Cross-module normalization tests ---


class NormalizeActionConsistencyTests(unittest.TestCase):
    """Test consistency between validators.normalize_action and takeout_parser.normalize_action."""

    def test_normalize_action_consistency(self):
        """Both normalize_action functions should behave identically."""
        test_actions = ["takeout", "鍙栧嚭", "thaw", "澶嶈嫃", "discard", "鎵旀帀", "move", "绉诲姩"]
        for action in test_actions:
            val_result = normalize_action(action)
            thaw_result = thaw_normalize_action(action)
            self.assertEqual(val_result, thaw_result,
                           f"Inconsistent normalization for '{action}': val={val_result}, thaw={thaw_result}")


if __name__ == "__main__":
    unittest.main()

