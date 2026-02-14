"""
Validation functions for LN2 inventory data
"""
from collections import defaultdict
from datetime import datetime
from .config import BOX_RANGE, POSITION_RANGE, VALID_ACTIONS
from .thaw_parser import normalize_action
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
    is_alpha = _indexing(layout) == "alphanumeric" if layout else False
    lo, hi = get_position_range(layout) if layout else (POSITION_RANGE[0], POSITION_RANGE[1])

    try:
        for part in positions_str.split(","):
            part = part.strip()
            if not part:
                continue
            if is_alpha and part[0].isalpha():
                positions.append(display_to_pos(part, layout))
            elif "-" in part:
                start, end = part.split("-")
                positions.extend(range(int(start), int(end) + 1))
            else:
                positions.append(int(part))
    except Exception as e:
        raise ValueError(f"位置格式错误: {e}. 正确格式示例: '1,2,3' 或 '1-3'")

    for pos in positions:
        if not (lo <= pos <= hi):
            raise ValueError(f"位置 {pos} 超出范围（{lo}-{hi}）")

    return sorted(set(positions))


def format_chinese_date(date_str, weekday=False):
    """
    Convert YYYY-MM-DD to YYYY年MM月DD日

    Args:
        date_str: Date string in YYYY-MM-DD format
        weekday: If True, append weekday info

    Returns:
        str: Chinese formatted date
    """
    dt = parse_date(date_str)
    if not dt:
        return date_str
    base = f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"
    if weekday:
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        base += f" (周{weekdays[dt.weekday()]})"
    return base


def has_depletion_history(rec):
    """Return True if record has thaw/takeout/discard history.

    Fully consumed records are expected to end with ``positions=[]``.
    """
    thaw_events = rec.get("thaw_events") or []
    for ev in thaw_events:
        if normalize_action(ev.get("action")) in {"takeout", "thaw", "discard"}:
            return True

    return False


