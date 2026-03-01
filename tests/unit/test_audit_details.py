"""Unit tests for audit_details builder functions."""

from lib.tool_api_impl.audit_details import (
    _extract_custom_fields,
    add_entry_details,
    adjust_box_count_details,
    edit_entry_details,
    failure_details,
    move_details,
    rollback_details,
    set_box_tag_details,
    takeout_details,
)


# ── add_entry_details ──────────────────────────────────────────────


class TestAddEntryDetails:
    def test_complete(self):
        d = add_entry_details(
            record_ids=[101, 102],
            box=2,
            positions=[5, 6],
            frozen_at="2025-01-15",
            cell_line="HeLa",
            note="passage 3",
            custom_fields={"source": "lab-A"},
        )
        assert d["op"] == "add_entry"
        assert d["record_ids"] == [101, 102]
        assert d["count"] == 2
        assert d["box"] == 2
        assert d["positions"] == [5, 6]
        assert d["frozen_at"] == "2025-01-15"
        assert d["cell_line"] == "HeLa"
        assert d["note"] == "passage 3"
        assert d["custom_fields"] == {"source": "lab-A"}

    def test_minimal(self):
        d = add_entry_details(
            record_ids=[1],
            box=1,
            positions=[1],
            frozen_at="2025-01-01",
        )
        assert d["op"] == "add_entry"
        assert d["count"] == 1
        assert "cell_line" not in d
        assert "note" not in d
        assert "custom_fields" not in d

    def test_note_none_omitted(self):
        d = add_entry_details(
            record_ids=[1], box=1, positions=[1], frozen_at="2025-01-01", note=None,
        )
        assert "note" not in d

    def test_empty_cell_line_omitted(self):
        d = add_entry_details(
            record_ids=[1], box=1, positions=[1], frozen_at="2025-01-01", cell_line="",
        )
        assert "cell_line" not in d

    def test_positions_coerced_to_int(self):
        d = add_entry_details(
            record_ids=[1], box=1, positions=["3", "4"], frozen_at="2025-01-01",
        )
        assert d["positions"] == [3, 4]


# ── edit_entry_details ─────────────────────────────────────────────


class TestEditEntryDetails:
    def test_field_changes_structure(self):
        d = edit_entry_details(
            record_id=101,
            cell_line="HeLa",
            short_name="H-001",
            box=2,
            position=5,
            field_changes={
                "frozen_at": ("2025-01-15", "2025-01-20"),
                "note": (None, "updated"),
            },
        )
        assert d["op"] == "edit_entry"
        assert d["record_id"] == 101
        assert d["cell_line"] == "HeLa"
        assert d["short_name"] == "H-001"
        assert d["box"] == 2
        assert d["position"] == 5
        assert d["field_changes"]["frozen_at"] == {"before": "2025-01-15", "after": "2025-01-20"}
        assert d["field_changes"]["note"] == {"before": None, "after": "updated"}

    def test_empty_changes(self):
        d = edit_entry_details(record_id=1, box=1, position=1, field_changes={})
        assert d["field_changes"] == {}
        assert d["cell_line"] is None
        assert d["short_name"] is None

    def test_note_and_custom_fields(self):
        d = edit_entry_details(
            record_id=1, box=1, position=1, field_changes={},
            note="passage 3", custom_fields={"source": "lab-A"},
        )
        assert d["note"] == "passage 3"
        assert d["custom_fields"] == {"source": "lab-A"}

    def test_note_none_omitted(self):
        d = edit_entry_details(record_id=1, box=1, position=1, field_changes={}, note=None)
        assert "note" not in d
        assert "custom_fields" not in d


# ── takeout_details ────────────────────────────────────────────────


