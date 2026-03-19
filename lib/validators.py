"""
Validation functions for LN2 inventory data
"""
from collections import defaultdict
from datetime import datetime
from .config import BOX_RANGE, POSITION_RANGE, VALID_ACTIONS
from .schema_aliases import (
    CANONICAL_STORED_AT_KEY,
    canonicalize_inventory_document,
    canonicalize_record_structural_aliases,
)
from .takeout_parser import normalize_action
from .position_fmt import (
    get_box_numbers,
    get_position_range,
    display_to_pos,
    _indexing,
)
from .validation_primitives import (
    is_plain_int as _is_plain_int,
    validate_date_format,
    parse_date as _parse_date_impl,
    record_label as _record_label,
    has_takeout_history,
    validate_record_fields,
)


def validate_date(date_str):
    """
    Validate date format YYYY-MM-DD

    Args:
        date_str: Date string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    return validate_date_format(date_str)


def parse_date(date_str):
    """Parse YYYY-MM-DD string to datetime object.

    Args:
        date_str: Date string to parse

    Returns:
        datetime or None if invalid
    """
    return _parse_date_impl(date_str)


def normalize_date_arg(date_str):
    """Normalize a date argument, accepting 'today'/'今天'/None as today's date.

    Args:
        date_str: Date string, 'today', '今天', or None

    Returns:
        YYYY-MM-DD string, or None if invalid
    """
    if date_str in (None, "", "today", "今天"):
        return datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        return None


def validate_box(box, layout=None):
    """
    Validate box number is in valid range.

    Args:
        box: Box number to validate
        layout: Optional box_layout dict; when provided, derives range from it.

    Returns:
        bool: True if valid, False otherwise
    """
    if isinstance(box, bool):
        return False

    try:
        box_num = int(box)
    except Exception:
        return False

    if layout is not None:
        return box_num in set(get_box_numbers(layout))
    return BOX_RANGE[0] <= box_num <= BOX_RANGE[1]


def _format_box_constraint(layout=None):
    """Format allowed box IDs for error messages."""
    if layout is not None:
        boxes = list(get_box_numbers(layout))
    else:
        boxes = list(range(BOX_RANGE[0], BOX_RANGE[1] + 1))

    if not boxes:
        return "N/A"
    if len(boxes) == 1:
        return str(boxes[0])

    is_contiguous = all(boxes[i] + 1 == boxes[i + 1] for i in range(len(boxes) - 1))
    if is_contiguous:
        return f"{boxes[0]}-{boxes[-1]}"

    return ",".join(str(b) for b in boxes)


def validate_position(pos, layout=None):
    """
    Validate position number is in valid range.

    Args:
        pos: Position number to validate
        layout: Optional box_layout dict; when provided, derives range from it.

    Returns:
        bool: True if valid, False otherwise
    """
    if not _is_plain_int(pos):
        return False

    if layout is not None:
        lo, hi = get_position_range(layout)
        return lo <= pos <= hi
    return POSITION_RANGE[0] <= pos <= POSITION_RANGE[1]


def validate_action(action):
    """
    Validate action type

    Args:
        action: Action string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    return action in VALID_ACTIONS


def parse_positions(positions_str, layout=None):
    """
    Parse position list: "1,2,3" or "1-3" (numeric), or "A1,A2" (alphanumeric).

    Args:
        positions_str: Position string to parse
        layout: Optional box_layout dict for alphanumeric support.

    Returns:
        list: Sorted list of unique internal integer positions

    Raises:
        ValueError: If format is invalid or positions out of range
    """
    positions = []
    is_alpha_mode = _indexing(layout) == "alphanumeric" if layout else False
    lo, hi = get_position_range(layout) if layout else (POSITION_RANGE[0], POSITION_RANGE[1])

    try:
        for part in positions_str.split(","):
            part = part.strip()
            if not part:
                continue
            if is_alpha_mode:
                if "-" in part:
                    raise ValueError("Ranges are not supported in alphanumeric mode")
                positions.append(display_to_pos(part, layout))
                continue

            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start = int(start_text)
                end = int(end_text)
                if end < start:
                    raise ValueError(f"Range end must be >= start: {part}")
                positions.extend(range(start, end + 1))
            else:
                positions.append(display_to_pos(part, layout))
    except Exception as e:
        raise ValueError(f"Invalid position format: {e}. Example: '1,2,3' or '1-3' or 'A1,A2'")

    for pos in positions:
        if not (lo <= pos <= hi):
            raise ValueError(f"Position {pos} out of range ({lo}-{hi})")

    return sorted(set(positions))


def format_chinese_date(date_str, weekday=False):
    """Convert YYYY-MM-DD to Chinese date text."""
    dt = parse_date(date_str)
    if not dt:
        return date_str
    base = f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"
    if weekday:
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        base += f" (周{weekdays[dt.weekday()]})"
    return base


def has_depletion_history(rec):
    """Return True if record has takeout history.

    Fully consumed records are expected to end with ``position=None``.
    """
    return has_takeout_history(rec, normalize_action)


