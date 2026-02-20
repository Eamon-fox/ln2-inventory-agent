"""CSV export helpers for full inventory snapshots."""

import csv
import os

from .custom_fields import STRUCTURAL_FIELD_KEYS, get_effective_fields


CORE_EXPORT_COLUMNS = [
    "id",
    "cell_line",
    "short_name",
    "box",
    "position",
    "frozen_at",
    "plasmid_name",
    "plasmid_id",
    "note",
]


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _record_sort_key(record):
    # Tube-level model: each record has a single position field
    position = record.get("position")
    return (
        _safe_int(record.get("box"), 10 ** 9),
        _safe_int(position, 10 ** 9),
        _safe_int(record.get("id"), 10 ** 9),
    )


def build_export_columns(meta=None):
    """Build stable CSV column order for full inventory export.

    Columns are dynamically generated from:
    - Structural fields (id, location, frozen_at, thaw_events, cell_line)
    - User-defined custom fields (from meta.custom_fields)

    Note: location column shows "box:position" format
    """
    from .custom_fields import STRUCTURAL_FIELD_KEYS

    STRUCTURAL_COLUMNS = ["id", "location", "frozen_at", "cell_line", "note", "thaw_events"]

    columns = list(STRUCTURAL_COLUMNS)

    for field_def in get_effective_fields(meta or {}):
        key = str(field_def.get("key") or "").strip()
        if not key:
            continue
        if key in columns:
            continue
        columns.append(key)

    return columns


def _row_value(record, column):
    if column == "location":
        # Merge box:position format
        box = record.get("box")
        position = record.get("position")
        if box is not None and position is not None:
            return f"{box}:{position}"
        return ""
    if column == "thaw_events":
        # Convert thaw_events to human-readable format
        events = record.get("thaw_events")
        if not events or not isinstance(events, list):
            return ""
        # Format: "2026-02-16 move 15→20; 2026-02-17 takeout"
        parts = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            date = ev.get("date", "")
            action = ev.get("action", "")
            from_pos = ev.get("from_position")
            to_pos = ev.get("to_position")
            if action == "move" and from_pos and to_pos:
                parts.append(f"{date} {action} {from_pos}→{to_pos}")
            else:
                parts.append(f"{date} {action}")
        return "; ".join(parts) if parts else ""
    if column == "cell_line":
        value = record.get("cell_line")
    else:
        value = record.get(column)
    if value is None:
        return ""
    # Serialize complex types (list, dict) to JSON for display
    if isinstance(value, (list, dict)):
        import json
        return json.dumps(value, ensure_ascii=False)
    return value


def build_export_rows(records, meta=None):
    """Build normalized rows for inventory export/display reuse.

    Args:
        records: List of inventory records
        meta: Metadata dict with custom_fields
    """
    normalized_records = [record for record in (records or []) if isinstance(record, dict)]
    normalized_records.sort(key=_record_sort_key)

    columns = build_export_columns(meta)
    rows = []
    for record in normalized_records:
        rows.append({column: _row_value(record, column) for column in columns})

    return {
        "columns": columns,
        "rows": rows,
    }


def build_export_rows_from_data(data):
    """Build normalized export rows from loaded YAML payload."""
    inventory = data.get("inventory", []) if isinstance(data, dict) else []
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    return build_export_rows(inventory, meta=meta)


def export_inventory_to_csv(data, output_path):
    """Write full inventory records to CSV and return export metadata."""
    payload = build_export_rows_from_data(data)
    columns = payload["columns"]
    rows = payload["rows"]

    abs_output_path = os.path.abspath(os.fspath(output_path))
    with open(abs_output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(column, "") for column in columns])

    return {
        "path": abs_output_path,
        "count": len(rows),
        "columns": columns,
    }
