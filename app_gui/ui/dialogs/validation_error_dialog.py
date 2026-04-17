"""Dialog for surfacing structured validation errors from tool_api.

Consumes the ``errors_detail`` payload produced by
``lib.tool_api_support._validate_data_or_error`` (see
``docs/modules/13-库存核心.md`` 的「校验错误输出契约」). Each entry is a dict
with ``rule``/``field``/``record_id``/``box``/``position``/``value``/``expected``
keys plus a human-readable ``message`` fallback.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app_gui.i18n import tr


_COLUMN_KEYS = ("record_id", "location", "field", "value", "rule", "expected")


def _format_location(detail: Dict[str, Any]) -> str:
    box = detail.get("box")
    pos = detail.get("position")
    if box is not None and pos is not None:
        return f"Box {box} / Pos {pos}"
    if box is not None:
        return f"Box {box}"
    if pos is not None:
        return f"Pos {pos}"
    return ""


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _coerce_details(errors_detail: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not errors_detail:
        return []
    return [d for d in errors_detail if isinstance(d, dict)]


class ValidationErrorDialog(QDialog):
    """Modal dialog listing structured validation errors."""

    def __init__(
        self,
        parent=None,
        *,
        errors_detail: Optional[Iterable[Dict[str, Any]]] = None,
        summary_message: str = "",
    ):
        super().__init__(parent)
        self._details = _coerce_details(errors_detail)

        self.setWindowTitle(tr("operations.validationError.title"))
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)

        summary_text = summary_message or tr(
            "operations.validationError.summary",
            count=len(self._details),
        )
        summary_label = QLabel(summary_text)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        self.table = QTableWidget(len(self._details), len(_COLUMN_KEYS))
        self.table.setHorizontalHeaderLabels([
            tr("operations.validationError.columnRecordId"),
            tr("operations.validationError.columnLocation"),
            tr("operations.validationError.columnField"),
            tr("operations.validationError.columnValue"),
            tr("operations.validationError.columnRule"),
            tr("operations.validationError.columnExpected"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)

        for row, detail in enumerate(self._details):
            cells = [
                _format_value(detail.get("record_id")),
                _format_location(detail),
                _format_value(detail.get("field")),
                _format_value(detail.get("value")),
                _format_value(detail.get("rule")),
                _format_value(detail.get("expected")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(str(detail.get("message") or text))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)

        button_box = QDialogButtonBox()
        copy_btn = button_box.addButton(
            tr("operations.validationError.copy"),
            QDialogButtonBox.ActionRole,
        )
        copy_btn.clicked.connect(self._copy_to_clipboard)
        button_box.addButton(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def _copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        lines = []
        for detail in self._details:
            parts = [
                f"id={detail.get('record_id')}" if detail.get("record_id") is not None else "",
                _format_location(detail),
                f"field={detail.get('field')}" if detail.get("field") else "",
                f"rule={detail.get('rule')}" if detail.get("rule") else "",
            ]
            header = " | ".join(p for p in parts if p)
            message = str(detail.get("message") or "")
            lines.append(f"{header}\n  {message}" if header else message)
        clipboard.setText("\n".join(lines))


def show_validation_error_dialog(
    parent,
    *,
    errors_detail: Optional[Iterable[Dict[str, Any]]],
    summary_message: str = "",
) -> None:
    """Open the dialog; no-op when ``errors_detail`` is empty."""
    details = _coerce_details(errors_detail)
    if not details:
        return
    dialog = ValidationErrorDialog(
        parent,
        errors_detail=details,
        summary_message=summary_message,
    )
    dialog.exec()
