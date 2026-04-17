"""Unit tests for app_gui.ui.table_entry_row_resolver."""

import pytest

from app_gui.ui.table_entry_row_resolver import (
    SlotState,
    resolve_entry_row,
    resolve_entry_rows,
)


def _identity_normalize(values):
    """Passthrough normaliser for tests that don't need coercion."""
    return dict(values or {})


def _make_row(*, row_kind="empty_slot", box=1, position=2, values=None):
    return {
        "row_kind": row_kind,
        "box": box,
        "position": position,
        "values": dict(values or {}),
    }


# ── resolve_entry_row ────────────────────────────────────────────────


class TestResolveEntryRowEmpty:
    def test_empty_slot_no_draft_no_staged(self):
        row = _make_row()
        result = resolve_entry_row(
            row, draft_values=None, staged_info=None,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["row_confirmed"] is False
        assert result["row_locked"] is False
        assert result["slot_state"] == SlotState.EMPTY.value

    def test_record_row_passthrough(self):
        row = _make_row(row_kind="record", values={"cell_line": "HeLa"})
        result = resolve_entry_row(
            row, draft_values={"cell_line": "K562"}, staged_info=None,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        # Non-empty-slot rows should not be affected by drafts
        assert result["slot_state"] == SlotState.EMPTY.value
        assert result["row_confirmed"] is False
        assert result["values"]["cell_line"] == "HeLa"


class TestResolveEntryRowDraft:
    def test_draft_overrides_values(self):
        row = _make_row(values={"cell_line": ""})
        result = resolve_entry_row(
            row, draft_values={"cell_line": "HeLa"},
            staged_info=None,
            data_columns=["cell_line"], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["slot_state"] == SlotState.DRAFT.value
        assert result["values"]["cell_line"] == "HeLa"
        assert result["row_confirmed"] is False
        assert result["row_locked"] is False

    def test_draft_over_staged_single_slot(self):
        staged = {"values": {"cell_line": "K562"}, "editable": True}
        result = resolve_entry_row(
            _make_row(), draft_values={"cell_line": "HeLa"},
            staged_info=staged,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["slot_state"] == SlotState.DRAFT.value
        assert result["values"]["cell_line"] == "HeLa"
        assert result["row_confirmed"] is False
        assert result["row_locked"] is False

    def test_draft_over_staged_multi_slot(self):
        staged = {"values": {"cell_line": "K562"}, "editable": False}
        result = resolve_entry_row(
            _make_row(), draft_values={"cell_line": "HeLa"},
            staged_info=staged,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["slot_state"] == SlotState.DRAFT.value
        assert result["row_locked"] is True  # locked because multi-slot staged


class TestResolveEntryRowStaged:
    def test_staged_single_slot(self):
        staged = {"values": {"cell_line": "K562"}, "editable": True}
        result = resolve_entry_row(
            _make_row(), draft_values=None, staged_info=staged,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["slot_state"] == SlotState.STAGED.value
        assert result["row_confirmed"] is True
        assert result["row_locked"] is False
        assert result["values"]["cell_line"] == "K562"

    def test_staged_multi_slot_locked(self):
        staged = {"values": {"cell_line": "K562"}, "editable": False}
        result = resolve_entry_row(
            _make_row(), draft_values=None, staged_info=staged,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["slot_state"] == SlotState.STAGED_LOCKED.value
        assert result["row_confirmed"] is True
        assert result["row_locked"] is True


class TestResolveEntryRowColorKey:
    def test_color_value_from_draft(self):
        result = resolve_entry_row(
            _make_row(), draft_values={"cell_line": "HeLa"},
            staged_info=None,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["color_value"] == "HeLa"

    def test_color_value_from_staged(self):
        staged = {"values": {"cell_line": "K562"}, "editable": True}
        result = resolve_entry_row(
            _make_row(), draft_values=None, staged_info=staged,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert result["color_value"] == "K562"

    def test_color_value_empty_when_no_entry(self):
        result = resolve_entry_row(
            _make_row(), draft_values=None, staged_info=None,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        # row_kind is empty_slot, so color_value is resolved (empty string)
        assert result.get("color_value", "") == ""


class TestResolveEntryRowSearchText:
    def test_search_text_from_values(self):
        result = resolve_entry_row(
            _make_row(values={"cell_line": "HeLa", "note": "test"}),
            draft_values=None, staged_info=None,
            data_columns=["cell_line", "note"], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert "hela" in result["search_text"]
        assert "test" in result["search_text"]


# ── resolve_entry_rows (batch) ───────────────────────────────────────


class TestResolveEntryRows:
    def test_batch_resolves_multiple_rows(self):
        rows = [
            _make_row(position=1),
            _make_row(position=2),
            _make_row(position=3, row_kind="record"),
        ]
        draft_map = {(1, 1): {"cell_line": "HeLa"}}
        staged_map = {(1, 2): {"values": {"cell_line": "K562"}, "editable": True}}

        results = resolve_entry_rows(
            rows, draft_map=draft_map, staged_map=staged_map,
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert len(results) == 3
        assert results[0]["slot_state"] == SlotState.DRAFT.value
        assert results[1]["slot_state"] == SlotState.STAGED.value
        assert results[2]["slot_state"] == SlotState.EMPTY.value

    def test_empty_maps_all_empty(self):
        rows = [_make_row(position=i) for i in range(1, 4)]
        results = resolve_entry_rows(
            rows, draft_map={}, staged_map={},
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert all(r["slot_state"] == SlotState.EMPTY.value for r in results)

    def test_original_row_not_mutated(self):
        row = _make_row(values={"cell_line": ""})
        original_values = dict(row["values"])
        resolve_entry_rows(
            [row],
            draft_map={(1, 2): {"cell_line": "HeLa"}},
            staged_map={},
            data_columns=[], color_key="cell_line",
            normalize_fn=_identity_normalize,
        )
        assert row["values"] == original_values
