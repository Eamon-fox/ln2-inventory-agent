"""Unit tests for app_gui.ui.table_entry_draft_store.TableEntryDraftStore."""

import pytest

from app_gui.ui.table_entry_draft_store import TableEntryDraftStore
from app_gui.ui.table_entry_row_resolver import SlotState


# ── helpers ──────────────────────────────────────────────────────────


class FakePlanStore:
    """Minimal plan-store stub with list_items support."""

    def __init__(self, items=None):
        self._items = list(items or [])

    def list_items(self):
        return list(self._items)


def _add_plan_item(*, box=1, positions=(2,), stored_at="2026-02-10", fields=None):
    """Build a minimal add plan item dict."""
    return {
        "action": "add",
        "box": box,
        "position": positions[0],
        "record_id": None,
        "source": "tests",
        "payload": {
            "box": box,
            "positions": list(positions),
            "stored_at": stored_at,
            "frozen_at": stored_at,
            "fields": dict(fields or {}),
        },
    }


def _make_store(*, meta=None, records=None, plan_items=None):
    store = TableEntryDraftStore()
    store.set_field_context(
        meta=meta or {"custom_fields": [{"key": "cell_line", "type": "str"}]},
        records=records or [],
        layout={},
    )
    if plan_items is not None:
        store.set_plan_store(FakePlanStore(plan_items))
    return store


# ── draft CRUD ───────────────────────────────────────────────────────


