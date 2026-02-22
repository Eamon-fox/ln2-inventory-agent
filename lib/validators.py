"""
Validation functions for LN2 inventory data
"""
from collections import defaultdict
from datetime import datetime
from .config import BOX_RANGE, POSITION_RANGE, VALID_ACTIONS
from .takeout_parser import normalize_action
from .position_fmt import (
    get_box_numbers,
    get_position_range,
    display_to_pos,
    _indexing,
)


def validate_date(date_str):
    """
    Validate date format YYYY-MM-DD

    Args:
        date_str: Date string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _is_plain_int(value):
    """Return True only for integers, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def parse_date(date_str):
    """Parse YYYY-MM-DD string to datetime object.

    Args:
        date_str: Date string to parse

    Returns:
        datetime or None if invalid
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except ValueError:
        return None


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
    thaw_events = rec.get("thaw_events") or []
    for ev in thaw_events:
        if not isinstance(ev, dict):
            continue
        if normalize_action(ev.get("action")) == "takeout":
            return True

    return False


def _record_label(rec, idx):
    if idx is None:
        return f"Record (id={rec.get('id', 'N/A')})"
    return f"Record #{idx + 1} (id={rec.get('id', 'N/A')})"


def validate_record(rec, idx=None, layout=None, meta=None):
    """Validate one inventory record.

    Args:
        rec: Record dict
        idx: Optional index for error messages
        layout: Optional box_layout dict
        meta: Optional meta dict for dynamic required fields

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    from .custom_fields import get_required_field_keys, get_cell_line_options, is_cell_line_required

    errors = []
    warnings = []
    rec_id = _record_label(rec, idx)

    box_rule = _format_box_constraint(layout)
    pos_lo, pos_hi = get_position_range(layout) if layout else (POSITION_RANGE[0], POSITION_RANGE[1])

    # Structural required fields + user-defined required fields
    structural_required = ["id", "box", "frozen_at"]
    user_required = get_required_field_keys(meta)
    required_fields = structural_required + sorted(user_required)
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{rec_id}: missing required field '{field}'")

    rec_id_value = rec.get("id")
    if not _is_plain_int(rec_id_value) or rec_id_value <= 0:
        errors.append(f"{rec_id}: 'id' must be a positive integer")

    box = rec.get("box")
    if not _is_plain_int(box):
        errors.append(f"{rec_id}: 'box' must be an integer")
    elif not validate_box(box, layout):
        errors.append(f"{rec_id}: 'box' out of range ({box_rule})")

    # Validate required user fields are non-empty strings
    for field in sorted(user_required):
        value = rec.get(field)
        if isinstance(value, str) and not value.strip():
            errors.append(f"{rec_id}: '{field}' must be a non-empty string")

    # Relaxed baseline validation for cell_line:
    # - Do not block historical inventory due to non-option / empty values.
    # - Enforce strict options only during write tools (add/edit).
    if isinstance(meta, dict):
        cell_line_options = get_cell_line_options(meta)
        cell_line_required = is_cell_line_required(meta)
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
                warnings.append(f"{rec_id}: 'cell_line' is empty while required=true (legacy-compatible warning)")
            elif cell_line and cell_line_options and cell_line not in cell_line_options:
                opts_str = ", ".join(cell_line_options[:5])
                if len(cell_line_options) > 5:
                    opts_str += f" ... total {len(cell_line_options)}"
                warnings.append(
                    f"{rec_id}: 'cell_line' not in configured options ({opts_str}) "
                    "(legacy-compatible warning)"
                )

    # Validate position (single integer, optional for consumed records)
    position = rec.get("position")
    if position is not None:
        if not _is_plain_int(position):
            errors.append(f"{rec_id}: 'position' must be an integer")
        elif not validate_position(position, layout):
            errors.append(f"{rec_id}: 'position' {position} out of range ({pos_lo}-{pos_hi})")
    else:
        # position is None - record should have depletion history
        if not has_depletion_history(rec):
            errors.append(f"{rec_id}: 'position' is null but no takeout history found")

    frozen_at = rec.get("frozen_at")
    if not validate_date(frozen_at):
        errors.append(f"{rec_id}: 'frozen_at' must be YYYY-MM-DD")
    else:
        frozen_date = parse_date(frozen_at)
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

                ev_action = normalize_action(ev.get("action"))
                if not ev_action:
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] has invalid action")

                ev_date = ev.get("date")
                if not validate_date(ev_date):
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] has invalid date")

                ev_positions = ev.get("positions")
                if isinstance(ev_positions, int):
                    ev_positions = [ev_positions]
                if not isinstance(ev_positions, list) or not ev_positions:
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] positions must be a non-empty list")
                    continue

                seen_ev_pos = set()
                for ev_pos in ev_positions:
                    if not isinstance(ev_pos, int):
                        errors.append(f"{rec_id}: thaw_events[{event_idx}] position {ev_pos} must be an integer")
                        continue
                    if not validate_position(ev_pos, layout):
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] position {ev_pos} out of range ({pos_lo}-{pos_hi})"
                        )
                        continue
                    if ev_pos in seen_ev_pos:
                        errors.append(f"{rec_id}: thaw_events[{event_idx}] duplicate position {ev_pos}")
                    seen_ev_pos.add(ev_pos)

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


