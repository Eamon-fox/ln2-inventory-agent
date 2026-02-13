"""Shared builders for plan items used by GUI and AI flows."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, Optional

from lib.thaw_parser import normalize_action

_EXTRA_ACTION_ALIAS = {
    "解冻": "thaw",
    "丢弃": "discard",
    "take out": "takeout",
    "add_entry": "add",
    "新增": "add",
    "edit_entry": "edit",
    "编辑": "edit",
}


def normalize_plan_action(action: Any) -> str:
    """Normalize action text into canonical plan action."""
    normalized = normalize_action(action)
    if normalized:
        return normalized
    raw = str(action or "").strip()
    text = raw.lower()
    if text in _EXTRA_ACTION_ALIAS:
        return _EXTRA_ACTION_ALIAS[text]
    if raw in _EXTRA_ACTION_ALIAS:
        return _EXTRA_ACTION_ALIAS[raw]
    if text == "add":
        return "add"
    return text


def resolve_record_context(record: Optional[Dict[str, Any]], fallback_box: int = 0) -> tuple[int, str]:
    """Resolve (box, label) from cached record."""
    box = int(fallback_box or 0)
    label = "-"
    if isinstance(record, dict):
        label = record.get("short_name") or record.get("parent_cell_line") or "-"
        try:
            box = int(record.get("box", box) or box)
        except Exception:
            pass
    return box, str(label or "-")


def build_add_plan_item(
    *,
    parent_cell_line: str,
    short_name: str,
    box: int,
    positions: Iterable[Any],
    frozen_at: Optional[str],
    plasmid_name: Optional[str] = None,
    plasmid_id: Optional[str] = None,
    note: Optional[str] = None,
    custom_data: Optional[Dict[str, Any]] = None,
    source: str = "human",
) -> Dict[str, Any]:
    """Build a normalized add PlanItem payload."""
    normalized_positions = [int(p) for p in list(positions or [])]
    payload = {
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "box": int(box),
        "positions": normalized_positions,
        "frozen_at": frozen_at,
        "plasmid_name": plasmid_name,
        "plasmid_id": plasmid_id,
        "note": note,
    }
    if custom_data and isinstance(custom_data, dict):
        payload["custom_data"] = custom_data
    return {
        "action": "add",
        "box": int(box),
        "position": normalized_positions[0] if normalized_positions else 1,
        "record_id": None,
        "label": (short_name or parent_cell_line or "-"),
        "source": source,
        "payload": payload,
    }


def build_record_plan_item(
    *,
    action: Any,
    record_id: int,
    position: int,
    box: int,
    label: str,
    date_str: Optional[str],
    note: Optional[str] = None,
    to_position: Optional[int] = None,
    to_box: Optional[int] = None,
    source: str = "human",
    payload_action: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a normalized non-add PlanItem payload."""
    action_norm = normalize_plan_action(action) or "takeout"
    if to_position is not None:
        action_norm = "move"

    payload = {
        "record_id": int(record_id),
        "position": int(position),
        "date_str": date_str,
        "action": payload_action if payload_action is not None else str(action or ""),
        "note": note,
    }
    item = {
        "action": action_norm,
        "box": int(box),
        "position": int(position),
        "record_id": int(record_id),
        "label": str(label or "-"),
        "source": source,
        "payload": payload,
    }

    if to_position is not None:
        tp = int(to_position)
        item["to_position"] = tp
        payload["to_position"] = tp
    if to_box is not None:
        tb = int(to_box)
        item["to_box"] = tb
        payload["to_box"] = tb

    return item


def build_edit_plan_item(
    *,
    record_id: int,
    fields: Dict[str, Any],
    box: int = 0,
    label: str = "-",
    source: str = "human",
) -> Dict[str, Any]:
    """Build a normalized edit PlanItem payload."""
    return {
        "action": "edit",
        "box": int(box),
        "position": 0,
        "record_id": int(record_id),
        "label": str(label or "-"),
        "source": source,
        "payload": {
            "record_id": int(record_id),
            "fields": dict(fields),
        },
    }


def build_rollback_plan_item(
    *,
    backup_path: Optional[str],
    source: str = "human",
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a normalized rollback PlanItem payload.

    Rollback items are executed via the Plan queue (human-in-the-loop) and must
    be the only item in the plan batch.
    """
    display_label = label
    if not display_label:
        display_label = "Rollback"
        if backup_path:
            try:
                import os

                display_label = f"Rollback: {os.path.basename(str(backup_path))}"
            except Exception:
                display_label = "Rollback"

    return {
        "action": "rollback",
        # Keep box/position integers to satisfy existing PlanItem schema.
        "box": 0,
        "position": 1,
        "record_id": None,
        "label": display_label,
        "source": source,
        "payload": {
            "backup_path": backup_path,
        },
    }


def iter_batch_entries(
    entries: Iterable[Any],
    *,
    default_to_box: Optional[int] = None,
) -> Iterator[Dict[str, Optional[int]]]:
    """Yield normalized batch rows from tuple/dict entries."""
    if entries is None:
        return

    for entry in entries:
        to_position = None
        to_box = default_to_box

        if isinstance(entry, (list, tuple)):
            if len(entry) >= 4:
                record_id = int(entry[0])
                position = int(entry[1])
                to_position = int(entry[2])
                to_box = int(entry[3])
            elif len(entry) == 3:
                record_id = int(entry[0])
                position = int(entry[1])
                to_position = int(entry[2])
            elif len(entry) == 2:
                record_id = int(entry[0])
                position = int(entry[1])
            else:
                continue
        elif isinstance(entry, dict):
            record_id = int(entry.get("record_id", entry.get("id", 0)))
            position = int(entry.get("position", entry.get("from_position", 0)))
            raw_to_position = entry.get("to_position")
            if raw_to_position not in (None, ""):
                to_position = int(raw_to_position)
            raw_to_box = entry.get("to_box")
            if raw_to_box not in (None, ""):
                to_box = int(raw_to_box)
        else:
            continue

        yield {
            "record_id": record_id,
            "position": position,
            "to_position": to_position,
            "to_box": to_box,
        }