class TestTakeoutDetails:
    def test_per_record_context(self):
        d = takeout_details(
            action="takeout",
            date="2025-03-01",
            records=[
                {"record_id": 1, "cell_line": "HeLa", "short_name": "H-001", "box": 2, "position": 5},
                {"record_id": 2, "cell_line": "293T", "short_name": "T-002", "box": 2, "position": 6},
            ],
        )
        assert d["op"] == "takeout"
        assert d["date"] == "2025-03-01"
        assert d["count"] == 2
        assert d["records"][0]["record_id"] == 1
        assert d["records"][0]["cell_line"] == "HeLa"
        assert d["records"][0]["short_name"] == "H-001"
        assert d["records"][0]["box"] == 2
        assert d["records"][0]["position"] == 5
        assert d["records"][1]["record_id"] == 2
        assert d["records"][1]["cell_line"] == "293T"

    def test_thaw_action(self):
        d = takeout_details(action="thaw", date="2025-01-01", records=[{"record_id": 1, "box": 1, "position": 1}])
        assert d["op"] == "thaw"
        assert d["records"][0]["cell_line"] is None
        assert d["records"][0]["short_name"] is None

    def test_discard_action(self):
        d = takeout_details(action="discard", date="2025-01-01", records=[{"record_id": 1, "box": 1, "position": 1}])
        assert d["op"] == "discard"

    def test_note_and_custom_fields_per_record(self):
        d = takeout_details(
            action="takeout",
            date="2025-03-01",
            records=[
                {
                    "record_id": 1, "cell_line": "HeLa", "box": 2, "position": 5,
                    "note": "passage 3", "custom_fields": {"source": "lab-A"},
                },
            ],
        )
        assert d["records"][0]["note"] == "passage 3"
        assert d["records"][0]["custom_fields"] == {"source": "lab-A"}

    def test_note_none_omitted(self):
        d = takeout_details(
            action="takeout", date="2025-01-01",
            records=[{"record_id": 1, "box": 1, "position": 1, "note": None}],
        )
        assert "note" not in d["records"][0]
        assert "custom_fields" not in d["records"][0]


# ── move_details ───────────────────────────────────────────────────


class TestMoveDetails:
    def test_with_swap(self):
        d = move_details(
            date="2025-03-01",
            moves=[
                {
                    "record_id": 1,
                    "cell_line": "HeLa",
                    "short_name": "H-001",
                    "from_box": 2,
                    "from_position": 5,
                    "to_box": 2,
                    "to_position": 10,
                    "swap_with_record_id": 3,
                },
            ],
            affected_record_ids=[1, 3],
        )
        assert d["op"] == "move"
        assert d["count"] == 1
        assert d["moves"][0]["cell_line"] == "HeLa"
        assert d["moves"][0]["short_name"] == "H-001"
        assert d["moves"][0]["swap_with_record_id"] == 3
        assert d["affected_record_ids"] == [1, 3]

    def test_without_swap(self):
        d = move_details(
            date="2025-03-01",
            moves=[
                {
                    "record_id": 1,
                    "from_box": 1,
                    "from_position": 5,
                    "to_box": 1,
                    "to_position": 10,
                },
            ],
            affected_record_ids=[1],
        )
        assert "swap_with_record_id" not in d["moves"][0]
        assert d["moves"][0]["cell_line"] is None
        assert d["moves"][0]["short_name"] is None

    def test_affected_ids_sorted(self):
        d = move_details(
            date="2025-01-01",
            moves=[
                {"record_id": 5, "cell_line": "A", "from_box": 1, "from_position": 1, "to_box": 1, "to_position": 2},
                {"record_id": 2, "cell_line": "B", "from_box": 1, "from_position": 3, "to_box": 1, "to_position": 4},
            ],
            affected_record_ids=[5, 2, 3],
        )
        assert d["affected_record_ids"] == [2, 3, 5]

    def test_note_and_custom_fields_per_move(self):
        d = move_details(
            date="2025-01-01",
            moves=[
                {
                    "record_id": 1, "from_box": 1, "from_position": 1,
                    "to_box": 1, "to_position": 2,
                    "note": "passage 3", "custom_fields": {"source": "lab-A"},
                },
            ],
            affected_record_ids=[1],
        )
        assert d["moves"][0]["note"] == "passage 3"
        assert d["moves"][0]["custom_fields"] == {"source": "lab-A"}

    def test_note_none_omitted_in_move(self):
        d = move_details(
            date="2025-01-01",
            moves=[
                {"record_id": 1, "from_box": 1, "from_position": 1, "to_box": 1, "to_position": 2, "note": None},
            ],
            affected_record_ids=[1],
        )
        assert "note" not in d["moves"][0]
        assert "custom_fields" not in d["moves"][0]


