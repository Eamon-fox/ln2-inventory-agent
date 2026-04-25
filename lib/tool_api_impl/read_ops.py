"""Extracted read/query operation implementations for Tool API."""

import os
from collections import defaultdict
from datetime import datetime, timedelta
from functools import cmp_to_key

from ..inventory_query_contracts import SEARCH_MODE_VALUES
from ..csv_export import export_inventory_to_csv
from ..custom_fields import get_color_key, unsupported_box_fields_issue
from ..position_fmt import (
    display_to_box,
    get_box_numbers,
    get_position_range,
    get_total_slots,
)
from ..schema_aliases import (
    DEFAULT_RECORD_SORT_FIELD,
    VALID_RECORD_SORT_FIELDS,
    get_stored_at,
    normalize_record_sort_field,
)
from ..takeout_parser import extract_events, normalize_action
from ..overview_table_query import query_overview_table
from ..validators import normalize_date_arg, parse_date, validate_box, validate_position
from ..yaml_ops import (
    coerce_audit_seq,
    compute_occupancy,
    iter_audit_events_reverse,
    load_yaml,
)
from .. import tool_api_support as api

INVENTORY_PREVIEW_LIMIT = 100


def _load_supported_data(yaml_path):
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return None, {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

    issue = unsupported_box_fields_issue((data or {}).get("meta"))
    if issue:
        return None, {
            "ok": False,
            "error_code": issue.get("error_code", "unsupported_box_fields"),
            "message": issue.get("message", "Unsupported dataset model."),
            "details": issue.get("details"),
        }

    return data, None


def tool_export_inventory_csv(yaml_path, output_path):
    """Export full inventory records to a CSV file."""
    if not output_path:
        return {
            "ok": False,
            "error_code": "invalid_output_path",
            "message": "CSV output path is required",
        }

    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    try:
        result = export_inventory_to_csv(data, output_path=output_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "export_failed",
            "message": f"CSV export failed: {exc}",
        }

    return {
        "ok": True,
        "result": result,
    }


def tool_list_empty_positions(yaml_path, box=None):
    """List empty positions by box."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    layout = api._get_layout(data)
    total_slots = get_total_slots(layout)
    box_numbers = get_box_numbers(layout)
    all_positions = set(range(1, total_slots + 1))
    occupancy = compute_occupancy(records)

    if box is not None:
        if not validate_box(box, layout):
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }
        boxes = [str(box)]
    else:
        boxes = [str(i) for i in box_numbers]

    items = []
    for box_key in boxes:
        used = set(occupancy.get(box_key, []))
        empty = sorted(all_positions - used)
        items.append(
            {
                "box": box_key,
                "total_slots": total_slots,
                "empty_count": len(empty),
                "empty_positions": empty,
            }
        )

    return {
        "ok": True,
        "result": {
            "boxes": items,
            "total_slots": total_slots,
        },
    }


def tool_search_records(
    yaml_path,
    query=None,
    mode="fuzzy",
    max_results=None,
    case_sensitive=False,
    box=None,
    position=None,
    record_id=None,
    status="all",
    sort_by=None,
    sort_order="desc",
):
    """Search records by text and/or structured filters."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    layout = api._get_layout(data)

    if mode not in SEARCH_MODE_VALUES:
        return {
            "ok": False,
            "error_code": "invalid_mode",
            "message": "mode must be " + "/".join(SEARCH_MODE_VALUES),
        }

    normalized_record_id = None
    if record_id not in (None, ""):
        try:
            normalized_record_id = int(record_id)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_code": "invalid_record_id",
                "message": f"record_id must be an integer: {record_id}",
            }

    normalized_box = None
    if box not in (None, ""):
        try:
            normalized_box = int(display_to_box(box, layout))
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": f"box must be a valid value: {box}",
            }
        if not validate_box(normalized_box, layout):
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }

    normalized_position = None
    if position not in (None, ""):
        try:
            normalized_position = int(api.coerce_position_value(position, layout=layout, field_name="position"))
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_position",
                "message": f"position must be a valid value: {position}",
            }
        if not validate_position(normalized_position, layout):
            pos_lo, pos_hi = get_position_range(layout)
            return {
                "ok": False,
                "error_code": "invalid_position",
                "message": f"position must be between {pos_lo}-{pos_hi}",
            }

    normalized_status = "all"
    if status not in (None, ""):
        status_value = str(status).strip().lower()
        if status_value not in {"all", "active", "inactive"}:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": "status must be one of: all, active, inactive",
            }
        normalized_status = status_value

    normalized_sort_by = normalize_record_sort_field(sort_by, default=DEFAULT_RECORD_SORT_FIELD)
    if normalized_sort_by not in VALID_RECORD_SORT_FIELDS:
        return {
            "ok": False,
            "error_code": "invalid_tool_input",
            "message": "sort_by must be one of: box, position, stored_at, id",
        }

    normalized_sort_order = "desc"
    if sort_order not in (None, ""):
        sort_order_value = str(sort_order).strip().lower()
        if sort_order_value not in {"asc", "desc"}:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": "sort_order must be one of: asc, desc",
            }
        normalized_sort_order = sort_order_value

    raw_query = " ".join(str(query or "").split())
    if raw_query == "*":
        raw_query = ""
    query_shortcut = None
    if raw_query and normalized_box is None and normalized_position is None:
        parsed = api.parse_search_location_shortcut(raw_query, layout)
        if parsed is not None:
            normalized_box, normalized_position = parsed
            query_shortcut = raw_query
            raw_query = ""

    normalized_query = api.normalize_search_text(raw_query, case_sensitive=case_sensitive)
    keywords = normalized_query.split() if normalized_query else []
    q = normalized_query

    scoped_records = []
    for rec in records:
        if normalized_record_id is not None:
            try:
                if int(rec.get("id")) != normalized_record_id:
                    continue
            except (TypeError, ValueError):
                continue

        if normalized_box is not None:
            try:
                if int(rec.get("box")) != normalized_box:
                    continue
            except (TypeError, ValueError):
                continue

        if normalized_position is not None:
            rec_position = rec.get("position")
            if rec_position is None:
                continue
            try:
                if int(rec_position) != normalized_position:
                    continue
            except (TypeError, ValueError):
                continue

        if normalized_status == "active" and rec.get("position") is None:
            continue
        if normalized_status == "inactive" and rec.get("position") is not None:
            continue

        scoped_records.append(rec)

    has_structured_filter = any(
        value is not None
        for value in (
            normalized_record_id,
            normalized_box,
            normalized_position,
        )
    )
    if normalized_status != "all":
        has_structured_filter = True

    matches = []
    if q:
        for rec in scoped_records:
            if mode == "fuzzy":
                blob = api.record_search_blob(rec, case_sensitive=case_sensitive)
                if q in blob:
                    matches.append(rec)
                continue

            if mode == "exact":
                search_values = api.record_search_values(rec, case_sensitive=case_sensitive)
                if q in search_values:
                    matches.append(rec)
                continue

            record_tokens = api.record_search_tokens(rec, case_sensitive=case_sensitive)
            if keywords and all(kw in record_tokens for kw in keywords):
                matches.append(rec)
    elif has_structured_filter or not normalized_query:
        matches = list(scoped_records)

    def _coerce_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _record_id_value(record):
        return _coerce_int(record.get("id"))

    def _sort_field_value(record):
        if normalized_sort_by == "id":
            return _record_id_value(record)
        if normalized_sort_by == "box":
            return _coerce_int(record.get("box"))
        if normalized_sort_by == "position":
            return _coerce_int(record.get("position"))
        return parse_date(get_stored_at(record))

    def _cmp_values(left, right):
        if left < right:
            return -1
        if left > right:
            return 1
        return 0

    def _compare_record_ids(left_record, right_record):
        left_id = _record_id_value(left_record)
        right_id = _record_id_value(right_record)
        if left_id is None and right_id is None:
            return 0
        if left_id is None:
            return 1
        if right_id is None:
            return -1
        cmp_id = _cmp_values(left_id, right_id)
        if normalized_sort_order == "desc":
            cmp_id = -cmp_id
        return cmp_id

    def _compare_records(left_record, right_record):
        left_value = _sort_field_value(left_record)
        right_value = _sort_field_value(right_record)
        if left_value is None and right_value is None:
            return _compare_record_ids(left_record, right_record)
        if left_value is None:
            return 1
        if right_value is None:
            return -1
        cmp_primary = _cmp_values(left_value, right_value)
        if normalized_sort_order == "desc":
            cmp_primary = -cmp_primary
        if cmp_primary != 0:
            return cmp_primary
        return _compare_record_ids(left_record, right_record)

    matches = sorted(matches, key=cmp_to_key(_compare_records))

    total_count = len(matches)
    display_matches = matches[:max_results] if (max_results and max_results > 0) else matches

    suggestions = []
    if total_count == 0:
        if normalized_box is not None and normalized_position is not None:
            suggestions.append("No matching records at the specified slot; try another box/position")
        elif has_structured_filter:
            suggestions.append("Check structured filters (record_id/box/position/status)")
        else:
            suggestions.extend(
                [
                    "Try shorter keywords, e.g. 'reporter' or '36'",
                    "Check for spelling mistakes",
                    "Try tokenized search with keywords mode",
                ]
            )
    elif total_count > 50:
        suggestions.extend(["Too many matches; add more keywords to narrow results"])

    slot_lookup = None
    if normalized_box is not None and normalized_position is not None:
        slot_matches = []
        for rec in records:
            try:
                rec_box = int(rec.get("box"))
                rec_pos_raw = rec.get("position")
                if rec_pos_raw is None:
                    continue
                rec_pos = int(rec_pos_raw)
            except (TypeError, ValueError):
                continue

            if rec_box == normalized_box and rec_pos == normalized_position:
                slot_matches.append(rec)

        status = "empty"
        if len(slot_matches) == 1:
            status = "occupied"
        elif len(slot_matches) > 1:
            status = "conflict"

        slot_record_ids = []
        for rec in slot_matches:
            raw_id = rec.get("id")
            if raw_id is None:
                continue
            try:
                slot_record_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        slot_lookup = {
            "box": normalized_box,
            "position": normalized_position,
            "status": status,
            "record_count": len(slot_matches),
            "record_ids": slot_record_ids,
        }

    result = {
        "query": query,
        "normalized_query": normalized_query,
        "keywords": keywords,
        "mode": mode,
        "records": display_matches,
        "total_count": total_count,
        "display_count": len(display_matches),
        "suggestions": suggestions,
        "applied_filters": {
            "record_id": normalized_record_id,
            "box": normalized_box,
            "position": normalized_position,
            "status": normalized_status,
            "sort_by": normalized_sort_by,
            "sort_order": normalized_sort_order,
            "sort_nulls": "last",
            "query_shortcut": query_shortcut,
        },
    }
    if slot_lookup is not None:
        result["slot_lookup"] = slot_lookup

    return {
        "ok": True,
        "result": result,
    }


