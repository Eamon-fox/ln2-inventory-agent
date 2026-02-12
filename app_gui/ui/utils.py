"""
Shared utilities for the UI.
"""
import json

# Keep this module importable without PySide6 so non-GUI unit tests can run.
try:
    from PySide6.QtCore import Qt  # type: ignore
except Exception:  # pragma: no cover
    Qt = None  # type: ignore


HELP_BUTTON_STYLE = """
    QPushButton {
        background-color: var(--background-raised);
        color: var(--text-weak);
        border: 1px solid var(--border-weak);
        border-radius: 10px;
        font-weight: 500;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #383838;
        border-color: var(--border-subtle);
    }
"""


def positions_to_text(positions):
    if not positions:
        return ""
    # Sort positions and add space after each comma for readability
    return ", ".join(str(p) for p in sorted(positions))


def cell_color(parent_cell_line):
    palette = {
        "NCCIT": "#4a90d9",
        "K562": "#e67e22",
        "HeLa": "#27ae60",
        "HEK293T": "#8e44ad",
        "NCCIT Des-MCP-APEX2": "#2c3e50",
    }
    return palette.get(parent_cell_line, "#7f8c8d")

def compact_json(value, max_chars=200):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = text.replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def build_panel_header(parent, title, help_title, help_text):
    """Create a standard panel header row with title and help button."""
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton
    from PySide6.QtCore import Qt as _Qt

    header_row = QHBoxLayout()
    header_row.setSpacing(8)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: 500; font-size: 14px; color: var(--text-strong);")
    header_row.addWidget(title_label)

    help_btn = QPushButton("?")
    help_btn.setFixedSize(18, 18)
    help_btn.setStyleSheet("""
        QPushButton {
            background-color: transparent;
            color: var(--text-weak);
            border: none;
            font-weight: 500;
            font-size: 12px;
            padding: 0;
        }
        QPushButton:hover {
            color: var(--accent);
        }
    """)
    help_btn.setCursor(_Qt.PointingHandCursor)
    help_btn.clicked.connect(lambda: QMessageBox.information(parent, help_title, help_text))
    header_row.addWidget(help_btn)
    header_row.addStretch()
    return header_row


class CollapsibleBox:
    _id_counter = 0

    @classmethod
    def _next_id(cls):
        cls._id_counter += 1
        return f"collapsible_{cls._id_counter}"

    @classmethod
    def render_html(cls, summary, content, is_dark=True, collapsed=True, max_preview_chars=100):
        box_id = cls._next_id()
        arrow = "▶" if collapsed else "▼"
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
        <span style="font-size: 10px; color: {muted_color};">{arrow}</span>
        <span style="font-size: 13px; color: {text_color}; font-weight: 500;">{summary}</span>
        <span style="font-size: 11px; color: {accent_color};">({len(content)} chars)</span>
    </div>
    <div style="font-size: 12px; color: {muted_color}; font-family: 'IBM Plex Mono', 'Consolas', monospace; white-space: pre-wrap; margin-top: 8px; padding: 8px; background-color: {content_bg}; border-radius: 4px;">{escaped_content}</div>
</div>'''
        return html
