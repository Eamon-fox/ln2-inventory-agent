"""Centralized audit details builders for all write operations.

Every write operation calls exactly one builder from this module to
construct its audit `details` dict.  This ensures consistent structure
and complete information across all audit events.

All returned dicts include an ``"op"`` key so every audit event is
self-describing.
"""

# Keys that are part of the record structure, not user-defined custom fields.
_RECORD_STRUCTURAL_KEYS = frozenset({
    "id", "box", "position", "frozen_at", "thaw_events",
    "cell_line", "short_name", "note",
})


def _extract_custom_fields(record):
    """Return a dict of custom (non-structural) fields from a record."""
    if not isinstance(record, dict):
        return {}
    return {k: v for k, v in record.items() if k not in _RECORD_STRUCTURAL_KEYS and v is not None}


def add_entry_details(
    *,
    record_ids,
    box,
    positions,
    frozen_at,
    cell_line=None,
    note=None,
    custom_fields=None,
):
    """Build details for a successful add_entry audit event."""
    details = {
        "op": "add_entry",
        "record_ids": list(record_ids),
        "count": len(record_ids),
        "box": box,
        "positions": [int(p) for p in positions],
        "frozen_at": frozen_at,
    }
    if cell_line:
        details["cell_line"] = cell_line
    if note is not None:
        details["note"] = note
    if custom_fields:
        details["custom_fields"] = dict(custom_fields)
    return details


def edit_entry_details(*, record_id, cell_line=None, short_name=None, box, position, field_changes, note=None, custom_fields=None):
    """Build details for a successful edit_entry audit event.

    *field_changes* maps field names to ``(before, after)`` tuples.
    """
    details = {
        "op": "edit_entry",
        "record_id": record_id,
        "cell_line": cell_line,
        "short_name": short_name,
        "box": box,
        "position": position,
        "field_changes": {
            k: {"before": pair[0], "after": pair[1]}
            for k, pair in field_changes.items()
        },
    }
    if note is not None:
        details["note"] = note
    if custom_fields:
        details["custom_fields"] = dict(custom_fields)
    return details


def takeout_details(*, action, date, records):
    """Build details for a successful takeout/thaw/discard audit event.

    *records* is a list of dicts each containing ``record_id``, ``box``,
    ``position``, ``cell_line``, ``short_name``, ``note``, and optionally
    custom field key-value pairs.
    """
    formatted = []
    for r in records:
        entry = {
            "record_id": r["record_id"],
            "cell_line": r.get("cell_line"),
            "short_name": r.get("short_name"),
            "box": r["box"],
            "position": r["position"],
        }
        if r.get("note") is not None:
            entry["note"] = r["note"]
        custom = r.get("custom_fields")
        if custom:
            entry["custom_fields"] = dict(custom)
        formatted.append(entry)
    return {
        "op": action,
        "date": date,
        "count": len(records),
        "records": formatted,
    }


def move_details(*, date, moves, affected_record_ids):
    """Build details for a successful move audit event.

    *moves* is a list of dicts each containing ``record_id``,
    ``cell_line``, ``short_name``, ``from_box``, ``from_position``,
    ``to_box``, ``to_position``, optionally ``swap_with_record_id``,
    ``note``, and ``custom_fields``.
    """
    formatted = []
    for m in moves:
        entry = {
            "record_id": m["record_id"],
            "cell_line": m.get("cell_line"),
            "short_name": m.get("short_name"),
            "from_box": m["from_box"],
            "from_position": m["from_position"],
            "to_box": m["to_box"],
            "to_position": m["to_position"],
        }
        if m.get("swap_with_record_id") is not None:
            entry["swap_with_record_id"] = m["swap_with_record_id"]
        if m.get("note") is not None:
            entry["note"] = m["note"]
        custom = m.get("custom_fields")
        if custom:
            entry["custom_fields"] = dict(custom)
        formatted.append(entry)
    return {
        "op": "move",
        "date": date,
        "count": len(moves),
        "moves": formatted,
        "affected_record_ids": sorted(affected_record_ids),
    }


def set_box_tag_details(*, box, tag_before, tag_after):
    """Build details for a successful set_box_tag audit event."""
    return {
        "op": "set_box_tag",
        "box": box,
        "tag_before": tag_before,
        "tag_after": tag_after,
    }


def adjust_box_count_details(*, sub_op, preview):
    """Build details for a successful adjust_box_count audit event.

    Extracts only the essential fields from the full *preview* dict.
    """
    details = {
        "op": "adjust_box_count",
        "sub_op": sub_op,
        "box_count_before": preview.get("box_count_before"),
        "box_count_after": preview.get("box_count_after"),
    }
    if sub_op == "add":
        details["added_boxes"] = preview.get("added_boxes", [])
    else:
        details["removed_box"] = preview.get("removed_box")
        renumber_mode = preview.get("renumber_mode")
        if renumber_mode:
            details["renumber_mode"] = renumber_mode
        box_mapping = preview.get("box_mapping")
        if box_mapping:
            details["box_mapping"] = box_mapping
    return details


def rollback_details(*, requested_backup=None, requested_from_event=None):
    """Build details for a rollback audit event (pre-persist).

    ``restored_from`` and ``snapshot_before_rollback`` are added later
    by ``yaml_ops.rollback_yaml()`` after the actual restore.
    """
    details = {"op": "rollback"}
    if requested_backup not in (None, ""):
        details["requested_backup"] = requested_backup
    if requested_from_event:
        details["requested_from_event"] = dict(requested_from_event)
    return details


def failure_details(*, op, **context):
    """Build details for any failed operation audit event.

    Includes ``op`` plus whatever context fields are available at the
    point of failure.
    """
    details = {"op": op}
    for key, value in context.items():
        if value is not None:
            details[key] = value
    return details