def validate_record(rec, idx=None, layout=None, meta=None, inventory=None):
    """Validate one inventory record.

    Args:
        rec: Record dict
        idx: Optional index for error messages
        layout: Optional box_layout dict
        meta: Optional meta dict for dynamic required fields

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    from .custom_fields import get_effective_fields

    rec, alias_errors = canonicalize_record_structural_aliases(
        rec,
        label=_record_label(rec if isinstance(rec, dict) else {}, idx),
    )
    if alias_errors:
        return alias_errors, []

    pos_range = get_position_range(layout) if layout else (POSITION_RANGE[0], POSITION_RANGE[1])

    # Structural required fields
    structural_required = ["id", "box", CANONICAL_STORED_AT_KEY]

    # Separate effective fields into option-bearing (relaxed) vs others (strict)
    effective = (
        get_effective_fields(meta, box=rec.get("box"), inventory=inventory)
        if isinstance(meta, dict)
        else []
    )
    strict_required_keys = {
        f["key"] for f in effective
        if f.get("required") and not f.get("options")
    }

    required_fields = structural_required + sorted(strict_required_keys)

    # Build option fields list from effective fields with options
    option_fields = []
    if isinstance(meta, dict):
        for field_def in effective:
            foptions = field_def.get("options")
            if foptions:
                option_fields.append(field_def)

    # Capture layout for closures
    _layout = layout

    errors, warnings = validate_record_fields(
        rec,
        idx,
        pos_range=pos_range,
        validate_box_fn=lambda box: validate_box(box, _layout),
        format_box_constraint_fn=lambda: _format_box_constraint(_layout),
        normalize_action_fn=normalize_action,
        required_fields=required_fields,
        option_fields=option_fields,
        check_event_future_dates=True,
    )

    # Validate strict required user fields are non-empty strings
    # (additional runtime check beyond the shared core)
    rec_label = _record_label(rec, idx)
    for field in sorted(strict_required_keys):
        value = rec.get(field)
        if isinstance(value, str) and not value.strip():
            errors.append(f"{rec_label}: '{field}' must be a non-empty string")

    return errors, warnings


def check_duplicate_ids(records):
    """Check duplicate IDs across records."""
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


def check_position_conflicts(records, *, existing_count: int = 0):
    """Check active double-occupancy conflicts by (box, position).

    Args:
        records: Full list of inventory records to check.
        existing_count: Number of leading records that belong to the existing
            inventory.  Records at index >= existing_count are treated as
            "batch / new" entries.  When > 0, conflict messages distinguish
            between existing-inventory conflicts, batch-internal conflicts,
            and cross-source conflicts.
    """
    usage: dict = defaultdict(list)
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        box = rec.get("box")
        position = rec.get("position")
        if box is None or position is None:
            continue
        if _is_plain_int(box) and _is_plain_int(position):
            usage[(box, position)].append((idx, rec))

    conflicts: list[str] = []
    for (box, pos), entries in usage.items():
        if len(entries) <= 1:
            continue
        if existing_count > 0:
            conflicts.append(
                _format_conflict_with_source(box, pos, entries, existing_count)
            )
        else:
            rec_ids = ", ".join(
                f"#{idx + 1} (id={rec.get('id')})" for idx, rec in entries
            )
            conflicts.append(
                f"Position conflict: Box {box} Position {pos} "
                f"is occupied by multiple records: {rec_ids}"
            )
    return conflicts


def _format_conflict_with_source(
    box: int, pos: int, entries: list, existing_count: int
) -> str:
    """Format a position-conflict message distinguishing record sources.

    Args:
        box: Box number.
        pos: Position number.
        entries: List of ``(idx, rec)`` tuples occupying the same slot.
        existing_count: Index boundary; records with ``idx < existing_count``
            are "existing inventory", others are "batch / new".
    """
    existing = [(i, r) for i, r in entries if i < existing_count]
    batch = [(i, r) for i, r in entries if i >= existing_count]

    def _label(idx: int, rec: dict, source: str) -> str:
        return f"{source} #{idx + 1} (id={rec.get('id')})"

    if existing and batch:
        # Cross-source conflict
        ex_labels = ", ".join(_label(i, r, "existing") for i, r in existing)
        ba_labels = ", ".join(_label(i, r, "batch") for i, r in batch)
        return (
            f"Position conflict (cross-source): Box {box} Position {pos} — "
            f"{ex_labels} vs {ba_labels}"
        )
    if len(batch) >= 2:
        # Batch-internal conflict
        ba_labels = ", ".join(_label(i, r, "batch") for i, r in batch)
        return (
            f"Position conflict (batch-internal): Box {box} Position {pos} — "
            f"batch records occupy the same slot: {ba_labels}"
        )
    # Existing-only conflict (both records from existing inventory)
    ex_labels = ", ".join(_label(i, r, "existing") for i, r in existing)
    return (
        f"Position conflict: Box {box} Position {pos} "
        f"is occupied by multiple existing records: {ex_labels}"
    )


def validate_inventory(data):
    """Validate full inventory document.

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        return ["YAML root must be an object"], []

    data, alias_errors = canonicalize_inventory_document(data)
    if alias_errors:
        return alias_errors, []

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return ["'inventory' must be a list"], []

    meta = data.get("meta", {})
    from .custom_fields import unsupported_box_fields_issue

    unsupported_issue = unsupported_box_fields_issue(meta)
    if unsupported_issue:
        return [str(unsupported_issue.get("message") or "Unsupported dataset model.")], []

    layout = meta.get("box_layout", {})

    for idx, rec in enumerate(inventory):
        if not isinstance(rec, dict):
            errors.append(f"Record #{idx + 1}: must be an object")
            continue
        rec_errors, rec_warnings = validate_record(
            rec,
            idx=idx,
            layout=layout,
            meta=meta,
            inventory=inventory,
        )
        errors.extend(rec_errors)
        warnings.extend(rec_warnings)

    errors.extend(check_duplicate_ids(inventory))
    errors.extend(check_position_conflicts(inventory))
    return errors, warnings


def format_validation_errors(errors, prefix="Integrity validation failed"):
    """Format validation errors into a concise message."""
    if not errors:
        return prefix
    top = errors[:6]
    more = len(errors) - len(top)
    lines = [prefix] + [f"- {msg}" for msg in top]
    if more > 0:
        lines.append(f"- ... and {more} more")
    return "\n".join(lines)
