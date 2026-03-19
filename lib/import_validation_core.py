"""Shared strict validation core for import acceptance and migrate script."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .validation_primitives import (
    is_plain_int as _is_plain_int,
    validate_date_format as _validate_date,
    parse_date as _parse_date,
    record_label as _record_label,
    has_takeout_history as _has_takeout_history_core,
    validate_record_fields,
)
from .custom_fields import unsupported_box_fields_issue
from .legacy_field_policy import (
    CELL_LINE_FIELD_KEY,
    PHASE_IMPORT,
    canonicalize_record_legacy_fields,
    resolve_legacy_field_policy,
    normalize_legacy_custom_field_defs,
)
from .schema_aliases import (
    ALL_STRUCTURAL_FIELD_KEYS,
    CANONICAL_STORAGE_EVENTS_KEY,
    CANONICAL_STORED_AT_KEY,
    CANONICAL_STRUCTURAL_FIELD_KEYS,
    canonicalize_inventory_document,
)


ALLOWED_ROOT_KEYS = frozenset({"meta", "inventory"})

STRUCTURAL_FIELD_KEYS = frozenset(
    CANONICAL_STRUCTURAL_FIELD_KEYS
)

# Fields that are auto-injected as default custom fields when not explicitly
# declared.  Kept here so _allowed_record_field_keys can include them.
_DEFAULT_FIELD_KEYS = frozenset({"note"})

_VALID_CUSTOM_TYPES = frozenset({"str", "int", "float", "date"})
_BOX_TAG_MAX_LENGTH = 80
_UNDECLARED_FIELD_RECORD_SAMPLE_LIMIT = 20

ACTION_ALIAS = {
    "takeout": "takeout",
    "move": "move",
    "\u53d6\u51fa": "takeout",
    "\u79fb\u52a8": "move",
}


def _normalize_action(action: Any) -> Optional[str]:
    if action is None:
        return None
    raw = str(action).strip()
    return ACTION_ALIAS.get(raw.lower()) or ACTION_ALIAS.get(raw)


def _has_takeout_history(rec: Dict[str, Any]) -> bool:
    return _has_takeout_history_core(rec, _normalize_action)


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
    unsupported_issue = unsupported_box_fields_issue(meta)
    if unsupported_issue:
        errors.append(str(unsupported_issue.get("message") or "Unsupported dataset model."))
        return errors, normalized

    raw = (meta or {}).get("custom_fields")
    if raw is None:
        return errors, normalized

    if not isinstance(raw, list):
        return ["meta.custom_fields must be a list"], normalized

    raw, _alias_changes = normalize_legacy_custom_field_defs(raw)

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
        if key in ALL_STRUCTURAL_FIELD_KEYS:
            errors.append(
                f"meta.custom_fields[{idx}] key='{key}' conflicts with structural field"
            )
            continue
        if key in seen:
            errors.append(f"meta.custom_fields[{idx}] duplicate key='{key}'")
            continue

        if key == "note":
            # ``note`` is a fixed system field: always text + optional.
            seen.add(key)
            normalized.append(
                {
                    "key": "note",
                    "required": False,
                    "type": "str",
                }
            )
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
        entry = {
            "key": key,
            "required": bool(item.get("required")),
            "type": field_type,
        }
        raw_options = item.get("options")
        if isinstance(raw_options, list):
            entry["options"] = [str(o) for o in raw_options if o]
        normalized.append(entry)

    return errors, normalized


def _required_custom_fields(normalized_custom_fields: List[Dict[str, Any]]) -> List[str]:
    required = []
    for item in normalized_custom_fields:
        key = str(item.get("key") or "").strip()
        if key and bool(item.get("required")):
            required.append(key)
    return sorted(set(required))


def _declared_custom_field_keys(normalized_custom_fields: List[Dict[str, Any]]) -> set:
    keys = set()
    for item in normalized_custom_fields:
        key = str((item or {}).get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def _allowed_record_field_keys(
    meta: Dict[str, Any],
    records: List[Dict[str, Any]],
    normalized_custom_fields: List[Dict[str, Any]],
) -> set:
    policy = resolve_legacy_field_policy(
        meta,
        records,
        declared_fields=normalized_custom_fields,
        phase=PHASE_IMPORT,
    )
    declared = _declared_custom_field_keys(policy.get("declared_fields") or normalized_custom_fields)
    allowed = set(STRUCTURAL_FIELD_KEYS) | set(_DEFAULT_FIELD_KEYS) | declared
    allowed.update(set(policy.get("staging_input_keys") or set()))
    return allowed


def _check_undeclared_record_fields(
    meta: Dict[str, Any],
    records: List[Dict[str, Any]],
    normalized_custom_fields: List[Dict[str, Any]],
) -> List[str]:
    """Reject inventory record keys not declared by structural fields/custom_fields."""
    allowed = _allowed_record_field_keys(meta, records, normalized_custom_fields)
    unknown_global = set()
    unknown_by_record = []

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue

        unknown_keys = sorted(
            {str(raw_key).strip() for raw_key in rec.keys() if str(raw_key).strip() not in allowed}
        )
        if not unknown_keys:
            continue

        unknown_global.update(unknown_keys)
        unknown_by_record.append((_record_label(rec, idx), unknown_keys))

    if not unknown_global:
        return []

    errors = [
        "Unsupported inventory field(s): "
        f"{', '.join(sorted(unknown_global))}. "
        "Declare them in meta.custom_fields first."
    ]
    for label, keys in unknown_by_record[:_UNDECLARED_FIELD_RECORD_SAMPLE_LIMIT]:
        errors.append(f"{label}: unsupported field(s): {', '.join(keys)}")

    hidden_count = len(unknown_by_record) - _UNDECLARED_FIELD_RECORD_SAMPLE_LIMIT
    if hidden_count > 0:
        errors.append(f"... and {hidden_count} more record(s) with unsupported field(s)")

    return errors


def _selector_key_candidates(
    meta: Dict[str, Any],
    records: List[Dict[str, Any]],
    normalized_custom_fields: List[Dict[str, Any]],
) -> List[str]:
    """Return allowed selector keys for meta.display_key/meta.color_key."""
    ordered = []
    seen: set = set()
    policy = resolve_legacy_field_policy(
        meta,
        records,
        declared_fields=normalized_custom_fields,
        phase=PHASE_IMPORT,
    )
    declared = _declared_custom_field_keys(policy.get("declared_fields") or normalized_custom_fields)
    default_keys = set(_DEFAULT_FIELD_KEYS)
    if policy.get("staging_cell_line"):
        default_keys.add(CELL_LINE_FIELD_KEY)
    for dk in sorted(default_keys):
        if dk not in seen:
            seen.add(dk)
            ordered.append(dk)
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
    records: List[Dict[str, Any]],
    normalized_custom_fields: List[Dict[str, Any]],
) -> List[str]:
    """Validate ``meta.display_key`` and ``meta.color_key`` against known keys."""
    errors: List[str] = []
    allowed_keys = _selector_key_candidates(meta, records, normalized_custom_fields)
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


def _validate_record(
    rec: Dict[str, Any],
    idx: int,
    layout: Dict[str, Any],
    meta: Dict[str, Any],
    required_custom_field_keys: List[str],
    normalized_custom_fields: List[Dict[str, Any]] | None = None,
) -> Tuple[List[str], List[str]]:
    pos_range = _position_range(layout)
    validation_rec = dict(rec) if isinstance(rec, dict) else rec
    if isinstance(validation_rec, dict):
        canonicalize_record_legacy_fields(validation_rec)

    required_fields = ["id", "box", CANONICAL_STORED_AT_KEY] + list(required_custom_field_keys)

    policy = resolve_legacy_field_policy(
        meta,
        [rec],
        declared_fields=normalized_custom_fields,
        phase=PHASE_IMPORT,
    )
    if (
        CELL_LINE_FIELD_KEY not in required_fields
        and policy.get("has_legacy_meta")
    ):
        explicit_cell_line = policy.get("explicit_cell_line")
        if explicit_cell_line is not None:
            if explicit_cell_line.get("required"):
                required_fields.append(CELL_LINE_FIELD_KEY)
        else:
            for field_def in policy.get("effective_fields") or []:
                if str((field_def or {}).get("key") or "").strip() != CELL_LINE_FIELD_KEY:
                    continue
                if field_def.get("required"):
                    required_fields.append(CELL_LINE_FIELD_KEY)
                break
    option_fields: List[Dict[str, Any]] = []
    for field_def in policy.get("effective_fields") or []:
        if not isinstance(field_def, dict):
            continue
        if field_def.get("options"):
            option_fields.append(field_def)

    # Build box validation closures for this layout context.
    _layout = layout

    def _validate_box(box_value: Any) -> bool:
        if not _is_plain_int(box_value):
            return False
        box_nums = _box_numbers(_layout)
        if box_nums and box_value not in set(box_nums):
            return False
        if box_value <= 0:
            return False
        return True

    def _format_box_constraint() -> str:
        box_nums = _box_numbers(_layout)
        if not box_nums:
            return "positive integer"
        return ",".join(str(v) for v in box_nums)

    return validate_record_fields(
        validation_rec,
        idx,
        pos_range=pos_range,
        validate_box_fn=_validate_box,
        format_box_constraint_fn=_format_box_constraint,
        normalize_action_fn=_normalize_action,
        required_fields=required_fields,
        option_fields=option_fields,
        check_event_future_dates=True,
    )


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
    """Check position conflicts within import/migration data.

    All records are treated as batch entries.  Conflict messages explicitly
    state that the conflict is *within the import data* so that users and
    agents do not confuse them with existing-inventory conflicts.
    """
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
        rec_ids = ", ".join(
            f"#{idx + 1} (id={rec.get('id')})" for idx, rec in entries
        )
        conflicts.append(
            f"Import data internal conflict: Box {box} Position {pos} "
            f"is occupied by multiple records within the import data: {rec_ids}"
        )
    return conflicts


def validate_inventory_document(
    data: Any,
    *,
    skip_record_validation: bool = False,
) -> Tuple[List[str], List[str]]:
    """Validate an in-memory inventory document.

    Args:
        data: The full YAML dict (``meta`` + ``inventory``).
        skip_record_validation: When ``True``, skip per-record value checks
            (options, required, types) and global record checks (duplicate IDs,
            position conflicts).  Meta-level validation (schema, layout,
            custom-fields contract, undeclared record keys) still runs.
            Use this when saving field-definition changes so that stale
            record data does not block meta updates.
    """
    errors = []
    warnings = []

    data, alias_errors = canonicalize_inventory_document(data)
    errors.extend(alias_errors)

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
    errors.extend(_validate_meta_selection_keys(meta, inventory, normalized_custom_fields))
    errors.extend(_check_undeclared_record_fields(meta, inventory, normalized_custom_fields))

    errors.extend(_check_inventory_boxes_match_layout(inventory, layout))

    if not skip_record_validation:
        required_custom_fields = _required_custom_fields(normalized_custom_fields)
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
                normalized_custom_fields=normalized_custom_fields,
            )
            errors.extend(rec_errors)
            warnings.extend(rec_warnings)

        errors.extend(_check_duplicate_ids(inventory))
        errors.extend(_check_position_conflicts(inventory))

    return errors, warnings