# ── set_box_tag_details ───────────────────────────────────────────


class TestSetBoxTagDetails:
    def test_concise(self):
        d = set_box_tag_details(box=2, tag_before="", tag_after="Group A")
        assert d == {
            "op": "set_box_tag",
            "box": 2,
            "tag_before": "",
            "tag_after": "Group A",
        }

    def test_clear_tag(self):
        d = set_box_tag_details(box=3, tag_before="Old", tag_after="")
        assert d["tag_before"] == "Old"
        assert d["tag_after"] == ""


# ── adjust_box_count_details ──────────────────────────────────────


class TestAdjustBoxCountDetails:
    def test_add(self):
        d = adjust_box_count_details(
            sub_op="add",
            preview={
                "box_count_before": 3,
                "box_count_after": 5,
                "added_boxes": [4, 5],
            },
        )
        assert d["op"] == "adjust_box_count"
        assert d["sub_op"] == "add"
        assert d["added_boxes"] == [4, 5]
        assert d["box_count_before"] == 3
        assert d["box_count_after"] == 5
        assert "removed_box" not in d

    def test_delete_keep_gaps(self):
        d = adjust_box_count_details(
            sub_op="delete",
            preview={
                "box_count_before": 5,
                "box_count_after": 4,
                "removed_box": 3,
                "renumber_mode": "keep_gaps",
            },
        )
        assert d["removed_box"] == 3
        assert d["renumber_mode"] == "keep_gaps"
        assert "box_mapping" not in d
        assert "added_boxes" not in d

    def test_delete_renumber(self):
        d = adjust_box_count_details(
            sub_op="delete",
            preview={
                "box_count_before": 5,
                "box_count_after": 4,
                "removed_box": 3,
                "renumber_mode": "renumber_contiguous",
                "box_mapping": {1: 1, 2: 2, 4: 3, 5: 4},
            },
        )
        assert d["box_mapping"] == {1: 1, 2: 2, 4: 3, 5: 4}


# ── rollback_details ──────────────────────────────────────────────


class TestRollbackDetails:
    def test_with_source_event(self):
        d = rollback_details(
            requested_backup="/path/to/bak",
            requested_from_event={"audit_seq": 5, "action": "add_entry"},
        )
        assert d["op"] == "rollback"
        assert d["requested_backup"] == "/path/to/bak"
        assert d["requested_from_event"]["audit_seq"] == 5

    def test_minimal(self):
        d = rollback_details()
        assert d == {"op": "rollback"}

    def test_empty_backup_omitted(self):
        d = rollback_details(requested_backup="")
        assert "requested_backup" not in d


# ── failure_details ────────────────────────────────────────────────


class TestFailureDetails:
    def test_includes_op(self):
        d = failure_details(op="add_entry")
        assert d == {"op": "add_entry"}

    def test_context_fields(self):
        d = failure_details(op="edit_entry", box=2, position=5, forbidden=["id"])
        assert d["op"] == "edit_entry"
        assert d["box"] == 2
        assert d["forbidden"] == ["id"]

    def test_none_values_excluded(self):
        d = failure_details(op="move", box=None, position=5)
        assert "box" not in d
        assert d["position"] == 5


# ── _extract_custom_fields ────────────────────────────────────────


class TestExtractCustomFields:
    def test_extracts_non_structural_keys(self):
        record = {
            "id": 1, "cell_line": "HeLa", "box": 2, "position": 5,
            "frozen_at": "2025-01-01", "note": "passage 3",
            "source": "lab-A", "batch": "B001",
        }
        custom = _extract_custom_fields(record)
        assert custom == {"source": "lab-A", "batch": "B001"}

    def test_empty_for_structural_only(self):
        record = {"id": 1, "cell_line": "HeLa", "box": 2, "position": 5}
        assert _extract_custom_fields(record) == {}

    def test_none_values_excluded(self):
        record = {"id": 1, "source": None, "batch": "B001"}
        assert _extract_custom_fields(record) == {"batch": "B001"}

    def test_non_dict_returns_empty(self):
        assert _extract_custom_fields(None) == {}
        assert _extract_custom_fields("not a dict") == {}
