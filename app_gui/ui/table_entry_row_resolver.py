"""Pure-function row resolver for table inline-entry overlays.

This module has **zero** Qt or GUI dependencies.  It takes raw projection
rows together with draft/staged snapshots and returns resolved rows ready
for the rendering layer.

Slot state semantics
--------------------
- ``empty``         – untouched empty slot (no draft, no staged item)
- ``draft``         – user has edited but not yet confirmed
- ``staged``        – confirmed, sitting in plan store (single-slot, editable)
- ``staged_locked`` – confirmed, multi-slot, not editable from the table
"""

from __future__ import annotations

import enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class SlotState(enum.Enum):
    EMPTY = "empty"
    DRAFT = "draft"
    STAGED = "staged"
    STAGED_LOCKED = "staged_locked"


# ── helpers ──────────────────────────────────────────────────────────


def _slot_key(row: dict) -> Optional[Tuple[int, int]]:
    """Extract (box, position) key from a row dict, or *None*."""
    try:
        box = int(row["box"])
        position = int(row["position"])
    except (KeyError, TypeError, ValueError):
        return None
    return (box, position)


def _row_search_text(columns: Sequence[str], values: dict) -> str:
    return " ".join(str(values.get(c, "")) for c in columns).lower()


# ── single-row resolver ─────────────────────────────────────────────


def resolve_entry_row(
    raw_row: Dict[str, Any],
    draft_values: Optional[Dict[str, str]],
    staged_info: Optional[Dict[str, Any]],
    data_columns: Sequence[str],
    color_key: str,
    normalize_fn: Callable[[dict], dict],
) -> Dict[str, Any]:
    """Resolve a single projection row against draft and staged state.

    Parameters
    ----------
    raw_row:
        Row dict from ``build_overview_table_projection`` (must contain at
        least ``row_kind``, ``box``, ``position``, ``values``).
    draft_values:
        User-edited field values (or *None* if no draft for this slot).
    staged_info:
        Dict with keys ``values``, ``editable``, ``color_value`` produced by
        the draft-store's staged-slot-map, or *None*.
    data_columns:
        Ordered data column names (for search-text generation).
    color_key:
        The active color-key field name.
    normalize_fn:
        A callable ``(raw_values) -> normalized_values`` that fills blanks
        and coerces types (mirrors ``_normalize_entry_values``).

    Returns
    -------
    dict  – a **copy** of *raw_row* with extra keys:
        ``row_confirmed``, ``row_locked``, ``slot_state`` (str value of
        :class:`SlotState`), ``color_value``, ``search_text``.
    """
    row = dict(raw_row)
    values = dict(row.get("values") or {})
    row_kind = str(row.get("row_kind") or "")

    row_confirmed = False
    row_locked = False
    slot_state = SlotState.EMPTY

    if row_kind == "empty_slot":
        if isinstance(draft_values, dict):
            # Draft takes priority over staged
            values.update(normalize_fn(draft_values))
            row_locked = bool(staged_info and not staged_info.get("editable"))
            slot_state = SlotState.DRAFT
        elif staged_info:
            values.update(normalize_fn(staged_info.get("values") or {}))
            row_confirmed = True
            editable = bool(staged_info.get("editable"))
            row_locked = not editable
            slot_state = SlotState.STAGED if editable else SlotState.STAGED_LOCKED
        # else: stays EMPTY

        row["color_value"] = str(values.get(color_key) or "")

    row["values"] = values
    row["row_confirmed"] = row_confirmed
    row["row_locked"] = row_locked
    row["slot_state"] = slot_state.value
    row["search_text"] = _row_search_text(data_columns, values)
    return row


# ── batch resolver ───────────────────────────────────────────────────


def resolve_entry_rows(
    raw_rows: List[Dict[str, Any]],
    draft_map: Dict[Tuple[int, int], dict],
    staged_map: Dict[Tuple[int, int], dict],
    data_columns: Sequence[str],
    color_key: str,
    normalize_fn: Callable[[dict], dict],
) -> List[Dict[str, Any]]:
    """Resolve a batch of projection rows.

    Parameters
    ----------
    draft_map:
        ``{(box, position): values_dict}`` – current draft edits.
    staged_map:
        ``{(box, position): staged_info_dict}`` – from plan-store query.
    """
    resolved = []
    for raw_row in raw_rows:
        sk = _slot_key(raw_row)
        draft = draft_map.get(sk) if sk is not None else None
        staged = staged_map.get(sk) if sk is not None else None
        resolved.append(
            resolve_entry_row(
                raw_row,
                draft_values=draft,
                staged_info=staged,
                data_columns=data_columns,
                color_key=color_key,
                normalize_fn=normalize_fn,
            )
        )
    return resolved
