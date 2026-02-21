"""Extracted read/query operation implementations for Tool API."""

from collections import defaultdict
from datetime import datetime, timedelta

from ..csv_export import export_inventory_to_csv
from ..position_fmt import (
    display_to_box,
    display_to_pos,
    get_box_numbers,
    get_position_range,
    get_total_slots,
)
from ..takeout_parser import extract_events, normalize_action
from ..validators import normalize_date_arg, parse_date, validate_box, validate_position
from ..yaml_ops import compute_occupancy, load_yaml


class _ApiProxy:
    def __getattr__(self, name):
        from .. import tool_api as _api_mod

        return getattr(_api_mod, name)


api = _ApiProxy()


def tool_export_inventory_csv(yaml_path, output_path):
    """Export full inventory records to a CSV file."""
    if not output_path:
        return {
            "ok": False,
            "error_code": "invalid_output_path",
            "message": "CSV output path is required",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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
    active_only=None,
):
    """Search records by text and/or structured filters."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

    records = data.get("inventory", [])
    layout = api._get_layout(data)

    if mode not in {"fuzzy", "exact", "keywords"}:
        return {
            "ok": False,
            "error_code": "invalid_mode",
            "message": "mode must be fuzzy/exact/keywords",
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
            normalized_position = int(display_to_pos(position, layout))
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

    normalized_active_only = None
    if active_only not in (None, ""):
        if isinstance(active_only, bool):
            normalized_active_only = active_only
        elif isinstance(active_only, (int, float)):
            normalized_active_only = bool(active_only)
        else:
            flag = str(active_only).strip().lower()
            if flag in {"1", "true", "yes", "y", "on"}:
                normalized_active_only = True
            elif flag in {"0", "false", "no", "n", "off"}:
                normalized_active_only = False
            else:
                return {
                    "ok": False,
                    "error_code": "invalid_tool_input",
                    "message": "Validation failed",
                }

    normalized_query = " ".join(str(query or "").split())
    query_shortcut = None
    if normalized_query and normalized_box is None and normalized_position is None:
        parsed = api._parse_search_location_shortcut(normalized_query, layout)
        if parsed is not None:
            normalized_box, normalized_position = parsed
            query_shortcut = normalized_query
            normalized_query = ""

    keywords = normalized_query.split() if normalized_query else []
    q = normalized_query if case_sensitive else normalized_query.lower()

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

        if normalized_active_only is True and rec.get("position") is None:
            continue
        if normalized_active_only is False and rec.get("position") is not None:
            continue

        scoped_records.append(rec)

    has_structured_filter = any(
        value is not None
        for value in (
            normalized_record_id,
            normalized_box,
            normalized_position,
            normalized_active_only,
        )
    )

    matches = []
    if q:
        for rec in scoped_records:
            blob = api._record_search_blob(rec, case_sensitive=case_sensitive)
            if mode in {"fuzzy", "exact"}:
                if q in blob:
                    matches.append(rec)
                continue

            # keywords (AND)
            ok = True
            for kw in keywords:
                kw_cmp = kw if case_sensitive else kw.lower()
                if kw_cmp not in blob:
                    ok = False
                    break
            if ok and keywords:
                matches.append(rec)
    elif has_structured_filter:
        matches = list(scoped_records)

    total_count = len(matches)
    display_matches = matches[:max_results] if (max_results and max_results > 0) else matches

    suggestions = []
    if total_count == 0:
        if normalized_box is not None and normalized_position is not None:
            suggestions.append("No matching records at the specified slot; try another box/position")
        elif has_structured_filter:
            suggestions.append("Check structured filters (record_id/box/position/active_only)")
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
            "active_only": normalized_active_only,
            "query_shortcut": query_shortcut,
        },
    }
    if slot_lookup is not None:
        result["slot_lookup"] = slot_lookup

    return {
        "ok": True,
        "result": result,
    }


def tool_recent_frozen(yaml_path, days=None, count=None):
    """Query recently frozen records sorted by date desc."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

    records = data.get("inventory", [])
    valid = []
    for rec in records:
        frozen_at = rec.get("frozen_at")
        if not frozen_at:
            continue
        dt = parse_date(frozen_at)
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

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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


def tool_recommend_positions(yaml_path, count, box_preference=None, strategy="consecutive"):
    """Recommend positions for new samples."""
    if count <= 0:
        return {
            "ok": False,
            "error_code": "invalid_count",
            "message": "count must be greater than 0",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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


def tool_generate_stats(yaml_path):
    """Generate inventory statistics and occupancy maps."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

    records = data.get("inventory", [])
    layout = api._get_layout(data)
    total_slots = get_total_slots(layout)
    occupancy = compute_occupancy(records)
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

    cell_lines = defaultdict(int)
    for rec in records:
        if rec.get("position") is not None:
            cell_lines[rec.get("cell_line", "Unknown")] += 1

    # Flatten the stats structure for easier access, but keep nested structure for backward compatibility
    stats_nested = {
        "overall": {
            "total_occupied": total_occupied,
            "total_empty": total_capacity - total_occupied,
            "total_capacity": total_capacity,
            "occupancy_rate": overall_rate,
        },
        "boxes": box_stats,
        "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True)),
    }

    stats_result = {
        # Backward compatibility: keep nested structure
        "data": data,
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
        "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True)),
        "record_count": len(records),
    }

    return {
        "ok": True,
        "result": stats_result,
    }


def tool_get_raw_entries(yaml_path, ids):
    """Return raw YAML entries for selected IDs."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML file: {exc}",
        }

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
