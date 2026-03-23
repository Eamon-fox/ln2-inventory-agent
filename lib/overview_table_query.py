"""Shared Overview table projection, filtering, and sorting helpers."""

from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from functools import cmp_to_key
from typing import Any

from .csv_export import build_export_rows
from .custom_fields import get_color_key
from .position_fmt import display_to_pos, format_box_position_compact, get_box_numbers
from .validators import parse_date


_KNOWN_COLUMN_TYPES = {
    "id": "number",
    "frozen_at": "date",
    "stored_at": "date",
    "location": "text",
    "thaw_events": "text",
    "storage_events": "text",
}

_VALID_FILTER_TYPES = frozenset({"list", "text", "number", "date"})


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_number(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    with suppress(TypeError, ValueError):
        return int(text)
    with suppress(TypeError, ValueError):
        return float(text)
    return None


def _normalize_text(value):
    return " ".join(str(value or "").split()).strip()


def _normalize_position_value(value, layout=None):
    position = _safe_int(value)
    if position is not None:
        return position
    with suppress(TypeError, ValueError):
        return int(display_to_pos(value, layout))
    return None


def _projection_box_numbers(layout, records):
    layout = layout if isinstance(layout, dict) else {}
    raw_numbers = list(get_box_numbers(layout) or [])
    if "box_numbers" in layout or "box_count" in layout:
        return raw_numbers

    record_numbers = []
    seen = set()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        box_num = _safe_int(record.get("box"))
        if box_num is None or box_num in seen:
            continue
        seen.add(box_num)
        record_numbers.append(box_num)
    if record_numbers:
        record_numbers.sort()
        return record_numbers
    return raw_numbers


def _empty_slot_row(columns, *, box, position, meta=None, inventory=None):
    values = {str(column): "" for column in list(columns or [])}
    values["location"] = format_box_position_compact(box, position, layout=meta.get("box_layout") if isinstance(meta, dict) else {})
    search_text = " ".join(str(values.get(column, "")) for column in values).lower()
    return {
        "row_kind": "empty_slot",
        "record_id": None,
        "record": None,
        "box": int(box),
        "position": int(position),
        "active": True,
        "color_value": "",
        "values": values,
        "search_text": search_text,
    }


def build_overview_table_projection(records, *, meta=None, layout=None, include_empty_slots=False):
    """Project inventory records into the Overview table row model."""
    payload = build_export_rows(records or [], meta=meta or {})
    columns = list(payload.get("columns") or [])
    color_key = get_color_key(meta or {}, inventory=records or [])

    records_by_id = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        record_id = _safe_int(record.get("id"))
        if record_id is not None:
            records_by_id[record_id] = record

    rows = []
    for values in payload.get("rows") or []:
        record_id = _safe_int(values.get("id"))
        record = records_by_id.get(record_id)

        box = _safe_int(record.get("box")) if isinstance(record, dict) else None
        position = _normalize_position_value(
            record.get("position") if isinstance(record, dict) else None,
            layout,
        )
        active = position is not None

        color_value = ""
        if isinstance(record, dict):
            color_value = str(record.get(color_key) or "")
        elif color_key in values:
            color_value = str(values.get(color_key) or "")

        search_text = " ".join(str(values.get(column, "")) for column in columns).lower()
        rows.append(
            {
                "row_kind": "active" if active else "taken_out",
                "record_id": record_id,
                "record": record,
                "box": box,
                "position": position,
                "active": active,
                "color_value": color_value,
                "values": dict(values),
                "search_text": search_text,
            }
        )

    if include_empty_slots:
        effective_layout = layout if isinstance(layout, dict) else ((meta or {}).get("box_layout") or {})
        box_numbers = _projection_box_numbers(effective_layout, records or [])
        rows_per_box = _safe_int((effective_layout or {}).get("rows")) or 9
        cols_per_box = _safe_int((effective_layout or {}).get("cols")) or 9
        total_slots = max(1, rows_per_box * cols_per_box)
        occupied = {
            (int(row["box"]), int(row["position"]))
            for row in rows
            if row.get("row_kind") == "active"
            and row.get("box") is not None
            and row.get("position") is not None
        }
        for box_num in list(box_numbers or []):
            for position in range(1, total_slots + 1):
                key = (int(box_num), int(position))
                if key in occupied:
                    continue
                rows.append(
                    _empty_slot_row(
                        columns,
                        box=box_num,
                        position=position,
                        meta=meta or {},
                        inventory=records or [],
                    )
                )

    return {
        "columns": columns,
        "color_key": color_key,
        "rows": rows,
    }


def get_unique_overview_table_values(rows, column_name):
    """Return unique display values and counts for one Overview table column."""
    value_counts = defaultdict(int)
    for row in rows or []:
        value = (row.get("values") or {}).get(column_name)
        if value in (None, ""):
            continue
        value_counts[str(value)] += 1

    return sorted(value_counts.items(), key=lambda item: (-item[1], item[0]))


def detect_overview_table_column_type(column_name, *, meta=None, rows=None):
    """Infer the Overview table filter/sort type for one column."""
    normalized_column = str(column_name or "").strip()
    if normalized_column in _KNOWN_COLUMN_TYPES:
        return _KNOWN_COLUMN_TYPES[normalized_column]

    custom_fields = []
    if isinstance(meta, dict):
        custom_fields = list(meta.get("custom_fields") or [])
    for field in custom_fields:
        if not isinstance(field, dict):
            continue
        field_key = str(field.get("key") or field.get("name") or "").strip()
        if field_key != normalized_column:
            continue
        field_type = str(field.get("type") or "str").strip().lower()
        if field_type in {"int", "float", "number"}:
            return "number"
        if field_type in {"date", "datetime"}:
            return "date"
        break

    unique_values = get_unique_overview_table_values(rows or [], normalized_column)
    if unique_values and len(unique_values) <= 20:
        return "list"
    return "text"


def overview_table_column_types(columns, *, meta=None, rows=None):
    return {
        str(column): detect_overview_table_column_type(column, meta=meta, rows=rows)
        for column in list(columns or [])
    }


def normalize_overview_table_column_filters(columns, column_filters):
    """Validate and normalize column_filters for Overview table queries."""
    if column_filters in (None, ""):
        return {}
    if not isinstance(column_filters, dict):
        raise ValueError("column_filters must be an object keyed by column name")

    known_columns = {str(column) for column in list(columns or [])}
    normalized = {}
    for raw_column, raw_config in column_filters.items():
        column_name = str(raw_column or "").strip()
        if not column_name:
            raise ValueError("column_filters must not contain empty column names")
        if column_name not in known_columns:
            raise ValueError(f"Unknown filter column: {column_name}")
        if not isinstance(raw_config, dict):
            raise ValueError(f"column_filters.{column_name} must be an object")

        filter_type = str(raw_config.get("type") or "").strip().lower()
        if filter_type not in _VALID_FILTER_TYPES:
            raise ValueError(
                f"column_filters.{column_name}.type must be one of: list, text, number, date"
            )

        if filter_type == "list":
            raw_values = raw_config.get("values")
            if not isinstance(raw_values, list):
                raise ValueError(f"column_filters.{column_name}.values must be an array")
            values = [str(value) for value in raw_values if str(value) != ""]
            if not values:
                continue
            normalized[column_name] = {"type": "list", "values": values}
            continue

        if filter_type == "text":
            text = _normalize_text(raw_config.get("text"))
            if not text:
                continue
            normalized[column_name] = {"type": "text", "text": text}
            continue

        if filter_type == "number":
            min_value = raw_config.get("min")
            max_value = raw_config.get("max")
            try:
                normalized_min = float(min_value) if min_value not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"column_filters.{column_name}.min must be numeric when provided"
                ) from exc
            try:
                normalized_max = float(max_value) if max_value not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"column_filters.{column_name}.max must be numeric when provided"
                ) from exc
            if normalized_min is None and normalized_max is None:
                continue
            normalized[column_name] = {
                "type": "number",
                "min": normalized_min,
                "max": normalized_max,
            }
            continue

        date_from = _normalize_text(raw_config.get("from"))
        date_to = _normalize_text(raw_config.get("to"))
        if not date_from and not date_to:
            continue
        if date_from and parse_date(date_from) is None:
            raise ValueError(
                f"column_filters.{column_name}.from must be YYYY-MM-DD when provided"
            )
        if date_to and parse_date(date_to) is None:
            raise ValueError(
                f"column_filters.{column_name}.to must be YYYY-MM-DD when provided"
            )
        normalized[column_name] = {"type": "date", "from": date_from or None, "to": date_to or None}

    return normalized


