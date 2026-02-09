"""
Validation functions for LN2 inventory data
"""
from datetime import datetime
from .config import BOX_RANGE, POSITION_RANGE, VALID_ACTIONS


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
    except ValueError:
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
