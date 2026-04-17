"""Centralised state store for table-view inline-entry drafts.

Owns:
  - Draft edits (user-typed values not yet confirmed)
  - Read-only view of staged plan-store items
  - Composite slot-state computation
  - Row resolution (delegates to :mod:`table_entry_row_resolver`)

Design notes
------------
This is a ``QObject`` (for signal support) but keeps Qt usage to signals
only – all data logic is plain Python dicts/tuples so it can be tested
without a running ``QApplication`` (signals just won't fire).
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal

from lib.custom_fields import get_color_key, get_effective_fields
from lib.schema_aliases import get_input_stored_at

from app_gui.ui.table_entry_row_resolver import SlotState, resolve_entry_rows


# ── public class ─────────────────────────────────────────────────────


class TableEntryDraftStore(QObject):
    """Single source of truth for inline-entry state.

    Signals
    -------
    slot_changed(object)
        Emitted with a ``(box, position)`` tuple whenever a single slot's
        draft state changes.
    drafts_cleared()
        Emitted when :meth:`clear_all_drafts` removes one or more entries.
    """

    slot_changed = Signal(object)
    drafts_cleared = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._drafts: Dict[Tuple[int, int], dict] = {}
        self._plan_store: Any = None  # PlanStore reference (read-only)
        self._meta: dict = {}
        self._records: list = []
        self._layout: dict = {}

    # ── setup ────────────────────────────────────────────────────────

    def set_plan_store(self, store: Any) -> None:
        """Bind a :class:`PlanStore` instance for staged-item queries."""
        self._plan_store = store

    def set_field_context(
        self,
        meta: dict,
        records: list,
        layout: dict,
    ) -> None:
        """Update metadata context used for field definitions and color key."""
        self._meta = dict(meta or {})
        self._records = list(records or [])
        self._layout = dict(layout or {})

    # ── draft CRUD ───────────────────────────────────────────────────

    def set_draft(self, slot_key: Tuple[int, int], values: dict) -> None:
        """Store or update a draft for *slot_key*.

        If the draft matches the currently staged values for this slot the
        draft is auto-cleared (the staged version is canonical).
        """
        if slot_key is None:
            return
        slot_key = tuple(slot_key)

        # Auto-clear when draft equals staged
        staged = self.staged_slot_map().get(slot_key)
        if staged is not None:
            if self._values_signature(values) == self._values_signature(
                staged.get("values") or {}
            ):
                self._drafts.pop(slot_key, None)
                self.slot_changed.emit(slot_key)
                return

        # Auto-clear when all values empty and no staged
        if staged is None and all(
            not str(v or "").strip() for v in (values or {}).values()
        ):
            if slot_key in self._drafts:
                del self._drafts[slot_key]
                self.slot_changed.emit(slot_key)
            return

        self._drafts[slot_key] = dict(values)
        self.slot_changed.emit(slot_key)

    def get_draft(self, slot_key: Tuple[int, int]) -> Optional[dict]:
        if slot_key is None:
            return None
        return self._drafts.get(tuple(slot_key))

    def clear_draft(self, slot_key: Tuple[int, int]) -> None:
        slot_key = tuple(slot_key) if slot_key is not None else None
        if slot_key is not None and slot_key in self._drafts:
            del self._drafts[slot_key]
            self.slot_changed.emit(slot_key)

    def clear_all_drafts(self) -> None:
        if self._drafts:
            self._drafts.clear()
            self.drafts_cleared.emit()

    def has_draft(self, slot_key: Tuple[int, int]) -> bool:
        if slot_key is None:
            return False
        return tuple(slot_key) in self._drafts

    @property
    def draft_map(self) -> Dict[Tuple[int, int], dict]:
        """Snapshot of all current drafts (read-only copy)."""
        return dict(self._drafts)

    # ── staged queries (read-only delegation to PlanStore) ───────────

    def staged_slot_map(self) -> Dict[Tuple[int, int], dict]:
        """Build ``{(box, pos): info}`` from plan-store add items.

        Each value dict contains:
        - ``item``: the raw plan item
        - ``positions``: tuple of all positions in the add
        - ``values``: normalised field values
        - ``color_value``: resolved color-key value
        - ``editable``: True for single-slot items
        """
        store = self._plan_store
        if store is None or not hasattr(store, "list_items"):
            return {}

        field_defs = self._field_definitions()
        color_key = get_color_key(
            self._meta, inventory=self._records,
        )
        slot_map: Dict[Tuple[int, int], dict] = {}
        try:
            plan_items = store.list_items()
        except Exception:
            plan_items = []

        for item in list(plan_items or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("action") or "").strip().lower() != "add":
                continue

            box = _safe_int(item.get("box"))
            positions = _normalize_add_item_positions(item)
            if box is None or not positions:
                continue

            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
            values = self._blank_entry_values()
            stored_at = str(get_input_stored_at(payload, default="") or "").strip()
            if stored_at:
                values["stored_at"] = stored_at
            for key in field_defs:
                raw_value = fields.get(key)
                values[key] = "" if raw_value in (None, "") else str(raw_value)
            color_value = str(values.get(color_key) or fields.get(color_key) or "")
            editable = len(positions) == 1
            for position in positions:
                slot_map[(box, position)] = {
                    "item": item,
                    "positions": positions,
                    "values": dict(values),
                    "color_value": color_value,
                    "editable": editable,
                }
        return slot_map

    def get_staged(self, slot_key: Tuple[int, int]) -> Optional[dict]:
        if slot_key is None:
            return None
        return self.staged_slot_map().get(tuple(slot_key))

    def is_staged(self, slot_key: Tuple[int, int]) -> bool:
        return self.get_staged(slot_key) is not None

    # ── composite state ──────────────────────────────────────────────

    def slot_state(self, slot_key: Tuple[int, int]) -> SlotState:
        """Compute the current visual/logical state for a slot."""
        if slot_key is None:
            return SlotState.EMPTY
        slot_key = tuple(slot_key)

        has_draft = slot_key in self._drafts
        staged = self.staged_slot_map().get(slot_key)

        if has_draft:
            return SlotState.DRAFT
        if staged:
            return SlotState.STAGED if staged.get("editable") else SlotState.STAGED_LOCKED
        return SlotState.EMPTY

    def is_dirty(self, slot_key: Tuple[int, int]) -> bool:
        """True when a draft exists that differs from any staged value."""
        if slot_key is None:
            return False
        slot_key = tuple(slot_key)
        draft = self._drafts.get(slot_key)
        if draft is None:
            return False
        staged = self.staged_slot_map().get(slot_key)
        if staged is None:
            return True  # draft with no staged = dirty
        return self._values_signature(draft) != self._values_signature(
            staged.get("values") or {}
        )

    def reconcile_with_staged(self) -> None:
        """Clear any drafts that now match their staged counterpart.

        Call this after the plan store changes so that drafts confirmed
        into the store are automatically cleaned up.
        """
        staged_map = self.staged_slot_map()
        stale_keys = []
        for slot_key, draft_values in list(self._drafts.items()):
            staged = staged_map.get(slot_key)
            if staged is None:
                continue
            if self._values_signature(draft_values) == self._values_signature(
                staged.get("values") or {}
            ):
                stale_keys.append(slot_key)
        for key in stale_keys:
            self._drafts.pop(key, None)
            self.slot_changed.emit(key)

    # ── row resolution ───────────────────────────────────────────────

    def resolve_rows(
        self,
        raw_rows: List[dict],
        data_columns: Sequence[str],
    ) -> List[dict]:
        """Overlay drafts/staged onto raw projection rows.

        Replaces the old ``_overlay_current_view_rows`` in
        ``overview_panel_table.py``.
        """
        color_key = get_color_key(self._meta, inventory=self._records)
        return resolve_entry_rows(
            raw_rows,
            draft_map=dict(self._drafts),
            staged_map=self.staged_slot_map(),
            data_columns=data_columns,
            color_key=color_key,
            normalize_fn=self.normalize_entry_values,
        )

    def resolve_single_row(
        self,
        row_data: dict,
        entry_values: dict,
    ) -> dict:
        """Resolve a single row after a cell edit.

        Replaces the old ``_row_with_entry_values``.
        """
        from app_gui.ui.table_entry_row_resolver import resolve_entry_row

        slot_key = _slot_key_from_row(row_data)
        color_key = get_color_key(self._meta, inventory=self._records)
        data_columns = list(row_data.get("_data_columns") or [])

        staged = self.staged_slot_map().get(slot_key) if slot_key is not None else None
        draft = self._drafts.get(slot_key) if slot_key is not None else None

        # Build a temporary raw row with the new entry_values merged
        raw_row = dict(row_data)
        raw_values = dict(raw_row.get("values") or {})
        raw_values.update(self.normalize_entry_values(entry_values))
        raw_row["values"] = raw_values
        raw_row["color_value"] = str(raw_values.get(color_key) or "")

        # For the resolver, we compute confirmed/locked from staged vs draft
        row_locked = bool(staged and not staged.get("editable"))
        row_confirmed = bool(staged) and not isinstance(draft, dict)

        raw_row["row_locked"] = row_locked
        raw_row["row_confirmed"] = row_confirmed
        raw_row["search_text"] = " ".join(
            str(raw_values.get(c, "")) for c in data_columns
        ).lower()

        if staged and not draft:
            raw_row["slot_state"] = (
                SlotState.STAGED.value
                if staged.get("editable")
                else SlotState.STAGED_LOCKED.value
            )
        elif draft is not None:
            raw_row["slot_state"] = SlotState.DRAFT.value
        else:
            raw_row["slot_state"] = SlotState.EMPTY.value

        return raw_row

    # ── normalisation helpers (exposed for callers) ──────────────────

    def normalize_entry_values(self, values: dict) -> dict:
        """Normalise raw field values (fill blanks, coerce stored_at)."""
        normalized = self._blank_entry_values()
        for column in normalized:
            normalized[column] = str((values or {}).get(column, "") or "").strip()
        stored_at = str(get_input_stored_at(normalized, default="") or "").strip()
        normalized["stored_at"] = stored_at
        normalized["frozen_at"] = stored_at
        return normalized

    def entry_values_signature(self, values: dict) -> tuple:
        """Public wrapper for signature computation."""
        return self._values_signature(values)

    def entry_columns(self) -> set:
        """Return the set of editable column names."""
        return {"stored_at", "frozen_at"} | set(self._field_definitions())

    def staged_entry_values_for_slot(
        self, slot_key: Tuple[int, int]
    ) -> dict:
        """Return normalised staged values, or blank entry values."""
        if slot_key is None:
            return self._blank_entry_values()
        staged = self.staged_slot_map().get(tuple(slot_key))
        if not staged:
            return self._blank_entry_values()
        return self.normalize_entry_values(staged.get("values") or {})

    # ── private helpers ──────────────────────────────────────────────

    def _field_definitions(self) -> dict:
        field_defs = {}
        for field_def in get_effective_fields(self._meta, inventory=self._records):
            if not isinstance(field_def, dict):
                continue
            key = str(field_def.get("key") or "").strip()
            if key:
                field_defs[key] = dict(field_def)
        return field_defs

    def _blank_entry_values(self) -> dict:
        return {column: "" for column in sorted(self.entry_columns())}

    def _values_signature(self, values: dict) -> tuple:
        normalized = self.normalize_entry_values(values)
        return tuple((column, normalized[column]) for column in sorted(normalized))


# ── module-level helpers (no Qt) ─────────────────────────────────────


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_add_item_positions(item: dict) -> tuple:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    raw_positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    if not raw_positions:
        raw_positions = [item.get("position")]
    normalized: list = []
    for raw_position in raw_positions:
        position = _safe_int(raw_position)
        if position is None or position <= 0 or position in normalized:
            continue
        normalized.append(position)
    return tuple(sorted(normalized))


def _slot_key_from_row(row_data: dict) -> Optional[Tuple[int, int]]:
    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is None or position is None:
        return None
    return (box, position)
