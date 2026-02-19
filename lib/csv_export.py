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


def _position_text(record):
    positions = record.get("positions") or []
    if not positions:
        return ""
    if len(positions) == 1:
        return str(positions[0])
    return ",".join(str(pos) for pos in positions)


def _record_sort_key(record):
    positions = record.get("positions") or []
    first_pos = positions[0] if positions else 10 ** 9
    return (
        _safe_int(record.get("box"), 10 ** 9),
        _safe_int(first_pos, 10 ** 9),
        _safe_int(record.get("id"), 10 ** 9),
    )


def build_export_columns(meta=None):
    """Build stable CSV column order for full inventory export.
    
    Columns are dynamically generated from:
    - Structural fields (id, box, position, frozen_at, thaw_events, cell_line)
    - User-defined custom fields (from meta.custom_fields)
    """
    from .custom_fields import STRUCTURAL_FIELD_KEYS
    
    STRUCTURAL_COLUMNS = ["id", "box", "position", "frozen_at", "thaw_events", "cell_line"]
    
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
    if column == "position":
        return _position_text(record)
    if column == "cell_line":
        value = record.get("cell_line")
    else:
        value = record.get(column)
    if value is None:
        return ""
    return value


def build_export_rows(records, meta=None):
    """Build normalized rows for inventory export/display reuse."""
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
