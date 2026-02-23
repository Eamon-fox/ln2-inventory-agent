"""Shared strict validation core for import acceptance and migrate script."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple


ALLOWED_ROOT_KEYS = frozenset({"meta", "inventory"})

STRUCTURAL_FIELD_KEYS = frozenset(
    {
        "id",
        "box",
        "position",
        "frozen_at",
        "thaw_events",
        "cell_line",
        "note",
    }
)

_VALID_CUSTOM_TYPES = frozenset({"str", "int", "float", "date"})
_BOX_TAG_MAX_LENGTH = 80

ACTION_ALIAS = {
    "takeout": "takeout",
    "move": "move",
    "\u53d6\u51fa": "takeout",
    "\u79fb\u52a8": "move",
}

DEFAULT_CELL_LINE_OPTIONS = [
    "Unknown",
    "K562",
    "HeLa",
    "NCCIT",
    "HEK293T",
    "HCT116",
    "U2OS",
    "A549",
    "MCF7",
    "HepG2",
    "Huh7",
    "SW480",
    "SW620",
    "HT29",
    "DLD1",
    "RKO",
    "PC3",
    "DU145",
    "LNCaP",
    "A375",
    "SK-MEL-28",
    "Jurkat",
    "Raji",
    "THP-1",
    "MDA-MB-231",
    "mESC",
]

def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_date(date_str: Any) -> bool:
    try:
        datetime.strptime(str(date_str), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _parse_date(date_str: Any):
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except Exception:
        return None


def _normalize_action(action: Any):
    if action is None:
        return None
    raw = str(action).strip()
    return ACTION_ALIAS.get(raw.lower()) or ACTION_ALIAS.get(raw)


def _position_range(layout: Dict[str, Any]) -> Tuple[int, int]:
    layout = layout or {}
    rows = layout.get("rows", 9)
    cols = layout.get("cols", 9)
    try:
        rows = int(rows)
        cols = int(cols)
    except Exception:
        return (1, 81)
    if rows <= 0 or cols <= 0:
        return (1, 81)
    return (1, rows * cols)


def _box_numbers(layout: Dict[str, Any]) -> List[int]:
    layout = layout or {}
    raw = layout.get("box_numbers")
    if isinstance(raw, (list, tuple)):
        out = []
        seen = set()
        for item in raw:
            try:
                num = int(item)
            except Exception:
                continue
            if num <= 0 or num in seen:
                continue
            seen.add(num)
            out.append(num)
        out.sort()
        if out:
            return out

    count = layout.get("box_count")
    if count is None:
        return []
    try:
        count = int(count)
    except Exception:
        return []
    if count <= 0:
        return []
    return list(range(1, count + 1))


def _validate_box_layout_contract(layout: Dict[str, Any]) -> List[str]:
    """Strictly validate required box layout fields for managed datasets."""
    errors: List[str] = []

    box_count = layout.get("box_count")
    parsed_box_count = None
    if not isinstance(box_count, int) or isinstance(box_count, bool):
        errors.append("meta.box_layout.box_count is required and must be a positive integer")
    elif box_count <= 0:
        errors.append("meta.box_layout.box_count is required and must be a positive integer")
    else:
        parsed_box_count = box_count

    raw_numbers = layout.get("box_numbers")
    parsed_numbers: List[int] = []
    if not isinstance(raw_numbers, list) or not raw_numbers:
        errors.append(
            "meta.box_layout.box_numbers is required and must be a non-empty list of positive integers"
        )
    else:
        seen = set()
        for idx, value in enumerate(raw_numbers):
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f"meta.box_layout.box_numbers[{idx}] must be a positive integer"
                )
                continue
            num = value
            if num <= 0:
                errors.append(
                    f"meta.box_layout.box_numbers[{idx}] must be a positive integer"
                )
                continue
            if num in seen:
                errors.append(
                    f"meta.box_layout.box_numbers[{idx}] duplicates value {num}"
                )
                continue
            seen.add(num)
            parsed_numbers.append(num)

        if parsed_numbers and parsed_numbers != sorted(parsed_numbers):
            errors.append("meta.box_layout.box_numbers must be sorted in ascending order")

    if parsed_box_count is not None and parsed_numbers:
        if len(parsed_numbers) != parsed_box_count:
            errors.append(
                "meta.box_layout mismatch: "
                f"box_count={parsed_box_count} but box_numbers has {len(parsed_numbers)} item(s)"
            )

    return errors


def _validate_box_tags(layout: Dict[str, Any]) -> List[str]:
    """Validate optional meta.box_layout.box_tags mapping."""
    raw_tags = layout.get("box_tags")
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, dict):
        return ["meta.box_layout.box_tags must be an object"]

    errors: List[str] = []
    declared_numbers = _box_numbers(layout)
    declared_set = set(declared_numbers)
    declared_text = ",".join(str(v) for v in declared_numbers)

    for raw_box, raw_tag in raw_tags.items():
        box_text = str(raw_box).strip()
        if not box_text.isdigit():
            errors.append(
                f"meta.box_layout.box_tags key '{raw_box}' must be a positive integer"
            )
            continue

        box_num = int(box_text)
        if box_num <= 0:
            errors.append(
                f"meta.box_layout.box_tags key '{raw_box}' must be a positive integer"
            )
            continue

        if declared_set and box_num not in declared_set:
            errors.append(
                "meta.box_layout.box_tags key "
                f"'{raw_box}' is not in declared box_numbers ({declared_text})"
            )
            continue

        tag_text = "" if raw_tag is None else str(raw_tag)
        if "\n" in tag_text or "\r" in tag_text:
            errors.append(
                f"meta.box_layout.box_tags[{box_num}] must be a single-line string"
            )
            continue

        tag_text = tag_text.strip()
        if not tag_text:
            errors.append(
                f"meta.box_layout.box_tags[{box_num}] must be a non-empty string"
            )
            continue

        if len(tag_text) > _BOX_TAG_MAX_LENGTH:
            errors.append(
                f"meta.box_layout.box_tags[{box_num}] must be <= "
                f"{_BOX_TAG_MAX_LENGTH} characters"
            )

    return errors


def _check_inventory_boxes_match_layout(
    records: List[Dict[str, Any]],
    layout: Dict[str, Any],
) -> List[str]:
    """Ensure inventory uses only boxes declared in meta.box_layout."""
    declared_numbers = _box_numbers(layout)
    if not declared_numbers:
        return []

    declared_set = set(declared_numbers)
    used_numbers = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        box = rec.get("box")
        if isinstance(box, int) and not isinstance(box, bool):
            box_num = box
            if box_num > 0:
                used_numbers.add(box_num)

    undeclared = sorted(box for box in used_numbers if box not in declared_set)
    if not undeclared:
        return []

    undeclared_text = ",".join(str(v) for v in undeclared)
    declared_text = ",".join(str(v) for v in declared_numbers)
    return [
        "Inventory uses undeclared boxes: "
        f"{undeclared_text}. Declared boxes are: {declared_text}. "
        "Update meta.box_layout.box_numbers/box_count to match inventory."
    ]


def validate_root_and_layout(data: Any) -> List[str]:
    errors = []
    if not isinstance(data, dict):
        return ["YAML root must be an object"]

    root_keys = set(data.keys())
    missing = sorted(ALLOWED_ROOT_KEYS - root_keys)
    extra = sorted(root_keys - ALLOWED_ROOT_KEYS)
    for key in missing:
        errors.append(f"Missing top-level key: '{key}'")
    if extra:
        errors.append(f"Unsupported top-level key(s): {', '.join(extra)}")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("'meta' must be an object")
        return errors

    layout = meta.get("box_layout")
    if not isinstance(layout, dict):
        errors.append("meta.box_layout must be an object")
        return errors

    rows = layout.get("rows")
    cols = layout.get("cols")
    if not isinstance(rows, int) or isinstance(rows, bool):
        errors.append("meta.box_layout.rows must be a positive integer")
    elif rows <= 0:
        errors.append("meta.box_layout.rows must be a positive integer")
    if not isinstance(cols, int) or isinstance(cols, bool):
        errors.append("meta.box_layout.cols must be a positive integer")
    elif cols <= 0:
        errors.append("meta.box_layout.cols must be a positive integer")

    errors.extend(_validate_box_layout_contract(layout))
    errors.extend(_validate_box_tags(layout))

    return errors


def validate_custom_fields_contract(meta: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    errors: List[str] = []
    normalized: List[Dict[str, Any]] = []
    raw = (meta or {}).get("custom_fields")
    if raw is None:
        return errors, normalized

    if not isinstance(raw, list):
        return ["meta.custom_fields must be a list"], normalized

    seen = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"meta.custom_fields[{idx}] must be an object")
            continue

        key = str(item.get("key") or "").strip()
        if not key:
            errors.append(f"meta.custom_fields[{idx}] missing 'key'")
            continue
        if not key.isidentifier():
            errors.append(f"meta.custom_fields[{idx}] key='{key}' must be a valid identifier")
            continue
        if key in STRUCTURAL_FIELD_KEYS:
            errors.append(
                f"meta.custom_fields[{idx}] key='{key}' conflicts with structural field"
            )
            continue
        if key in seen:
            errors.append(f"meta.custom_fields[{idx}] duplicate key='{key}'")
            continue

        field_type = str(item.get("type") or "str").strip().lower()
        if field_type not in _VALID_CUSTOM_TYPES:
            errors.append(
                "meta.custom_fields[{idx}] key='{key}' has unsupported type='{field_type}'".format(
                    idx=idx,
                    key=key,
                    field_type=field_type,
                )
            )
            continue

        seen.add(key)
        normalized.append(
            {
                "key": key,
                "required": bool(item.get("required")),
                "type": field_type,
            }
        )

    return errors, normalized


def _required_custom_fields(normalized_custom_fields: List[Dict[str, Any]]) -> List[str]:
    required = []
    for item in normalized_custom_fields:
        key = str(item.get("key") or "").strip()
        if key and bool(item.get("required")):
            required.append(key)
    return sorted(set(required))


def _selector_key_candidates(normalized_custom_fields: List[Dict[str, Any]]) -> List[str]:
    """Return allowed selector keys for meta.display_key/meta.color_key."""
    ordered = ["cell_line"]
    seen = {"cell_line"}
    for item in normalized_custom_fields:
        key = str((item or {}).get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _format_allowed_selector_keys(keys: List[str], *, limit: int = 8) -> str:
    shown = list(keys or [])
    if len(shown) <= limit:
        return ", ".join(shown)
    head = ", ".join(shown[:limit])
    return f"{head} ... total {len(shown)}"


def _validate_meta_selection_keys(
    meta: Dict[str, Any],
    normalized_custom_fields: List[Dict[str, Any]],
) -> List[str]:
    """Validate ``meta.display_key`` and ``meta.color_key`` against known keys."""
    errors: List[str] = []
    allowed_keys = _selector_key_candidates(normalized_custom_fields)
    allowed_set = set(allowed_keys)
    allowed_text = _format_allowed_selector_keys(allowed_keys)

    for field_name in ("display_key", "color_key"):
        if field_name not in (meta or {}):
            continue
        raw_value = (meta or {}).get(field_name)
        if raw_value is None:
            continue
        if not isinstance(raw_value, str):
            errors.append(
                f"meta.{field_name} must be a string key; allowed keys: {allowed_text}"
            )
            continue

        normalized_value = raw_value.strip()
        if not normalized_value:
            errors.append(
                f"meta.{field_name} must not be empty; allowed keys: {allowed_text}"
            )
            continue
        if normalized_value != raw_value:
            errors.append(
                f"meta.{field_name}={raw_value!r} has leading/trailing whitespace; "
                f"use {normalized_value!r}"
            )
            continue
        if normalized_value not in allowed_set:
            errors.append(
                f"meta.{field_name}={normalized_value!r} is invalid; "
                f"allowed keys: {allowed_text}"
            )

    return errors


def _cell_line_options(meta: Dict[str, Any]) -> List[str]:
    opts = (meta or {}).get("cell_line_options")
    if isinstance(opts, list):
        return [str(o) for o in opts if o]
    return list(DEFAULT_CELL_LINE_OPTIONS)


def _is_cell_line_required(meta: Dict[str, Any]) -> bool:
    return bool((meta or {}).get("cell_line_required", True))


def _record_label(rec: Dict[str, Any], idx: int) -> str:
    return f"Record #{idx + 1} (id={rec.get('id', 'N/A')})"


def _has_takeout_history(rec: Dict[str, Any]) -> bool:
    thaw_events = rec.get("thaw_events") or []
    if not isinstance(thaw_events, list):
        return False
    for ev in thaw_events:
        if not isinstance(ev, dict):
            continue
        if _normalize_action(ev.get("action")) == "takeout":
            return True
    return False


def _validate_record(
    rec: Dict[str, Any],
    idx: int,
    layout: Dict[str, Any],
    meta: Dict[str, Any],
    required_custom_field_keys: List[str],
) -> Tuple[List[str], List[str]]:
    errors = []
    warnings = []
    rec_id = _record_label(rec, idx)
    pos_lo, pos_hi = _position_range(layout)

    required_fields = ["id", "box", "frozen_at"] + list(required_custom_field_keys)
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{rec_id}: missing required field '{field}'")

    rec_id_value = rec.get("id")
    if not isinstance(rec_id_value, int) or isinstance(rec_id_value, bool):
        errors.append(f"{rec_id}: 'id' must be a positive integer")
    elif rec_id_value <= 0:
        errors.append(f"{rec_id}: 'id' must be a positive integer")

    box = rec.get("box")
    if not isinstance(box, int) or isinstance(box, bool):
        errors.append(f"{rec_id}: 'box' must be an integer")
    else:
        box_num = box
        box_numbers = _box_numbers(layout)
        if box_numbers and box_num not in set(box_numbers):
            allowed = ",".join(str(v) for v in box_numbers)
            errors.append(f"{rec_id}: 'box' out of range ({allowed})")
        elif box_num <= 0:
            errors.append(f"{rec_id}: 'box' must be a positive integer")

    position = rec.get("position")
    if position is not None:
        if not _is_plain_int(position):
            errors.append(f"{rec_id}: 'position' must be an integer")
        elif not (pos_lo <= position <= pos_hi):
            errors.append(f"{rec_id}: 'position' {position} out of range ({pos_lo}-{pos_hi})")
    elif not _has_takeout_history(rec):
        errors.append(f"{rec_id}: 'position' is null but no takeout history found")

    frozen_at = rec.get("frozen_at")
    if not _validate_date(frozen_at):
        errors.append(f"{rec_id}: 'frozen_at' must be YYYY-MM-DD")
    else:
        frozen_date = _parse_date(frozen_at)
        if frozen_date and frozen_date > datetime.now():
            errors.append(f"{rec_id}: frozen date {frozen_at} is in the future")

    thaw_events = rec.get("thaw_events")
    if thaw_events is not None:
        if not isinstance(thaw_events, list):
            errors.append(f"{rec_id}: 'thaw_events' must be a list")
        else:
            for event_idx, ev in enumerate(thaw_events, 1):
                if not isinstance(ev, dict):
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] must be an object")
                    continue

                ev_action = _normalize_action(ev.get("action"))
                if not ev_action:
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] has invalid action")

                ev_date = ev.get("date")
                if not _validate_date(ev_date):
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] has invalid date")
                else:
                    parsed_ev_date = _parse_date(ev_date)
                    if parsed_ev_date and parsed_ev_date > datetime.now():
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] date {ev_date} is in the future"
                        )

                ev_positions = ev.get("positions")
                if isinstance(ev_positions, int):
                    ev_positions = [ev_positions]
                if not isinstance(ev_positions, list) or not ev_positions:
                    errors.append(
                        f"{rec_id}: thaw_events[{event_idx}] positions must be a non-empty list"
                    )
                    continue

                seen_ev_pos = set()
                for ev_pos in ev_positions:
                    if not _is_plain_int(ev_pos):
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] position {ev_pos} must be an integer"
                        )
                        continue
                    if not (pos_lo <= ev_pos <= pos_hi):
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] position {ev_pos} out of range ({pos_lo}-{pos_hi})"
                        )
                        continue
                    if ev_pos in seen_ev_pos:
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] duplicate position {ev_pos}"
                        )
                    seen_ev_pos.add(ev_pos)

    cell_line_options = _cell_line_options(meta)
    cell_line_required = _is_cell_line_required(meta)
    has_cell_line_key = "cell_line" in rec
    if not has_cell_line_key:
        warnings.append(f"{rec_id}: missing 'cell_line' (legacy-compatible warning)")
    else:
        raw_cell_line = rec.get("cell_line")
        if raw_cell_line is None:
            cell_line = ""
        elif isinstance(raw_cell_line, str):
            cell_line = raw_cell_line.strip()
        else:
            cell_line = str(raw_cell_line).strip()
            warnings.append(f"{rec_id}: 'cell_line' is not a string (legacy-compatible warning)")

        if cell_line_required and not cell_line:
            warnings.append(
                f"{rec_id}: 'cell_line' is empty while required=true (legacy-compatible warning)"
            )
        elif cell_line and cell_line_options and cell_line not in cell_line_options:
            opts_str = ", ".join(cell_line_options[:5])
            if len(cell_line_options) > 5:
                opts_str += f" ... total {len(cell_line_options)}"
            warnings.append(
                f"{rec_id}: 'cell_line' not in configured options ({opts_str}) "
                "(legacy-compatible warning)"
            )

    return errors, warnings


def _check_duplicate_ids(records: List[Dict[str, Any]]) -> List[str]:
    id_map = {}
    errors = []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        rec_id = rec.get("id")
        if rec_id is None:
            continue
        if rec_id in id_map:
            prev_idx = id_map[rec_id]
            errors.append(
                f"Duplicate ID {rec_id}: Record #{prev_idx + 1} and Record #{idx + 1}"
            )
        else:
            id_map[rec_id] = idx
    return errors


def _check_position_conflicts(records: List[Dict[str, Any]]) -> List[str]:
    usage = defaultdict(list)
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        box = rec.get("box")
        position = rec.get("position")
        if box is None or position is None:
            continue
        if _is_plain_int(box) and _is_plain_int(position):
            usage[(box, position)].append((idx, rec))

    conflicts = []
    for (box, pos), entries in usage.items():
        if len(entries) <= 1:
            continue
        rec_ids = ", ".join(f"#{idx + 1} (id={rec.get('id')})" for idx, rec in entries)
        conflicts.append(
            f"Position conflict: Box {box} Position {pos} is occupied by multiple records: {rec_ids}"
        )
    return conflicts


def validate_inventory_document(data: Any) -> Tuple[List[str], List[str]]:
    errors = []
    warnings = []

    root_errors = validate_root_and_layout(data)
    errors.extend(root_errors)
    if root_errors:
        return errors, warnings

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return ["'inventory' must be a list"], []

    meta = data.get("meta", {})
    layout = meta.get("box_layout", {})
    contract_errors, normalized_custom_fields = validate_custom_fields_contract(meta)
    errors.extend(contract_errors)
    errors.extend(_validate_meta_selection_keys(meta, normalized_custom_fields))
    required_custom_fields = _required_custom_fields(normalized_custom_fields)

    errors.extend(_check_inventory_boxes_match_layout(inventory, layout))

    for idx, rec in enumerate(inventory):
        if not isinstance(rec, dict):
            errors.append(f"Record #{idx + 1}: must be an object")
            continue
        rec_errors, rec_warnings = _validate_record(
            rec,
            idx=idx,
            layout=layout,
            meta=meta,
            required_custom_field_keys=required_custom_fields,
        )
        errors.extend(rec_errors)
        warnings.extend(rec_warnings)

    errors.extend(_check_duplicate_ids(inventory))
    errors.extend(_check_position_conflicts(inventory))
    return errors, warnings