def tool_filter_records(
    yaml_path,
    keyword=None,
    box=None,
    color_value=None,
    include_inactive=False,
    column_filters=None,
    sort_by=None,
    sort_order="asc",
    limit=None,
    offset=0,
):
    """Filter inventory records using Overview table semantics."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    meta = (data or {}).get("meta", {})
    layout = api._get_layout(data)

    normalized_box = None
    if box not in (None, ""):
        try:
            normalized_box = int(display_to_box(box, layout))
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": f"box must be a valid value: {box}",
            }
        if not validate_box(normalized_box, layout):
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }

    include_inactive_flag = include_inactive
    if not isinstance(include_inactive_flag, bool):
        normalized_flag = str(include_inactive_flag or "").strip().lower()
        if normalized_flag in {"1", "true", "yes", "y", "on"}:
            include_inactive_flag = True
        elif normalized_flag in {"", "0", "false", "no", "n", "off"}:
            include_inactive_flag = False
        else:
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": "include_inactive must be a boolean",
            }

    try:
        result = query_overview_table(
            records,
            meta=meta,
            keyword=keyword,
            box=normalized_box,
            color_value=color_value,
            include_inactive=include_inactive_flag,
            column_filters=column_filters,
            sort_by=sort_by or "location",
            sort_order=sort_order or "asc",
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        return {
            "ok": False,
            "error_code": "invalid_tool_input",
            "message": str(exc),
        }

    if not result.get("rows"):
        result["suggestions"] = [
            "Try fewer filters or clear one column filter",
            "Check keyword spelling and current box/color filters",
            "Set include_inactive=true if the record may have been taken out",
        ]

    return {
        "ok": True,
        "result": result,
    }


def tool_recent_stored(yaml_path, days=None, count=None):
    """Query recently stored records sorted by date desc."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    valid = []
    for rec in records:
        stored_at = get_stored_at(rec)
        if not stored_at:
            continue
        dt = parse_date(stored_at)
        if not dt:
            continue
        valid.append((dt, rec))

    valid.sort(key=lambda x: x[0], reverse=True)
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        selected = [rec for dt, rec in valid if dt >= cutoff]
    elif count is not None:
        selected = [rec for _, rec in valid[:count]]
    else:
        selected = [rec for _, rec in valid[:10]]

    return {
        "ok": True,
        "result": {
            "records": selected,
            "count": len(selected),
            "days": days,
            "limit": count,
        },
    }