def match_overview_table_column_filter(row_data, column_name, filter_config):
    """Return True when one row matches one normalized Overview column filter."""
    value = (row_data.get("values") or {}).get(column_name)
    filter_type = str((filter_config or {}).get("type") or "").strip().lower()

    if filter_type == "list":
        values = {str(item) for item in list(filter_config.get("values") or [])}
        return str(value) in values

    if filter_type == "text":
        search_text = str(filter_config.get("text") or "").lower()
        return search_text in str(value or "").lower()

    if filter_type == "number":
        numeric_value = _safe_number(value)
        if numeric_value is None:
            return False
        min_value = filter_config.get("min")
        max_value = filter_config.get("max")
        if min_value is not None and numeric_value < min_value:
            return False
        if max_value is not None and numeric_value > max_value:
            return False
        return True

    if filter_type == "date":
        parsed_value = parse_date(value)
        if parsed_value is None:
            return False
        date_from = filter_config.get("from")
        date_to = filter_config.get("to")
        if date_from:
            from_date = parse_date(date_from)
            if from_date is not None and parsed_value < from_date:
                return False
        if date_to:
            to_date = parse_date(date_to)
            if to_date is not None and parsed_value > to_date:
                return False
        return True

    return True


def filter_overview_table_rows(
    rows,
    *,
    keyword="",
    box=None,
    color_value=None,
    include_inactive=False,
    column_filters=None,
):
    """Apply Overview-table top filters and column filters to projected rows."""
    normalized_keyword = _normalize_text(keyword).lower()
    normalized_color_value = None
    if color_value not in (None, ""):
        normalized_color_value = str(color_value)

    filtered = []
    matched_boxes = set()
    for row_data in rows or []:
        row_box = row_data.get("box")
        row_color_value = str(row_data.get("color_value") or "")
        row_active = bool(row_data.get("active"))

        if box is not None and row_box != box:
            continue
        if normalized_color_value is not None and row_color_value != normalized_color_value:
            continue
        if not include_inactive and not row_active:
            continue
        if normalized_keyword and normalized_keyword not in str(row_data.get("search_text") or ""):
            continue

        matched = True
        for column_name, filter_config in dict(column_filters or {}).items():
            if not match_overview_table_column_filter(row_data, column_name, filter_config):
                matched = False
                break
        if not matched:
            continue

        filtered.append(row_data)
        if row_box is not None:
            matched_boxes.add(int(row_box))

    return filtered, sorted(matched_boxes)


