from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QHBoxLayout, QWidget


def _tooltip_html(text: str) -> str:
    escaped = escape(str(text or "").strip()).replace("\n", "<br>")
    return f"<div style='white-space: normal; max-width: 420px;'>{escaped}</div>"


def info_label(label_text: str, tooltip_text: str) -> QWidget | str:
    tooltip = str(tooltip_text or "").strip()
    if not tooltip:
        return label_text

    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    label = QLabel(str(label_text or ""))
    layout.addWidget(label, 0, Qt.AlignVCenter)

    info = QLabel("i")
    info.setObjectName("settingsInlineInfoLabel")
    info.setAlignment(Qt.AlignCenter)
    info.setFixedSize(12, 12)
    info.setToolTip(_tooltip_html(tooltip))
    info.setAccessibleName(tooltip)
    info.setStyleSheet(
        "#settingsInlineInfoLabel {"
        "border: 1px solid rgba(127, 127, 127, 150);"
        "border-radius: 6px;"
        "font-size: 8px;"
        "font-weight: 600;"
        "color: rgba(127, 127, 127, 220);"
        "background: transparent;"
        "}"
    )
    layout.addWidget(info, 0, Qt.AlignTop)
    layout.addStretch(1)

    return widget
