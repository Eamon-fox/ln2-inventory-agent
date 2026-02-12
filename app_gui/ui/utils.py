"""
Shared utilities for the UI.
"""
import json


HELP_BUTTON_STYLE = """
    QPushButton {
        background-color: #3b82f6;
        color: white;
        border: none;
        border-radius: 10px;
        font-weight: bold;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #2563eb;
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

    header_row = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
    header_row.addWidget(title_label)
    header_row.addStretch()

    help_btn = QPushButton("?")
    help_btn.setFixedSize(20, 20)
    help_btn.setStyleSheet(HELP_BUTTON_STYLE)
    help_btn.clicked.connect(lambda: QMessageBox.information(parent, help_title, help_text))
    header_row.addWidget(help_btn)
    return header_row
