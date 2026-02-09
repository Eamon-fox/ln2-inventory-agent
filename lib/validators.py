"""
Validation functions for LN2 inventory data
"""
from collections import defaultdict
from datetime import datetime
from .config import BOX_RANGE, POSITION_RANGE, VALID_ACTIONS
from .thaw_parser import normalize_action


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


def validate_box(box):
    """
    Validate box number is in valid range

    Args:
        box: Box number to validate

    Returns:
        bool: True if valid, False otherwise
    """
    return BOX_RANGE[0] <= box <= BOX_RANGE[1]


def validate_position(pos):
    """
    Validate position number is in valid range

    Args:
        pos: Position number to validate

    Returns:
        bool: True if valid, False otherwise
    """
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


def parse_positions(positions_str):
    """
    Parse position list: "1,2,3" or "1-3"

    Args:
        positions_str: Position string to parse

    Returns:
        list: Sorted list of unique positions

    Raises:
        ValueError: If format is invalid or positions out of range
    """
    positions = []
    try:
        for part in positions_str.split(","):
            part = part.strip()
            if "-" in part:
                # Handle range "1-3"
                start, end = part.split("-")
                positions.extend(range(int(start), int(end) + 1))
            else:
                positions.append(int(part))
    except Exception as e:
        raise ValueError(f"位置格式错误: {e}. 正确格式示例: '1,2,3' 或 '1-3'")

    # Validate position range
    for pos in positions:
        if not validate_position(pos):
            raise ValueError(f"位置 {pos} 超出范围（{POSITION_RANGE[0]}-{POSITION_RANGE[1]}）")

    return sorted(set(positions))  # Remove duplicates and sort


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

    # Backward compatibility for legacy free-text logs.
    thaw_log = rec.get("thaw_log")
    return bool(thaw_log and str(thaw_log).strip())


def _record_label(rec, idx):
    if idx is None:
        return f"记录(id={rec.get('id', 'N/A')})"
    return f"记录 #{idx + 1} (id={rec.get('id', 'N/A')})"


def validate_record(rec, idx=None):
    """Validate one inventory record.

    Returns:
        tuple[list[str], list[str]]: (errors, warnings)
    """
    errors = []
    warnings = []
    rec_id = _record_label(rec, idx)

    required_fields = ["id", "parent_cell_line", "short_name", "box", "positions", "frozen_at"]
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{rec_id}: 缺少必填字段 '{field}'")

    rec_id_value = rec.get("id")
    if not isinstance(rec_id_value, int) or rec_id_value <= 0:
        errors.append(f"{rec_id}: 'id' 必须是正整数")

    box = rec.get("box")
    if not isinstance(box, int):
        errors.append(f"{rec_id}: 'box' 必须是整数")
    elif not validate_box(box):
        errors.append(f"{rec_id}: 'box' 超出范围 ({BOX_RANGE[0]}-{BOX_RANGE[1]})")

    for field in ["parent_cell_line", "short_name"]:
        value = rec.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{rec_id}: '{field}' 必须是非空字符串")

    positions = rec.get("positions")
    if not isinstance(positions, list):
        errors.append(f"{rec_id}: 'positions' 必须是列表")
    elif not positions:
        if not has_depletion_history(rec):
            errors.append(f"{rec_id}: 'positions' 为空，但没有取出/复苏/扔掉历史")
    else:
        seen_positions = set()
        for pos in positions:
            if not isinstance(pos, int):
                errors.append(f"{rec_id}: 位置 {pos} 必须是整数")
                continue
            if not validate_position(pos):
                errors.append(f"{rec_id}: 位置 {pos} 超出范围 ({POSITION_RANGE[0]}-{POSITION_RANGE[1]})")
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
                    if not validate_position(ev_pos):
                        errors.append(
                            f"{rec_id}: thaw_events[{event_idx}] 位置 {ev_pos} 超出范围 ({POSITION_RANGE[0]}-{POSITION_RANGE[1]})"
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

    for idx, rec in enumerate(inventory):
        if not isinstance(rec, dict):
            errors.append(f"记录 #{idx + 1}: 必须是对象")
            continue
        rec_errors, rec_warnings = validate_record(rec, idx=idx)
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
