"""Shared dialog layout helpers for GUI presentation code."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QSpacerItem,
)


DEFAULT_DIALOG_MIN_WIDTH = 560
DEFAULT_DIALOG_TEXT_WIDTH = 640


def configure_message_box(
    box: QMessageBox,
    *,
    min_width: int = DEFAULT_DIALOG_MIN_WIDTH,
    text_width: int = DEFAULT_DIALOG_TEXT_WIDTH,
) -> QMessageBox:
    """Apply SnowFox's readable text layout defaults to a QMessageBox."""
    if hasattr(box, "setMinimumWidth"):
        box.setMinimumWidth(int(min_width))
    if hasattr(box, "setTextFormat"):
        box.setTextFormat(Qt.AutoText)

    find_children = getattr(box, "findChildren", None)
    if callable(find_children):
        for label in find_children(QLabel):
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
            if int(text_width) > 0:
                label.setMaximumWidth(int(text_width))
                label.setMinimumWidth(min(int(min_width) - 120, int(text_width)))

    layout_getter = getattr(box, "layout", None)
    layout = layout_getter() if callable(layout_getter) else None
    if layout is not None:
        spacer = QSpacerItem(
            int(min_width),
            0,
            QSizePolicy.Minimum,
            QSizePolicy.Expanding,
        )
        row_count = getattr(layout, "rowCount", lambda: 0)()
        column_count = max(1, getattr(layout, "columnCount", lambda: 1)())
        layout.addItem(spacer, row_count, 0, 1, column_count)
    return box


def create_message_box(
    parent,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    detailed_text: str | None = None,
    icon=QMessageBox.NoIcon,
    standard_buttons=None,
    default_button=None,
    min_width: int = DEFAULT_DIALOG_MIN_WIDTH,
    text_width: int = DEFAULT_DIALOG_TEXT_WIDTH,
    message_box_cls=QMessageBox,
) -> QMessageBox:
    box = message_box_cls(parent)
    if hasattr(box, "setWindowTitle"):
        box.setWindowTitle(str(title or ""))
    if hasattr(box, "setText"):
        box.setText(str(text or ""))
    if hasattr(box, "setIcon"):
        box.setIcon(icon)
    if informative_text and hasattr(box, "setInformativeText"):
        box.setInformativeText(str(informative_text))
    if detailed_text and hasattr(box, "setDetailedText"):
        box.setDetailedText(str(detailed_text))
    if standard_buttons is not None and hasattr(box, "setStandardButtons"):
        box.setStandardButtons(standard_buttons)
    if default_button is not None and hasattr(box, "setDefaultButton"):
        box.setDefaultButton(default_button)
    return configure_message_box(box, min_width=min_width, text_width=text_width)


def ask_yes_no(
    parent,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    detailed_text: str | None = None,
    icon=QMessageBox.Question,
    default_button=QMessageBox.No,
    yes_button=QMessageBox.Yes,
    message_box_cls=QMessageBox,
) -> bool:
    return ask_confirmation(
        parent,
        title=title,
        text=text,
        informative_text=informative_text,
        detailed_text=detailed_text,
        icon=icon,
        standard_buttons=QMessageBox.Yes | QMessageBox.No,
        accept_button=yes_button,
        default_button=default_button,
        message_box_cls=message_box_cls,
    )


def ask_confirmation(
    parent,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    detailed_text: str | None = None,
    icon=QMessageBox.Question,
    standard_buttons=QMessageBox.Yes | QMessageBox.No,
    accept_button=QMessageBox.Yes,
    default_button=QMessageBox.No,
    message_box_cls=QMessageBox,
) -> bool:
    box = create_message_box(
        parent,
        title=title,
        text=text,
        informative_text=informative_text,
        detailed_text=detailed_text,
        icon=icon,
        standard_buttons=standard_buttons,
        default_button=default_button,
        message_box_cls=message_box_cls,
    )
    return box.exec() == accept_button


def show_warning_message(
    parent,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    detailed_text: str | None = None,
    message_box_cls=QMessageBox,
) -> int:
    box = create_message_box(
        parent,
        title=title,
        text=text,
        informative_text=informative_text,
        detailed_text=detailed_text,
        icon=QMessageBox.Warning,
        standard_buttons=QMessageBox.Ok,
        default_button=QMessageBox.Ok,
        message_box_cls=message_box_cls,
    )
    return box.exec()


def show_info_message(
    parent,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    detailed_text: str | None = None,
    message_box_cls=QMessageBox,
) -> int:
    box = create_message_box(
        parent,
        title=title,
        text=text,
        informative_text=informative_text,
        detailed_text=detailed_text,
        icon=QMessageBox.Information,
        standard_buttons=QMessageBox.Ok,
        default_button=QMessageBox.Ok,
        message_box_cls=message_box_cls,
    )
    return box.exec()


def configure_dialog(
    dialog: QDialog,
    *,
    min_width: int = DEFAULT_DIALOG_MIN_WIDTH,
) -> QDialog:
    dialog.setMinimumWidth(int(min_width))
    return dialog


def create_wrapping_label(
    text: str = "",
    *,
    rich_text: bool = False,
    text_width: int = DEFAULT_DIALOG_TEXT_WIDTH,
) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.RichText if rich_text else Qt.AutoText)
    label.setText(str(text or ""))
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    if int(text_width) > 0:
        label.setMaximumWidth(int(text_width))
    return label
