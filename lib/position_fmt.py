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
    display = str(display).strip()
    if _indexing(layout) == "alphanumeric" and display and display[0].isalpha():
        letter = display[0].upper()
        row = _LETTERS.index(letter)
        col = int(display[1:]) - 1
        cols = _cols(layout)
        if col < 0 or col >= cols:
            raise ValueError(f"Column out of range: {display}")
        if row < 0 or row >= _rows(layout):
            raise ValueError(f"Row out of range: {display}")
        return row * cols + col + 1
    return int(display)


# ---------------------------------------------------------------------------
# Box conversion
# ---------------------------------------------------------------------------

def box_to_display(box, layout=None):
    """Convert box number to display label."""
    labels = (layout or {}).get("box_labels")
    if labels and isinstance(labels, list):
        idx = int(box) - 1
        if 0 <= idx < len(labels):
            return str(labels[idx])
    return str(box)


def display_to_box(display, layout=None):
    """Convert display label to box number."""
    labels = (layout or {}).get("box_labels")
    if labels and isinstance(labels, list):
        display_str = str(display).strip()
        for i, label in enumerate(labels):
            if str(label) == display_str:
                return i + 1
    return int(display)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def get_box_count(layout=None):
    """Return number of boxes from layout, falling back to BOX_RANGE."""
    layout = layout or {}
    bc = layout.get("box_count")
    if bc is not None:
        return int(bc)
    return BOX_RANGE[1] - BOX_RANGE[0] + 1


def get_total_slots(layout=None):
    """Return total positions per box (rows * cols)."""
    return _rows(layout) * _cols(layout)


def get_position_range(layout=None):
    """Return (min_pos, max_pos) derived from layout."""
    return (1, get_total_slots(layout))
