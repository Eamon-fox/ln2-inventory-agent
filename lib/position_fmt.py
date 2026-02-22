"""Bidirectional conversion between internal 1-based integer positions and display strings.

Internal model: positions are always 1-based integers stored in YAML.
Display layer converts to/from human-readable formats based on ``layout["indexing"]``.

Supported indexing modes:
  - ``"numeric"`` (default): "1", "2", ..., "81"
  - ``"alphanumeric"``: "A1", "A2", ..., "I9" (row letter + 1-based col number)
"""

from lib.config import BOX_RANGE

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _cols(layout):
    return int((layout or {}).get("cols", 9))


def _rows(layout):
    return int((layout or {}).get("rows", 9))


def _indexing(layout):
    return str((layout or {}).get("indexing", "numeric")).lower()


# ---------------------------------------------------------------------------
# Position conversion
# ---------------------------------------------------------------------------

def pos_to_display(pos, layout=None):
    """Convert internal 1-based integer position to display string."""
    if _indexing(layout) == "alphanumeric":
        cols = _cols(layout)
        row = (pos - 1) // cols
        col = (pos - 1) % cols
        if row < len(_LETTERS):
            return f"{_LETTERS[row]}{col + 1}"
    return str(pos)


def display_to_pos(display, layout=None):
    """Convert display string to internal 1-based integer position.

    Raises ``ValueError`` on invalid input.
    """
    if isinstance(display, int) and not isinstance(display, bool):
        return int(display)

    text = str(display).strip()
    if not text:
        raise ValueError("Position cannot be empty")

    indexing = _indexing(layout)
    if indexing == "alphanumeric":
        if not text[0].isalpha():
            raise ValueError(f"Position must use alphanumeric format like A1: {text}")

        letter = text[0].upper()
        if letter not in _LETTERS:
            raise ValueError(f"Invalid row letter: {text}")

        suffix = text[1:]
        if not suffix.isdigit():
            raise ValueError(f"Invalid alphanumeric position: {text}")

        row = _LETTERS.index(letter)
        col = int(suffix) - 1
        cols = _cols(layout)
        if col < 0 or col >= cols:
            raise ValueError(f"Column out of range: {text}")
        if row < 0 or row >= _rows(layout):
            raise ValueError(f"Row out of range: {text}")
        return row * cols + col + 1

    if text[0].isalpha():
        raise ValueError(f"Position must be numeric like 1: {text}")
    return int(text)


# ---------------------------------------------------------------------------
# Box conversion
# ---------------------------------------------------------------------------

def box_to_display(box, layout=None):
    """Convert box number to display label."""
    labels = (layout or {}).get("box_labels")
    if labels and isinstance(labels, list):
        try:
            box_num = int(box)
        except Exception:
            box_num = None
        if box_num is not None:
            numbers = get_box_numbers(layout)
            if box_num in numbers:
                idx = numbers.index(box_num)
                if 0 <= idx < len(labels):
                    return str(labels[idx])
    return str(box)


def display_to_box(display, layout=None):
    """Convert display label to box number."""
    labels = (layout or {}).get("box_labels")
    if labels and isinstance(labels, list):
        numbers = get_box_numbers(layout)
        display_str = str(display).strip()
        for i, label in enumerate(labels):
            if str(label) == display_str and i < len(numbers):
                return numbers[i]
    return int(display)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def get_box_numbers(layout=None):
    """Return active box numbers from layout.

    Backward compatibility:
    - If ``box_numbers`` is present, it is treated as source of truth.
    - Otherwise, fall back to contiguous ``1..box_count``.
    - If ``box_count`` is absent, fall back to configured ``BOX_RANGE``.
    """
    layout = layout or {}

    raw_numbers = layout.get("box_numbers")
    if isinstance(raw_numbers, (list, tuple)):
        seen = set()
        normalized = []
        for value in raw_numbers:
            try:
                num = int(value)
            except Exception:
                continue
            if num < 1 or num in seen:
                continue
            seen.add(num)
            normalized.append(num)
        normalized.sort()
        if normalized:
            return normalized

    bc = layout.get("box_count")
    if bc is not None:
        try:
            count = int(bc)
        except Exception:
            count = 0
        if count > 0:
            return list(range(1, count + 1))
        return []

    lo, hi = BOX_RANGE
    return list(range(int(lo), int(hi) + 1))


def get_box_count(layout=None):
    """Return number of active boxes from layout."""
    return len(get_box_numbers(layout))


def get_total_slots(layout=None):
    """Return total positions per box (rows * cols)."""
    return _rows(layout) * _cols(layout)


def get_position_range(layout=None):
    """Return (min_pos, max_pos) derived from layout."""
    return (1, get_total_slots(layout))
