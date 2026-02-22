"""Parsing and slot-validation helpers for Tool API."""

import re

from .position_fmt import display_to_box, display_to_pos, pos_to_display
from .validators import parse_positions, validate_box, validate_position


_POSITION_SCALAR_KEYS = {
    "position",
    "to_position",
    "from_position",
    "old_position",
    "new_position",
    "position_before",
    "position_after",
    "remaining_position",
    "current_position",
    "swap_position_before",
    "swap_position_after",
    "swap_old_position",
    "swap_new_position",
}

_POSITION_LIST_KEYS = {"positions", "empty_positions"}


def _coerce_position_value(raw_value, layout=None, field_name="position"):
    """Convert a display/internal position value to internal integer position."""
    if raw_value in (None, ""):
        raise ValueError(f"{field_name} cannot be empty")
    try:
        return int(display_to_pos(raw_value, layout))
    except Exception as exc:
        raise ValueError(f"{field_name} is invalid: {raw_value}") from exc


def _normalize_positions_input(positions, layout=None):
    """Normalize add-entry positions input into a list of internal integers."""
    if isinstance(positions, str):
        return parse_positions(positions, layout=layout)

    if isinstance(positions, (list, tuple, set)):
        return [_coerce_position_value(value, layout=layout, field_name="position") for value in positions]

    if positions in (None, ""):
        return []

    return [_coerce_position_value(positions, layout=layout, field_name="position")]


def _format_position_value_for_output(value, layout=None):
    """Render one internal position value as display text for API output."""
    if value is None:
        return None
    try:
        return pos_to_display(int(value), layout)
    except Exception:
        return value


def _format_position_list_for_output(values, layout=None):
    """Render a list of internal positions as display texts."""
    if not isinstance(values, (list, tuple)):
        return values
    return [_format_position_value_for_output(value, layout=layout) for value in values]


def _format_positions_in_payload(payload, layout=None):
    """Recursively format all known position fields in API response payloads."""
    if isinstance(payload, dict):
        formatted = {}
        for key, value in payload.items():
            if key in _POSITION_SCALAR_KEYS:
                formatted[key] = _format_position_value_for_output(value, layout=layout)
                continue
            if key in _POSITION_LIST_KEYS:
                formatted[key] = _format_position_list_for_output(value, layout=layout)
                continue
            if key == "occupancy" and isinstance(value, dict):
                occ = {}
                for box_key, positions in value.items():
                    occ[box_key] = _format_position_list_for_output(positions, layout=layout)
                formatted[key] = occ
                continue
            formatted[key] = _format_positions_in_payload(value, layout=layout)
        return formatted

    if isinstance(payload, list):
        return [_format_positions_in_payload(item, layout=layout) for item in payload]

    if isinstance(payload, tuple):
        return tuple(_format_positions_in_payload(item, layout=layout) for item in payload)

    return payload


def parse_batch_entries(entries_str, layout=None):
    """Parse batch input format.

    Supports:
    - ``id1,id2,...`` (use current active position for each tube id; takeout only)
    - ``id1:pos1,id2:pos2,...`` (takeout)
    - ``id1:from1->to1,id2:from2->to2,...`` (move within same box)
    - ``id1:from1->to1:box,id2:from2->to2:box,...`` (cross-box move)

    ``pos/from/to`` accepts display values under current layout (e.g. ``A1``).
    """
    result = []
    try:
        for entry in str(entries_str).split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" not in entry:
                result.append((int(entry),))
                continue

            parts = entry.split(":")
            record_id = int(parts[0])
            pos_text = parts[1].strip() if len(parts) >= 2 else ""
            if not pos_text:
                result.append((record_id,))
                continue

            to_box = int(parts[2]) if len(parts) >= 3 else None
            if "->" in pos_text:
                from_pos_text, to_pos_text = pos_text.split("->", 1)
                tup = (
                    record_id,
                    _coerce_position_value(from_pos_text, layout=layout, field_name="from_position"),
                    _coerce_position_value(to_pos_text, layout=layout, field_name="to_position"),
                )
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            elif ">" in pos_text:
                from_pos_text, to_pos_text = pos_text.split(">", 1)
                tup = (
                    record_id,
                    _coerce_position_value(from_pos_text, layout=layout, field_name="from_position"),
                    _coerce_position_value(to_pos_text, layout=layout, field_name="to_position"),
                )
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            else:
                result.append((record_id, _coerce_position_value(pos_text, layout=layout, field_name="position")))
    except Exception as exc:
        raise ValueError(
            "Invalid input format: "
            f"{exc}. Valid examples: '182,183' or '182:23,183:41' or '182:23->31,183:41->42' or '182:23->31:1' (cross-box)"
        )
    return result