def check_position_conflicts(records):
    """Check active double-occupancy conflicts by (box, position)."""
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


def validate_inventory(data):
    """Validate full inventory document.

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        return ["YAML root must be an object"], []

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return ["'inventory' must be a list"], []

    meta = data.get("meta", {})
    layout = meta.get("box_layout", {})

    for idx, rec in enumerate(inventory):
        if not isinstance(rec, dict):
            errors.append(f"Record #{idx + 1}: must be an object")
            continue
        rec_errors, rec_warnings = validate_record(rec, idx=idx, layout=layout, meta=meta)
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


def validate_plan_item_with_history(new_item, existing_items, tr_fn=None):
    """Validate a new item against all existing items in plan.

    This function is shared between operations_panel (human) and tool_runner (AI agent)
    to ensure consistent validation behavior.

    Args:
        new_item: New plan item to validate
        existing_items: List of existing plan items to check against
        tr_fn: Optional translation function (i18n.tr). If None, uses default messages.

    Returns:
        tuple[bool, str]: (is_valid, error_message)
            is_valid=True, error_message=None if validation passes
            is_valid=False, error_message="error text" if blocked
    """
    if tr_fn is None:
        # Default fallback without translation
        def tr_fn(key, **kwargs):
            return key.format(**kwargs)

    # Collect all positions that will be affected by existing items
    all_positions = []
    for existing in existing_items:
        action = existing.get("action", "").lower()
        if action == "move":
            # For move, track both from and to positions
            box = existing.get("box", 0)
            pos = existing.get("position")
            to_box = existing.get("to_box")
            to_pos = existing.get("to_position")
            all_positions.append((box, pos))
            # Track target position (use source box if to_box is None for same-box moves)
            if to_pos is not None:
                target_box = to_box if to_box is not None else box
                all_positions.append((target_box, to_pos))
        elif action == "add":
            # For add, track all positions
            box = existing.get("box", 0)
            payload = existing.get("payload") or {}
            positions = payload.get("positions", [])
            for p in positions:
                all_positions.append((box, p))
        else:
            # takeout: track source position
            box = existing.get("box", 0)
            pos = existing.get("position")
            if pos is not None:
                all_positions.append((box, pos))

    # Check if new item conflicts with any existing position
    new_action = new_item.get("action", "").lower()
    new_box = new_item.get("box", 0)

    if new_action == "add":
        # Add: check if any target position is occupied
        payload = new_item.get("payload") or {}
        positions = payload.get("positions", [])
        for pos in positions:
            if (new_box, pos) in all_positions:
                return False, tr_fn("operations.positionOccupied", box=new_box, position=pos)
    elif new_action == "move":
        # Move: check source position, target position (same box or cross-box)
        new_from_pos = new_item.get("position")
        new_to_pos = new_item.get("to_position")
        new_to_box = new_item.get("to_box")

        # Check if source position is still valid (not moved away by another item)
        if (new_box, new_from_pos) in all_positions:
            return False, tr_fn("operations.sourcePositionAlreadyMoved")

        # Check target position
        if new_to_pos is not None:
            target = (new_to_box, new_to_pos) if new_to_box else (new_box, new_to_pos)
            if target in all_positions:
                return False, tr_fn("operations.targetPositionOccupied", box=target[0], position=target[1])

    # takeout: source position check already done by position occupancy check
    return True, None