def _location_sort_value(row_data):
    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is None or position is None:
        return None
    return box, position


def _text_sort_value(value):
    text = str(value or "").strip()
    if not text:
        return None
    return text.casefold()


def _column_sort_value(row_data, column_name, *, column_types=None):
    normalized_column = str(column_name or "").strip()
    if normalized_column == "location":
        return _location_sort_value(row_data)
    if normalized_column == "id":
        return _safe_number((row_data.get("values") or {}).get("id"))

    value = (row_data.get("values") or {}).get(normalized_column)
    column_type = str((column_types or {}).get(normalized_column) or "text")
    if column_type == "number":
        return _safe_number(value)
    if column_type == "date":
        return parse_date(value)
    return _text_sort_value(value)


def sort_overview_table_rows(rows, *, sort_by="location", sort_order="asc", column_types=None):
    """Sort projected Overview rows using shared table semantics."""
    normalized_sort_by = str(sort_by or "location").strip() or "location"
    normalized_sort_order = str(sort_order or "asc").strip().lower() or "asc"
    if normalized_sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be one of: asc, desc")

    rows_list = list(rows or [])

    def _cmp_values(left, right):
        if left < right:
            return -1
        if left > right:
            return 1
        return 0

    def _compare_rows(left_row, right_row):
        left_value = _column_sort_value(
            left_row,
            normalized_sort_by,
            column_types=column_types,
        )
        right_value = _column_sort_value(
            right_row,
            normalized_sort_by,
            column_types=column_types,
        )

        if left_value is None and right_value is None:
            return 0
        if left_value is None:
            return 1
        if right_value is None:
            return -1

        cmp_value = _cmp_values(left_value, right_value)
        if normalized_sort_order == "desc":
            cmp_value = -cmp_value
        return cmp_value

    return sorted(rows_list, key=cmp_to_key(_compare_rows))