def _coerce_batch_entry(entry, layout=None):
    """Normalize one batch entry to a tuple of ints.

    Accepts tuple/list forms ``(record_id, position)`` or ``(record_id, from_pos, to_pos)``
    and dict forms with common aliases.
    """
    if isinstance(entry, dict):
        record_id = entry.get("record_id", entry.get("id"))
        from_pos = entry.get("position")
        if from_pos is None:
            from_pos = entry.get("from_position", entry.get("from_pos", entry.get("from")))
        to_pos = entry.get("to_position")
        if to_pos is None:
            to_pos = entry.get("to_pos", entry.get("target_position", entry.get("target_pos")))
        to_box = entry.get("to_box")

        if record_id is None:
            raise ValueError("Each item must include record_id/id")
        if from_pos is None:
            if to_pos is None:
                return (int(record_id),)
            raise ValueError("Each item must include position/from_position")
        if to_pos is None:
            return (int(record_id), _coerce_position_value(from_pos, layout=layout, field_name="position"))
        if to_box is not None:
            return (
                int(record_id),
                _coerce_position_value(from_pos, layout=layout, field_name="from_position"),
                _coerce_position_value(to_pos, layout=layout, field_name="to_position"),
                int(to_box),
            )
        return (
            int(record_id),
            _coerce_position_value(from_pos, layout=layout, field_name="from_position"),
            _coerce_position_value(to_pos, layout=layout, field_name="to_position"),
        )

    if isinstance(entry, (list, tuple)):
        if len(entry) == 1:
            return (int(entry[0]),)
        if len(entry) == 2:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="position"),
            )
        if len(entry) == 3:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="from_position"),
                _coerce_position_value(entry[2], layout=layout, field_name="to_position"),
            )
        if len(entry) == 4:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="from_position"),
                _coerce_position_value(entry[2], layout=layout, field_name="to_position"),
                int(entry[3]),
            )
        raise ValueError(
            "Each item must be (record_id) or (record_id, position) or (record_id, from_position, to_position[, to_box])"
        )

    raise ValueError("Each item must be tuple/list/dict")


def _parse_slot_payload(slot_payload, *, layout, field_name):
    """Normalize one V2 slot payload into internal ``(box, position)``."""
    if not isinstance(slot_payload, dict):
        raise ValueError(f"{field_name} must be an object with box/position")
    if "box" not in slot_payload:
        raise ValueError(f"{field_name}.box is required")
    if "position" not in slot_payload:
        raise ValueError(f"{field_name}.position is required")
    try:
        box = int(display_to_box(slot_payload.get("box"), layout))
    except Exception as exc:
        raise ValueError(f"{field_name}.box is invalid: {slot_payload.get('box')}") from exc
    pos = _coerce_position_value(
        slot_payload.get("position"),
        layout=layout,
        field_name=f"{field_name}.position",
    )
    return box, pos


def _find_record_by_id_local(records, record_id):
    """Return record dict by ``id`` from loaded inventory list."""
    target = int(record_id)
    for rec in records or []:
        try:
            rid = int(rec.get("id"))
        except Exception:
            continue
        if rid == target:
            return rec
    return None


def _validate_source_slot_match(record, *, record_id, from_box, from_pos):
    """Return issue payload if source slot does not match active record slot."""
    if record is None:
        return {
            "error_code": "record_not_found",
            "message": f"Record ID {record_id} not found",
            "details": {"record_id": record_id},
        }

    current_box = record.get("box")
    current_pos = record.get("position")
    if current_pos is None:
        return {
            "error_code": "position_not_found",
            "message": f"Record ID {record_id} has no active position",
            "details": {"record_id": record_id},
        }

    try:
        current_box_int = int(current_box)
        current_pos_int = int(current_pos)
    except Exception:
        return {
            "error_code": "validation_failed",
            "message": f"Record ID {record_id} has invalid box/position fields",
            "details": {"record_id": record_id},
        }

    if current_box_int != int(from_box) or current_pos_int != int(from_pos):
        return {
            "error_code": "from_mismatch",
            "message": (
                f"Record ID {record_id} source mismatch: requested "
                f"Box {from_box}:{from_pos}, current Box {current_box_int}:{current_pos_int}"
            ),
            "details": {
                "record_id": record_id,
                "from_box": from_box,
                "from_position": from_pos,
                "current_box": current_box_int,
                "current_position": current_pos_int,
            },
        }

    return None


def _record_search_blob(record, case_sensitive=False):
    """Build a normalized text blob from one inventory record for matching."""
    parts = []
    for value in (record or {}).values():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (str, int, float, bool)):
                    parts.append(str(item))
    blob = " ".join(parts)
    return blob if case_sensitive else blob.lower()


def _parse_search_location_shortcut(query_text, layout):
    """Parse compact location query like ``2:15`` into (box, position)."""
    text = str(query_text or "").strip()
    if not text:
        return None

    # Support both ASCII ":" and full-width Chinese "?".
    match = re.match(r"^(?:box\s*)?([^:\s]+)\s*[:?]\s*([^:\s]+)$", text, flags=re.IGNORECASE)
    if not match:
        return None

    raw_box, raw_position = match.group(1), match.group(2)
    try:
        box_num = int(display_to_box(raw_box, layout))
        pos_num = int(display_to_pos(raw_position, layout))
    except Exception:
        return None

    if not validate_box(box_num, layout):
        return None
    if not validate_position(pos_num, layout):
        return None
    return box_num, pos_num