class TestDraftCRUD:
    def test_set_and_get(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        assert store.get_draft((1, 2)) == {"cell_line": "HeLa"}
        assert store.has_draft((1, 2)) is True

    def test_get_nonexistent(self):
        store = _make_store()
        assert store.get_draft((1, 2)) is None
        assert store.has_draft((1, 2)) is False

    def test_clear_draft(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        store.clear_draft((1, 2))
        assert store.get_draft((1, 2)) is None

    def test_clear_nonexistent_is_noop(self):
        store = _make_store()
        store.clear_draft((1, 99))  # should not raise

    def test_clear_all(self):
        store = _make_store()
        store.set_draft((1, 1), {"cell_line": "A"})
        store.set_draft((1, 2), {"cell_line": "B"})
        store.clear_all_drafts()
        assert store.draft_map == {}

    def test_none_slot_key_ignored(self):
        store = _make_store()
        store.set_draft(None, {"cell_line": "X"})
        assert store.draft_map == {}


class TestDraftAutoClearing:
    def test_draft_matching_staged_auto_clears(self):
        item = _add_plan_item(box=1, positions=(2,), stored_at="2026-02-10",
                              fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        # Set a draft that matches the staged values exactly
        store.set_draft((1, 2), {"cell_line": "K562", "stored_at": "2026-02-10"})
        assert store.has_draft((1, 2)) is False  # auto-cleared

    def test_draft_differing_from_staged_persists(self):
        item = _add_plan_item(box=1, positions=(2,), stored_at="2026-02-10",
                              fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        store.set_draft((1, 2), {"cell_line": "HeLa", "stored_at": "2026-02-10"})
        assert store.has_draft((1, 2)) is True

    def test_all_empty_draft_no_staged_auto_clears(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "", "stored_at": ""})
        assert store.has_draft((1, 2)) is False


# ── staged queries ───────────────────────────────────────────────────


class TestStagedQueries:
    def test_staged_slot_map_single(self):
        item = _add_plan_item(box=1, positions=(2,), fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        smap = store.staged_slot_map()
        assert (1, 2) in smap
        assert smap[(1, 2)]["editable"] is True

    def test_staged_slot_map_multi(self):
        item = _add_plan_item(box=1, positions=(2, 3), fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        smap = store.staged_slot_map()
        assert (1, 2) in smap
        assert (1, 3) in smap
        assert smap[(1, 2)]["editable"] is False
        assert smap[(1, 3)]["editable"] is False

    def test_no_plan_store(self):
        store = _make_store()
        assert store.staged_slot_map() == {}

    def test_get_staged(self):
        item = _add_plan_item(box=1, positions=(2,), fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        assert store.get_staged((1, 2)) is not None
        assert store.get_staged((1, 99)) is None

    def test_is_staged(self):
        item = _add_plan_item(box=1, positions=(2,), fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        assert store.is_staged((1, 2)) is True
        assert store.is_staged((1, 99)) is False


# ── slot state ───────────────────────────────────────────────────────


class TestSlotState:
    def test_empty(self):
        store = _make_store()
        assert store.slot_state((1, 2)) == SlotState.EMPTY

    def test_draft(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        assert store.slot_state((1, 2)) == SlotState.DRAFT

    def test_staged_single(self):
        item = _add_plan_item(box=1, positions=(2,))
        store = _make_store(plan_items=[item])
        assert store.slot_state((1, 2)) == SlotState.STAGED

    def test_staged_locked_multi(self):
        item = _add_plan_item(box=1, positions=(2, 3))
        store = _make_store(plan_items=[item])
        assert store.slot_state((1, 2)) == SlotState.STAGED_LOCKED
        assert store.slot_state((1, 3)) == SlotState.STAGED_LOCKED

    def test_none_slot_key(self):
        store = _make_store()
        assert store.slot_state(None) == SlotState.EMPTY


# ── is_dirty ─────────────────────────────────────────────────────────


class TestIsDirty:
    def test_no_draft_not_dirty(self):
        store = _make_store()
        assert store.is_dirty((1, 2)) is False

    def test_draft_no_staged_is_dirty(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        assert store.is_dirty((1, 2)) is True

    def test_none_slot_not_dirty(self):
        store = _make_store()
        assert store.is_dirty(None) is False


# ── signals ──────────────────────────────────────────────────────────


class TestSignals:
    def test_slot_changed_on_set(self):
        store = _make_store()
        received = []
        store.slot_changed.connect(lambda sk: received.append(sk))
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        assert len(received) == 1
        assert received[0] == (1, 2)

    def test_slot_changed_on_clear(self):
        store = _make_store()
        store.set_draft((1, 2), {"cell_line": "HeLa"})
        received = []
        store.slot_changed.connect(lambda sk: received.append(sk))
        store.clear_draft((1, 2))
        assert len(received) == 1

    def test_drafts_cleared_signal(self):
        store = _make_store()
        store.set_draft((1, 1), {"cell_line": "A"})
        fired = []
        store.drafts_cleared.connect(lambda: fired.append(True))
        store.clear_all_drafts()
        assert len(fired) == 1

    def test_no_signal_on_empty_clear_all(self):
        store = _make_store()
        fired = []
        store.drafts_cleared.connect(lambda: fired.append(True))
        store.clear_all_drafts()
        assert len(fired) == 0


# ── resolve_rows ─────────────────────────────────────────────────────


class TestResolveRows:
    def test_basic_resolution(self):
        item = _add_plan_item(box=1, positions=(2,), fields={"cell_line": "K562"})
        store = _make_store(plan_items=[item])
        store.set_draft((1, 3), {"cell_line": "HeLa"})

        raw_rows = [
            {"row_kind": "empty_slot", "box": 1, "position": 1, "values": {}},
            {"row_kind": "empty_slot", "box": 1, "position": 2, "values": {}},
            {"row_kind": "empty_slot", "box": 1, "position": 3, "values": {}},
        ]
        results = store.resolve_rows(raw_rows, data_columns=["cell_line"])
        assert results[0]["slot_state"] == SlotState.EMPTY.value
        assert results[1]["slot_state"] == SlotState.STAGED.value
        assert results[1]["row_confirmed"] is True
        assert results[2]["slot_state"] == SlotState.DRAFT.value
        assert results[2]["row_confirmed"] is False


# ── normalisation ────────────────────────────────────────────────────


class TestNormalization:
    def test_normalize_entry_values(self):
        store = _make_store()
        result = store.normalize_entry_values({"cell_line": "HeLa", "stored_at": "2026-02-10"})
        assert result["cell_line"] == "HeLa"
        assert result["stored_at"] == "2026-02-10"
        assert result["frozen_at"] == "2026-02-10"

    def test_entry_columns(self):
        store = _make_store()
        cols = store.entry_columns()
        assert "stored_at" in cols
        assert "frozen_at" in cols
        assert "cell_line" in cols