def _record_label(rec, idx):
    if idx is None:
        return f"记录(id={rec.get('id', 'N/A')})"
    return f"记录 #{idx + 1} (id={rec.get('id', 'N/A')})"


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
    from .custom_fields import get_required_field_keys

    errors = []
    warnings = []
    rec_id = _record_label(rec, idx)

    box_rule = _format_box_constraint(layout)
    pos_lo, pos_hi = get_position_range(layout) if layout else (POSITION_RANGE[0], POSITION_RANGE[1])

    # Structural required fields + user-defined required fields
    structural_required = ["id", "box", "positions", "frozen_at"]
    user_required = get_required_field_keys(meta)
    required_fields = structural_required + sorted(user_required)
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{rec_id}: 缺少必填字段 '{field}'")

    rec_id_value = rec.get("id")
    if not isinstance(rec_id_value, int) or rec_id_value <= 0:
        errors.append(f"{rec_id}: 'id' 必须是正整数")

    box = rec.get("box")
    if not isinstance(box, int):
        errors.append(f"{rec_id}: 'box' 必须是整数")
    elif not validate_box(box, layout):
        errors.append(f"{rec_id}: 'box' 超出范围 ({box_rule})")

    # Validate required user fields are non-empty strings
    for field in sorted(user_required):
        value = rec.get(field)
        if isinstance(value, str) and not value.strip():
            errors.append(f"{rec_id}: '{field}' 必须是非空字符串")

    positions = rec.get("positions")
    if not isinstance(positions, list):
        errors.append(f"{rec_id}: 'positions' 必须是列表")
    elif not positions:
        if not has_depletion_history(rec):
            errors.append(f"{rec_id}: 'positions' 为空，但没有取出/复苏/扔掉历史")
    else:
        if len(positions) > 1:
            errors.append(f"{rec_id}: 'positions' 最多只能包含 1 个位置（tube 为最小单元）")
        seen_positions = set()
        for pos in positions:
            if not isinstance(pos, int):
                errors.append(f"{rec_id}: 位置 {pos} 必须是整数")
                continue
            if not validate_position(pos, layout):
                errors.append(f"{rec_id}: 位置 {pos} 超出范围 ({pos_lo}-{pos_hi})")
                continue
            if pos in seen_positions:
                errors.append(f"{rec_id}: 'positions' 中存在重复值 {pos}")
            seen_positions.add(pos)

    frozen_at = rec.get("frozen_at")
    if not validate_date(frozen_at):
        errors.append(f"{rec_id}: 'frozen_at' 日期格式错误，应为 YYYY-MM-DD")
    else:
        frozen_date = parse_date(frozen_at)
        if frozen_date and frozen_date > datetime.now():
            errors.append(f"{rec_id}: 冻存日期 {frozen_at} 在未来")

    thaw_events = rec.get("thaw_events")
    if thaw_events is not None:
        if not isinstance(thaw_events, list):
            errors.append(f"{rec_id}: 'thaw_events' 必须是列表")
        else:
            for event_idx, ev in enumerate(thaw_events, 1):
                if not isinstance(ev, dict):
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] 必须是对象")
                    continue

                ev_action = normalize_action(ev.get("action"))
                if not ev_action:
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] action 非法")

                ev_date = ev.get("date")
                if not validate_date(ev_date):
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] date 格式错误")

                ev_positions = ev.get("positions")
                if isinstance(ev_positions, int):
                    ev_positions = [ev_positions]
                if not isinstance(ev_positions, list) or not ev_positions:
                    errors.append(f"{rec_id}: thaw_events[{event_idx}] positions 必须是非空列表")
                    continue

                seen_ev_pos = set()
                for ev_pos in ev_positions:
                    if not isinstance(ev_pos, int):
                        errors.append(f"{rec_id}: thaw_events[{event_idx}] 位置 {ev_pos} 必须是整数")
                        continue
                    if not validate_position(ev_pos, layout):
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] 位置 {ev_pos} 超出范围 ({pos_lo}-{pos_hi})"
                        )
                        continue
                    if ev_pos in seen_ev_pos:
                        errors.append(f"{rec_id}: thaw_events[{event_idx}] positions 中重复 {ev_pos}")
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
            errors.append(f"重复的 ID {rec_id}: 记录 #{prev_idx + 1} 和记录 #{idx + 1}")
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
        if box is None:
            continue
        for pos in rec.get("positions") or []:
            if isinstance(pos, int):
                usage[(int(box), int(pos))].append((idx, rec))

    conflicts = []
    for (box, pos), entries in usage.items():
        if len(entries) <= 1:
            continue
        rec_ids = ", ".join(f"#{idx + 1} (id={rec.get('id')})" for idx, rec in entries)
        conflicts.append(f"位置冲突: 盒子 {box} 位置 {pos} 被多条记录占用: {rec_ids}")
    return conflicts


def validate_inventory(data):
    """Validate full inventory document.

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    errors = []
    warnings = []

    if not isinstance(data, dict):
        return ["YAML 根节点必须是对象"], []

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return ["'inventory' 必须是列表"], []

    meta = data.get("meta", {})
    layout = meta.get("box_layout", {})

    for idx, rec in enumerate(inventory):
        if not isinstance(rec, dict):
            errors.append(f"记录 #{idx + 1}: 必须是对象")
            continue
        rec_errors, rec_warnings = validate_record(rec, idx=idx, layout=layout, meta=meta)
        errors.extend(rec_errors)
        warnings.extend(rec_warnings)

    errors.extend(check_duplicate_ids(inventory))
    errors.extend(check_position_conflicts(inventory))
    return errors, warnings


def format_validation_errors(errors, prefix="完整性校验失败"):
    """Format validation errors into a concise message."""
    if not errors:
        return prefix
    top = errors[:6]
    more = len(errors) - len(top)
    lines = [prefix] + [f"- {msg}" for msg in top]
    if more > 0:
        lines.append(f"- ... 以及另外 {more} 条")
    return "\n".join(lines)
