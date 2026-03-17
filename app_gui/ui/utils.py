"""
Shared utilities for the UI.
"""
import json
import tempfile

import mistune

from app_gui.ui.theme import (
    FONT_SIZE_SM,
)


HELP_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: var(--background-raised);
        color: var(--text-weak);
        border: 1px solid var(--border-weak);
        border-radius: 10px;
        font-weight: 500;
        font-size: {FONT_SIZE_SM}px;
    }}
    QPushButton:hover {{
        background-color: var(--background-strong);
        border-color: var(--border-subtle);
    }}
"""


def positions_to_text(positions):
    if not positions:
        return ""
    # Sort positions and add space after each comma for readability
    return ", ".join(str(p) for p in sorted(positions))


# Low-saturation Morandi palette for overview grid cells to reduce eye strain.
_COLOR_CYCLE = [
    "#8FA4B3", "#B7A18A", "#8EA892", "#9C8FA8", "#7F8A93",
    "#B38D8A", "#7FA39C", "#A98F76", "#7D99A8", "#A07C7A",
    "#8DA8A2", "#B2A184", "#9C90A8", "#7E8790", "#8A949B",
]

_dynamic_palette = {}


def build_color_palette(options):
    """Build a color palette mapping from a list of option strings."""
    global _dynamic_palette
    _dynamic_palette = {}
    for i, opt in enumerate(options):
        _dynamic_palette[opt] = _COLOR_CYCLE[i % len(_COLOR_CYCLE)]


def cell_color(value):
    if not value:
        return "#8A949B"
    if _dynamic_palette:
        return _dynamic_palette.get(value, "#8A949B")
    # Fallback: hash-based color from cycle
    idx = hash(value) % len(_COLOR_CYCLE)
    return _COLOR_CYCLE[idx]

def md_to_html(text):
    """Convert markdown text to HTML suitable for Qt rich-text widgets."""
    if not text:
        return ""
    return mistune.html(text)


def compact_json(value, max_chars=200):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = text.replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def open_html_in_browser(html_text, suffix=".html", open_url_fn=None):
    """Write HTML text to a temporary file and open it with the system browser."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(str(html_text or ""))
        temp_path = f.name

    from PySide6.QtCore import QUrl  # type: ignore

    if open_url_fn is None:
        from PySide6.QtGui import QDesktopServices  # type: ignore

        open_url_fn = QDesktopServices.openUrl

    open_url_fn(QUrl.fromLocalFile(temp_path))
    return temp_path
