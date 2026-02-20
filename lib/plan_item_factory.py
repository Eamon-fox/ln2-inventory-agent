"""Shared builders for plan items used by GUI and AI flows."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, Optional

from lib.thaw_parser import canonicalize_non_move_action, normalize_action

_EXTRA_ACTION_ALIAS = {
    "解冻": "takeout",
    "丢弃": "takeout",
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
        collapsed = canonicalize_non_move_action(normalized)
        return collapsed or normalized
    raw = str(action or "").strip()
    text = raw.lower()
    if text in _EXTRA_ACTION_ALIAS:
        return _EXTRA_ACTION_ALIAS[text]
    if raw in _EXTRA_ACTION_ALIAS:
        return _EXTRA_ACTION_ALIAS[raw]
    if text == "add":
        return "add"
    return text


def resolve_record_box(record: Optional[Dict[str, Any]], fallback_box: int = 0) -> int:
    """Resolve box number from cached record."""
    if isinstance(record, dict):
        try:
            return int(record.get("box", fallback_box) or fallback_box)
        except Exception:
            pass
    return int(fallback_box or 0)


def build_add_plan_item(
    *,
    box: int,
    positions: Iterable[Any],
    frozen_at: Optional[str],
    fields: Optional[Dict[str, Any]] = None,
    source: str = "human",
) -> Dict[str, Any]:
    """Build a normalized add PlanItem payload."""
    fields = dict(fields or {})
    normalized_positions = [int(p) for p in list(positions or [])]
    payload = {
        "box": int(box),
        "positions": normalized_positions,
        "frozen_at": frozen_at,
        "fields": fields,
    }
    return {
        "action": "add",
        "box": int(box),
        "position": normalized_positions[0] if normalized_positions else 1,
        "record_id": None,
        "source": source,
        "payload": payload,
    }


def build_record_plan_item(
    *,
    action: Any,
    record_id: int,
    position: int,
    box: int,
    date_str: Optional[str],
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
    }
    item = {
        "action": action_norm,
        "box": int(box),
        "position": int(position),
        "record_id": int(record_id),
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
    position: int = 1,
    source: str = "human",
) -> Dict[str, Any]:
    """Build a normalized edit PlanItem payload."""
    return {
        "action": "edit",
        "box": int(box),
        "position": int(position) if position else 1,
        "record_id": int(record_id),
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
    source_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a normalized rollback PlanItem payload.

    Rollback items are executed via the Plan queue (human-in-the-loop) and must
    be the only item in the plan batch.

    source_event can be provided to keep a lightweight link to the audit event
    that triggered this rollback request.
    """
    payload: Dict[str, Any] = {
        "backup_path": backup_path,
    }
    if isinstance(source_event, dict):
        compact_event = {
            str(key): value
            for key, value in source_event.items()
            if value not in (None, "")
        }
        if compact_event:
            payload["source_event"] = compact_event

    return {
        "action": "rollback",
        # Keep box/position integers to satisfy existing PlanItem schema.
        "box": 0,
        "position": 1,
        "record_id": None,
        "source": source,
        "payload": payload,
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
