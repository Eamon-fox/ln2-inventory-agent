"""
Shared utilities for the UI.
"""
import json

from app_gui.ui.theme import FONT_SIZE_MONO, FONT_SIZE_XS, FONT_SIZE_SM, FONT_SIZE_MD

# Keep this module importable without PySide6 so non-GUI unit tests can run.
try:
    from PySide6.QtCore import Qt  # type: ignore
except Exception:  # pragma: no cover
    Qt = None  # type: ignore


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


_COLOR_CYCLE = [
    "#4a90d9", "#e67e22", "#27ae60", "#8e44ad", "#2c3e50",
    "#e74c3c", "#16a085", "#d35400", "#2980b9", "#c0392b",
    "#1abc9c", "#f39c12", "#9b59b6", "#34495e", "#7f8c8d",
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
        return "#7f8c8d"
    if _dynamic_palette:
        return _dynamic_palette.get(value, "#7f8c8d")
    # Fallback: hash-based color from cycle
    idx = hash(value) % len(_COLOR_CYCLE)
    return _COLOR_CYCLE[idx]

def compact_json(value, max_chars=200):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = text.replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


class CollapsibleBox:
    _id_counter = 0

    @classmethod
    def _next_id(cls):
        cls._id_counter += 1
        return f"collapsible_{cls._id_counter}"

    @classmethod
    def render_html(cls, summary, content, is_dark=True, collapsed=True, max_preview_chars=100):
        box_id = cls._next_id()
        arrow = "&#9654;" if collapsed else "&#9660;"
        display = "none" if collapsed else "block"
        
        preview_text = content[:max_preview_chars] + "..." if len(content) > max_preview_chars else content
        preview_text = preview_text.replace('\n', ' ').strip()
        
        if is_dark:
            header_bg = "#242424"
            content_bg = "#1f1f1f"
            text_color = "#e8e8e8"
            muted_color = "#888888"
            accent_color = "#38bdf8"
            border_color = "rgba(255,255,255,0.08)"
        else:
            header_bg = "#f5f5f5"
            content_bg = "#fafafa"
            text_color = "#1e1e1e"
            muted_color = "#646464"
            accent_color = "#2563eb"
            border_color = "rgba(0,0,0,0.08)"

        escaped_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        html = f'''<div style="margin: 8px 0; background-color: {header_bg}; border: 1px solid {border_color}; border-radius: 6px; padding: 8px 12px;">
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
        <span style="font-size: {FONT_SIZE_MONO}px; color: {muted_color};">{arrow}</span>
        <span style="font-size: {FONT_SIZE_MD}px; color: {text_color}; font-weight: 500;">{summary}</span>
        <span style="font-size: {FONT_SIZE_XS}px; color: {accent_color};">({len(content)} chars)</span>
    </div>
    <div style="font-size: {FONT_SIZE_SM}px; color: {muted_color}; font-family: 'IBM Plex Mono', 'Consolas', monospace; white-space: pre-wrap; margin-top: 8px; padding: 8px; background-color: {content_bg}; border-radius: 4px;">{escaped_content}</div>
</div>'''
        return html
