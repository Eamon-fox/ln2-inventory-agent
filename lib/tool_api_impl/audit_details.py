"""Centralized audit details builders for all write operations.

Every write operation calls exactly one builder from this module to
construct its audit `details` dict.  This ensures consistent structure
and complete information across all audit events.

All returned dicts include an ``"op"`` key so every audit event is
self-describing.
"""

from ..schema_aliases import ALL_STRUCTURAL_FIELD_KEYS

# Keys that are part of the record structure, not user-defined custom fields.
_RECORD_STRUCTURAL_KEYS = ALL_STRUCTURAL_FIELD_KEYS


def _normalize_field_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    return value


def _coerce_field_payload(value):
    if not isinstance(value, dict):
        return {}
    payload = {}
    for key, raw in value.items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        normalized = _normalize_field_value(raw)
        if normalized is None:
            continue
        payload[text_key] = normalized
    return payload


def _merge_fields_payload(
    *,
    fields=None,
    legacy_fields=None,
    cell_line=None,
    short_name=None,
    note=None,
    custom_fields=None,
):
    """Build schema-first fields payload with backward-compatible fallbacks."""
    merged_fields = _coerce_field_payload(fields)
    for key, value in (
        ("cell_line", cell_line),
        ("short_name", short_name),
        ("note", note),
    ):
        normalized = _normalize_field_value(value)
        if normalized is None:
            continue
        merged_fields.setdefault(key, normalized)

    for key, value in _coerce_field_payload(custom_fields).items():
        merged_fields.setdefault(key, value)

    merged_legacy = _coerce_field_payload(legacy_fields)
    return merged_fields, merged_legacy


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
    fields=None,
    legacy_fields=None,
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
    field_payload, legacy_payload = _merge_fields_payload(
        fields=fields,
        legacy_fields=legacy_fields,
        cell_line=cell_line,
        note=note,
        custom_fields=custom_fields,
    )
    if field_payload:
        details["fields"] = field_payload
    if legacy_payload:
        details["legacy_fields"] = legacy_payload
    return details


def edit_entry_details(
    *,
    record_id,
    box,
    position,
    field_changes,
    fields=None,
    legacy_fields=None,
    cell_line=None,
    short_name=None,
    note=None,
    custom_fields=None,
):
    """Build details for a successful edit_entry audit event.

    *field_changes* maps field names to ``(before, after)`` tuples.
    """
    details = {
        "op": "edit_entry",
        "record_id": record_id,
        "box": box,
        "position": position,
        "field_changes": {
            k: {"before": pair[0], "after": pair[1]}
            for k, pair in field_changes.items()
        },
    }
    field_payload, legacy_payload = _merge_fields_payload(
        fields=fields,
        legacy_fields=legacy_fields,
        cell_line=cell_line,
        short_name=short_name,
        note=note,
        custom_fields=custom_fields,
    )
    if field_payload:
        details["fields"] = field_payload
    if legacy_payload:
        details["legacy_fields"] = legacy_payload
    return details


def takeout_details(*, action, date, records):
    """Build details for a successful takeout/thaw/discard audit event.

    *records* is a list of dicts each containing ``record_id``, ``box``,
    ``position``, ``cell_line``, ``short_name``, ``note``, and optionally
    custom field key-value pairs.
    """
    formatted = []
    for r in records:
        field_payload, legacy_payload = _merge_fields_payload(
            fields=r.get("fields"),
            legacy_fields=r.get("legacy_fields"),
            cell_line=r.get("cell_line"),
            short_name=r.get("short_name"),
            note=r.get("note"),
            custom_fields=r.get("custom_fields"),
        )
        entry = {
            "record_id": r["record_id"],
            "box": r["box"],
            "position": r["position"],
        }
        if field_payload:
            entry["fields"] = field_payload
        if legacy_payload:
            entry["legacy_fields"] = legacy_payload
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
        field_payload, legacy_payload = _merge_fields_payload(
            fields=m.get("fields"),
            legacy_fields=m.get("legacy_fields"),
            cell_line=m.get("cell_line"),
            short_name=m.get("short_name"),
            note=m.get("note"),
            custom_fields=m.get("custom_fields"),
        )
        entry = {
            "record_id": m["record_id"],
            "from_box": m["from_box"],
            "from_position": m["from_position"],
            "to_box": m["to_box"],
            "to_position": m["to_position"],
        }
        if m.get("swap_with_record_id") is not None:
            entry["swap_with_record_id"] = m["swap_with_record_id"]
        if field_payload:
            entry["fields"] = field_payload
        if legacy_payload:
            entry["legacy_fields"] = legacy_payload
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


def manage_boxes_details(*, sub_op, preview):
    """Build details for a successful manage_boxes audit event.

    Extracts only the essential fields from the full *preview* dict.
    """
    details = {
        "op": "manage_boxes",
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
