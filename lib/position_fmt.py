"""Bidirectional conversion between internal 1-based integer positions and display strings.

Internal model: positions are always 1-based integers stored in YAML.
Display layer converts to/from human-readable formats based on ``layout["indexing"]``.

Supported indexing modes:
  - ``"numeric"`` (default): "1", "2", ..., "81"
  - ``"alphanumeric"``: "A1", "A2", ..., "I9" (row letter + 1-based col number)
"""

from lib.config import BOX_RANGE

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BOX_LAYOUT_INDEXING_VALUES = ("numeric", "alphanumeric")
DEFAULT_BOX_LAYOUT_INDEXING = "numeric"


def _cols(layout):
    return int((layout or {}).get("cols", 9))


def _rows(layout):
    return int((layout or {}).get("rows", 9))


def _indexing(layout):
    return normalize_box_layout_indexing((layout or {}).get("indexing"))


def normalize_box_layout_indexing(value, *, default=DEFAULT_BOX_LAYOUT_INDEXING):
    text = str(value or "").strip().lower()
    if text in BOX_LAYOUT_INDEXING_VALUES:
        return text
    return default


def is_valid_box_layout_indexing(value):
    text = str(value or "").strip().lower()
    return text in BOX_LAYOUT_INDEXING_VALUES


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


def box_tag_text(box, layout=None):
    """Return the optional per-box tag stored in ``box_tags``.

    The stored field name remains ``meta.box_layout.box_tags`` for backward
    compatibility, but the semantic role is display-only and never identity.
    """
    box_tags = (layout or {}).get("box_tags")
    if not isinstance(box_tags, dict):
        return ""

    raw_value = box_tags.get(str(box))
    if raw_value is None:
        return ""

    text = str(raw_value)
    if "\n" in text or "\r" in text:
        text = text.replace("\r", " ").replace("\n", " ")
    return text.strip()


def box_identity_label(box, layout=None):
    """Return stable numeric box identity with optional tag suffix."""
    try:
        box_num = int(box)
        base = str(box_num)
    except Exception:
        box_num = None
        base = str(box)

    if box_num is None:
        return base

    tag_text = box_tag_text(box_num, layout)
    if not tag_text:
        return base
    return f"{base} ({tag_text})"


def format_box_position_display(
    box,
    position,
    *,
    layout=None,
    box_label="Box",
    position_label="Position",
):
    """Return a stable identity-first box/position display string."""
    box_text = "?" if box in (None, "") else box_identity_label(box, layout)
    if position in (None, ""):
        pos_text = "?"
    else:
        try:
            pos_text = pos_to_display(int(position), layout)
        except Exception:
            pos_text = str(position)
    return f"{box_label} {box_text} {position_label} {pos_text}"


def format_box_positions_display(
    box,
    positions,
    *,
    layout=None,
    box_label="Box",
    positions_label="Positions",
):
    """Return a stable identity-first box/multi-position display string."""
    box_text = "?" if box in (None, "") else box_identity_label(box, layout)
    normalized_positions = []
    for raw_position in list(positions or []):
        try:
            normalized_positions.append(pos_to_display(int(raw_position), layout))
        except Exception:
            normalized_positions.append(str(raw_position))

    if not normalized_positions:
        positions_text = "?"
    else:
        positions_text = f"[{', '.join(normalized_positions)}]"
    return f"{box_label} {box_text} {positions_label} {positions_text}"


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