def tool_recent_frozen(yaml_path, days=None, count=None):
    """Deprecated alias for tool_recent_stored."""
    return tool_recent_stored(yaml_path, days=days, count=count)


def tool_query_takeout_events(
    yaml_path,
    date=None,
    days=None,
    start_date=None,
    end_date=None,
    action=None,
    max_records=0,
):
    """Query takeout/move events by date mode and action."""
    action_filter = normalize_action(action) if action else None
    if action and not action_filter:
        return {
            "ok": False,
            "error_code": "invalid_action",
            "message": "Action must be takeout/move",
        }

    if days:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)
        mode = "days"
        target_dates = None
        date_range = (start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    elif start_date and end_date:
        start = normalize_date_arg(start_date)
        end = normalize_date_arg(end_date)
        if not start or not end:
            return {
                "ok": False,
                "error_code": "invalid_date",
                "message": "Invalid date format, please use YYYY-MM-DD",
            }
        mode = "range"
        target_dates = None
        date_range = (start, end)
    elif date is not None:
        target = normalize_date_arg(date)
        if not target:
            return {
                "ok": False,
                "error_code": "invalid_date",
                "message": "Invalid date format, please use YYYY-MM-DD",
            }
        mode = "single"
        target_dates = [target]
        date_range = None
    else:
        # No date specified - return all events
        mode = "all"
        target_dates = None
        date_range = None

    range_start, range_end = date_range if date_range else (None, None)

    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    matched = []
    total_events = 0
    for rec in records:
        events = extract_events(rec)
        if not events:
            continue

        if mode == "all":
            # Return all events with optional action filter
            filtered = [
                ev
                for ev in events
                if ev.get("date") and (not action_filter or ev.get("action") == action_filter)
            ]
        elif mode == "single":
            filtered = [
                ev
                for ev in events
                if ev.get("date") in target_dates and (not action_filter or ev.get("action") == action_filter)
            ]
        else:  # mode == "range" or "days"
            filtered = [
                ev
                for ev in events
                if ev.get("date")
                and range_start <= ev.get("date") <= range_end
                and (not action_filter or ev.get("action") == action_filter)
            ]

        if filtered:
            matched.append({"record": rec, "events": filtered})
            total_events += len(filtered)

    total_record_count = len(matched)

    # Apply max_records to limit number of events (not records)
    if max_records and max_records > 0:
        # Collect all events and limit by max_records
        all_events = []
        for m in matched:
            events_for_record = m["events"][:max_records]
            remaining = max_records - len(events_for_record)
            if remaining > 0:
                max_records = remaining
                all_events.append({"record": m["record"], "events": events_for_record})
            else:
                if events_for_record:
                    all_events.append({"record": m["record"], "events": events_for_record})
                break
        records_to_return = all_events
    else:
        records_to_return = matched

    # Recalculate event_count based on filtered records
    final_event_count = sum(len(m["events"]) for m in records_to_return)

    return {
        "ok": True,
        "result": {
            "mode": mode,
            "target_dates": target_dates,
            "date_range": date_range,
            "action_filter": action_filter,
            "records": records_to_return,
            "record_count": total_record_count,
            "display_count": len(records_to_return),
            "event_count": final_event_count,
        },
    }


def tool_collect_timeline(yaml_path, days=30, all_history=False):
    """Collect timeline events and summary stats."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    records = data.get("inventory", [])
    timeline = api._collect_timeline_events(records, days=None if all_history else days)

    total_frozen = 0
    total_takeout = 0
    total_move = 0
    active_days = 0
    for _, events in timeline.items():
        frozen = len(events["frozen"])
        takeout = len(events["takeout"])
        move = len(events["move"])
        total_frozen += frozen
        total_takeout += takeout
        total_move += move
        if frozen + takeout + move > 0:
            active_days += 1

    return {
        "ok": True,
        "result": {
            "timeline": dict(timeline),
            "sorted_dates": sorted(timeline.keys(), reverse=True),
            "summary": {
                "active_days": active_days,
                "total_ops": total_frozen + total_takeout + total_move,
                "frozen": total_frozen,
                "takeout": total_takeout,
                "move": total_move,
            },
        },
    }


def _normalize_timeline_filter_date(name, value):
    text = str(value or "").strip()
    if not text:
        return None, None
    if parse_date(text) is None:
        return None, {
            "ok": False,
            "error_code": "invalid_date",
            "message": f"{name} must be YYYY-MM-DD",
        }
    return text, None


def _normalize_audit_timeline_row(row):
    if not isinstance(row, dict):
        return None, None
    normalized = dict(row or {})
    if not str(normalized.get("status") or "").strip():
        normalized["status"] = "success"
    seq = coerce_audit_seq(normalized.get("audit_seq"))
    if seq is not None:
        normalized["audit_seq"] = seq
    return normalized, seq


def _audit_timeline_row_matches(row, *, action_norm="", status_norm="", start_norm=None, end_norm=None):
    ts_date = str(row.get("timestamp") or "")[:10]
    if start_norm and (not ts_date or ts_date < start_norm):
        return False
    if end_norm and (not ts_date or ts_date > end_norm):
        return False
    if action_norm and str(row.get("action") or "") != action_norm:
        return False
    if status_norm and str(row.get("status") or "") != status_norm:
        return False
    return True


def tool_list_audit_timeline(
    yaml_path,
    limit=50,
    offset=0,
    action_filter=None,
    status_filter=None,
    start_date=None,
    end_date=None,
):
    """List audit timeline rows from persisted audit events only (audit_seq desc)."""
    limit_val = None
    if limit == "":
        limit = 50
    if limit is not None:
        try:
            limit_val = int(limit)
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_limit",
                "message": "limit must be null or an integer >= 1",
            }
        if limit_val <= 0:
            return {
                "ok": False,
                "error_code": "invalid_limit",
                "message": "limit must be null or an integer >= 1",
            }

    try:
        offset_val = 0 if offset in (None, "") else int(offset)
    except Exception:
        return {
            "ok": False,
            "error_code": "invalid_offset",
            "message": "offset must be an integer >= 0",
        }
    if offset_val < 0:
        return {
            "ok": False,
            "error_code": "invalid_offset",
            "message": "offset must be an integer >= 0",
        }

    start_norm, start_error = _normalize_timeline_filter_date("start_date", start_date)
    if start_error:
        return start_error
    end_norm, end_error = _normalize_timeline_filter_date("end_date", end_date)
    if end_error:
        return end_error
    if start_norm and end_norm and start_norm > end_norm:
        return {
            "ok": False,
            "error_code": "invalid_date_range",
            "message": "start_date must be <= end_date",
        }

    action_norm = str(action_filter or "").strip()
    if action_norm.lower() == "all":
        action_norm = ""
    status_norm = str(status_filter or "").strip()
    if status_norm.lower() == "all":
        status_norm = ""

    yaml_abs = os.path.abspath(str(yaml_path or ""))
    has_filter = bool(action_norm or status_norm or start_norm or end_norm)
    try:
        if not has_filter and limit_val is not None:
            items = []
            seen = 0
            latest_seq = None
            target_count = offset_val + limit_val
            exhausted = True
            for raw_row in iter_audit_events_reverse(yaml_abs):
                normalized, seq = _normalize_audit_timeline_row(raw_row)
                if normalized is None:
                    continue
                if latest_seq is None and seq is not None:
                    latest_seq = seq
                if seen >= offset_val and len(items) < limit_val:
                    items.append(normalized)
                seen += 1
                if seen >= target_count and latest_seq is not None:
                    exhausted = False
                    break

            total = seen if exhausted else max(int(latest_seq or 0), seen)
            return {
                "ok": True,
                "result": {
                    "items": items,
                    "total": total,
                    "limit": limit_val,
                    "offset": offset_val,
                },
            }

        filtered = []
        previous_seq = None
        needs_sort = False
        for raw_row in iter_audit_events_reverse(yaml_abs):
            normalized, seq = _normalize_audit_timeline_row(raw_row)
            if normalized is None:
                continue
            if seq is not None and previous_seq is not None and seq > previous_seq:
                needs_sort = True
            if seq is not None:
                previous_seq = seq
            if _audit_timeline_row_matches(
                normalized,
                action_norm=action_norm,
                status_norm=status_norm,
                start_norm=start_norm,
                end_norm=end_norm,
            ):
                filtered.append(normalized)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load audit timeline: {exc}",
        }

    if needs_sort:
        filtered.sort(key=lambda ev: int(coerce_audit_seq(ev.get("audit_seq")) or 0), reverse=True)
    total = len(filtered)
    if limit_val is None:
        items = filtered[offset_val:]
    else:
        items = filtered[offset_val: offset_val + limit_val]
    return {
        "ok": True,
        "result": {
            "items": items,
            "total": total,
            "limit": limit_val,
            "offset": offset_val,
        },
    }


def tool_recommend_positions(yaml_path, count, box_preference=None, strategy="consecutive"):
    """Recommend positions for new samples."""
    if count <= 0:
        return {
            "ok": False,
            "error_code": "invalid_count",
            "message": "count must be greater than 0",
        }

    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    layout = api._get_layout(data)
    total_slots = get_total_slots(layout)
    box_numbers = get_box_numbers(layout)
    all_positions = set(range(1, total_slots + 1))
    occupancy = compute_occupancy(data.get("inventory", []))

    if box_preference:
        if not validate_box(box_preference, layout):
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }
        boxes_to_check = [str(box_preference)]
    else:
        boxes_to_check = []
        for box_num in box_numbers:
            key = str(box_num)
            boxes_to_check.append((key, len(occupancy.get(key, []))))
        boxes_to_check = [b for b, _ in sorted(boxes_to_check, key=lambda x: x[1])]

    recommendations = []
    for box_key in boxes_to_check:
        occupied = set(occupancy.get(box_key, []))
        empty = sorted(all_positions - occupied)
        if len(empty) < count:
            continue

        box_recs = []
        if strategy in {"consecutive", "any"}:
            for group in api._find_consecutive_slots(empty, count)[:3]:
                box_recs.append({"box": int(box_key), "positions": group, "reason": "consecutive positions", "score": 100})

        if strategy == "same_row":
            for group in api._find_same_row_slots(empty, count, layout)[:3]:
                box_recs.append({"box": int(box_key), "positions": group, "reason": "same_row", "score": 90})

        if not box_recs:
            box_recs.append({"box": int(box_key), "positions": empty[:count], "reason": "first_available", "score": 50})

        recommendations.extend(box_recs)
        if len(recommendations) >= 5:
            break

    return {
        "ok": True,
        "result": {
            "count": count,
            "strategy": strategy,
            "recommendations": recommendations[:5],
        },
    }


def tool_generate_stats(
    yaml_path,
    box=None,
    include_inactive=False,
    full_records_for_gui=False,
):
    """Generate inventory statistics.

    - Global mode (box omitted): returns full-inventory stats.
    - Box mode (box provided): returns only that box's stats/records.
    """
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    all_records = data.get("inventory", [])
    def _parse_bool_flag(value, *, field_name):
        if isinstance(value, bool):
            return True, value
        if value in (None, ""):
            return True, False
        if isinstance(value, (int, float)):
            return True, bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True, True
        if normalized in {"0", "false", "no", "n", "off"}:
            return True, False
        return False, {
            "ok": False,
            "error_code": "invalid_tool_input",
            "message": f"{field_name} must be a boolean",
        }

    include_ok, include_parsed = _parse_bool_flag(
        include_inactive,
        field_name="include_inactive",
    )
    if not include_ok:
        return include_parsed
    include_inactive_flag = bool(include_parsed)

    gui_full_ok, gui_full_parsed = _parse_bool_flag(
        full_records_for_gui,
        field_name="full_records_for_gui",
    )
    if not gui_full_ok:
        return gui_full_parsed
    full_records_for_gui_flag = bool(gui_full_parsed)
    records = list(all_records) if include_inactive_flag else [rec for rec in all_records if rec.get("position") is not None]
    layout = api._get_layout(data)
    target_box = None
    if box not in (None, ""):
        try:
            target_box = int(display_to_box(box, layout))
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }
        if not validate_box(target_box, layout):
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": "Validation failed",
            }

    def _record_sort_key(record):
        pos_raw = record.get("position")
        rid_raw = record.get("id")
        try:
            position_value = int(pos_raw)
        except (TypeError, ValueError):
            position_value = 10**9
        try:
            rid_value = int(rid_raw)
        except (TypeError, ValueError):
            rid_value = 10**9
        return position_value, rid_value

    def _apply_preview_payload(result, scoped_records):
        if full_records_for_gui_flag:
            result["inventory_preview"] = scoped_records
            result["inventory_omitted"] = False
            result["inventory_limit"] = INVENTORY_PREVIEW_LIMIT
        elif len(scoped_records) <= INVENTORY_PREVIEW_LIMIT:
            result["inventory_preview"] = scoped_records
            result["inventory_omitted"] = False
            result["inventory_limit"] = INVENTORY_PREVIEW_LIMIT
        else:
            result["inventory_omitted"] = True
            result["inventory_omitted_reason"] = "record_count_exceeds_limit"
            result["inventory_limit"] = INVENTORY_PREVIEW_LIMIT
            result["next_actions"] = [
                "Call generate_stats with box=<box_id> to inspect one box.",
                "Use search_records with a non-empty query and structured filters for targeted lookup.",
            ]

    if target_box is not None:
        box_records = []
        for rec in records:
            try:
                rec_box = int(rec.get("box"))
            except (TypeError, ValueError):
                continue
            if rec_box != target_box:
                continue
            box_records.append(rec)
        box_records.sort(key=_record_sort_key)

        per_box_slots = get_total_slots(layout)
        occupancy = compute_occupancy(all_records)
        box_key = str(target_box)
        box_occupied = len(occupancy.get(box_key, []))
        box_empty = per_box_slots - box_occupied
        box_rate = (box_occupied / per_box_slots * 100) if per_box_slots > 0 else 0

        color_key = get_color_key((data or {}).get("meta"))
        value_counts = defaultdict(int)
        for rec in box_records:
            value_counts[rec.get(color_key, "Unknown")] += 1

        stats_result = {
            "data": {"meta": (data or {}).get("meta", {})},
            "meta": (data or {}).get("meta", {}),
            "layout": layout,
            "box": target_box,
            "box_total_slots": per_box_slots,
            "box_occupied": box_occupied,
            "box_empty": box_empty,
            "box_occupancy_rate": box_rate,
            "box_record_count": len(box_records),
            "box_records": box_records,
            "cell_lines": dict(sorted(value_counts.items(), key=lambda x: x[1], reverse=True)),
            "field_value_counts": {"key": color_key, "counts": dict(sorted(value_counts.items(), key=lambda x: x[1], reverse=True))},
            "record_count": len(box_records),
            "include_inactive": include_inactive_flag,
            "full_records_for_gui": full_records_for_gui_flag,
        }
        _apply_preview_payload(stats_result, box_records)
        return {
            "ok": True,
            "result": stats_result,
        }

    total_slots = get_total_slots(layout)
    occupancy = compute_occupancy(all_records)
    box_numbers = get_box_numbers(layout)
    total_boxes = len(box_numbers)

    total_occupied = sum(len(positions) for positions in occupancy.values())
    total_capacity = total_boxes * total_slots
    overall_rate = (total_occupied / total_capacity * 100) if total_capacity > 0 else 0

    box_stats = {}
    for box_num in box_numbers:
        key = str(box_num)
        occupied_count = len(occupancy.get(key, []))
        rate = (occupied_count / total_slots * 100) if total_slots > 0 else 0
        box_stats[key] = {
            "occupied": occupied_count,
            "empty": total_slots - occupied_count,
            "total": total_slots,
            "rate": rate,
        }

    color_key = get_color_key((data or {}).get("meta"))
    value_counts = defaultdict(int)
    for rec in records:
        value_counts[rec.get(color_key, "Unknown")] += 1
    sorted_value_counts = dict(sorted(value_counts.items(), key=lambda x: x[1], reverse=True))

    # Flatten the stats structure for easier access, but keep nested structure for backward compatibility
    stats_nested = {
        "overall": {
            "total_occupied": total_occupied,
            "total_empty": total_capacity - total_occupied,
            "total_capacity": total_capacity,
            "occupancy_rate": overall_rate,
        },
        "boxes": box_stats,
        "cell_lines": sorted_value_counts,
    }

    stats_result = {
        # Keep `data` key for compatibility, but do not expose full inventory here.
        "data": {"meta": (data or {}).get("meta", {})},
        "meta": (data or {}).get("meta", {}),
        "layout": layout,
        "occupancy": occupancy,
        "stats": stats_nested,
        # Also provide flattened structure for easier access
        "total_slots": total_capacity,  # Total slots across all boxes
        "slots_per_box": total_slots,  # Slots per single box
        "total_occupied": total_occupied,
        "total_empty": total_capacity - total_occupied,
        "total_capacity": total_capacity,
        "occupancy_rate": overall_rate,
        "boxes": box_stats,
        "cell_lines": sorted_value_counts,
        "field_value_counts": {"key": color_key, "counts": sorted_value_counts},
        "record_count": len(records),
        "include_inactive": include_inactive_flag,
        "full_records_for_gui": full_records_for_gui_flag,
    }
    _apply_preview_payload(stats_result, records)

    return {
        "ok": True,
        "result": stats_result,
    }


def tool_get_raw_entries(yaml_path, ids):
    """Return raw YAML entries for selected IDs."""
    data, failure = _load_supported_data(yaml_path)
    if failure:
        return failure

    inventory = data.get("inventory", [])
    id_set = set(ids)
    found = []
    found_ids = set()
    for entry in inventory:
        entry_id = entry.get("id")
        if entry_id in id_set:
            found.append(entry)
            found_ids.add(entry_id)
    found.sort(key=lambda x: x.get("id", 0))
    missing = sorted(id_set - found_ids)

    if not found:
        return {
            "ok": False,
            "error_code": "not_found",
            "message": f"IDs not found: {', '.join(map(str, ids))}",
            "missing_ids": missing,
            "entries": [],
        }

    return {
        "ok": True,
        "result": {
            "entries": found,
            "missing_ids": missing,
            "requested_ids": list(ids),
        },
    }