def paginate_overview_table_rows(rows, *, limit=None, offset=0):
    rows_list = list(rows or [])
    try:
        offset_value = int(offset or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("offset must be an integer >= 0") from exc
    if offset_value < 0:
        raise ValueError("offset must be an integer >= 0")

    if limit in (None, ""):
        return rows_list[offset_value:], None, offset_value

    try:
        limit_value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be null or an integer >= 1") from exc
    if limit_value <= 0:
        raise ValueError("limit must be null or an integer >= 1")
    return rows_list[offset_value: offset_value + limit_value], limit_value, offset_value


def query_overview_table(
    records,
    *,
    meta=None,
    keyword="",
    box=None,
    color_value=None,
    include_inactive=False,
    column_filters=None,
    sort_by="location",
    sort_order="asc",
    limit=None,
    offset=0,
):
    """Execute one shared Overview-table query and return display payload."""
    projection = build_overview_table_projection(records or [], meta=meta or {})
    columns = list(projection.get("columns") or [])

    normalized_sort_by = str(sort_by or "location").strip() or "location"
    if normalized_sort_by not in {str(column) for column in columns}:
        raise ValueError(
            "sort_by must be one of: " + ", ".join(str(column) for column in columns)
        )

    normalized_column_filters = normalize_overview_table_column_filters(
        columns,
        column_filters,
    )
    filtered_rows, matched_boxes = filter_overview_table_rows(
        projection.get("rows") or [],
        keyword=keyword,
        box=box,
        color_value=color_value,
        include_inactive=include_inactive,
        column_filters=normalized_column_filters,
    )
    column_types = overview_table_column_types(
        columns,
        meta=meta or {},
        rows=filtered_rows,
    )
    sorted_rows = sort_overview_table_rows(
        filtered_rows,
        sort_by=normalized_sort_by,
        sort_order=sort_order,
        column_types=column_types,
    )
    paged_rows, normalized_limit, normalized_offset = paginate_overview_table_rows(
        sorted_rows,
        limit=limit,
        offset=offset,
    )

    display_rows = []
    for row_data in paged_rows:
        display_rows.append(
            {
                "row_kind": row_data.get("row_kind"),
                "record_id": row_data.get("record_id"),
                "box": row_data.get("box"),
                "position": row_data.get("position"),
                "active": bool(row_data.get("active")),
                "color_value": row_data.get("color_value"),
                "values": dict(row_data.get("values") or {}),
            }
        )

    total_count = len(sorted_rows)
    display_count = len(display_rows)
    has_more = normalized_limit is not None and (normalized_offset + display_count) < total_count

    return {
        "columns": columns,
        "column_types": column_types,
        "rows": display_rows,
        "color_key": projection.get("color_key"),
        "total_count": total_count,
        "display_count": display_count,
        "matched_boxes": matched_boxes,
        "limit": normalized_limit,
        "offset": normalized_offset,
        "has_more": has_more,
        "applied_filters": {
            "keyword": _normalize_text(keyword),
            "box": box,
            "color_value": None if color_value in (None, "") else str(color_value),
            "include_inactive": bool(include_inactive),
            "column_filters": normalized_column_filters,
            "sort_by": normalized_sort_by,
            "sort_order": str(sort_order or "asc").strip().lower() or "asc",
            "sort_nulls": "last",
        },
    }
