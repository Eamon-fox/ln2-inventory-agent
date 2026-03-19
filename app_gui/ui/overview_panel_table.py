"""Table-view and prefill helpers for OverviewPanel."""

from contextlib import suppress

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem

from app_gui.i18n import t
from app_gui.ui.theme import pick_contrasting_text_color
from app_gui.ui.utils import cell_color
from lib.csv_export import build_export_rows
from lib.validators import parse_date


class _SortableOverviewItem(QTableWidgetItem):
    """QTableWidgetItem with explicit typed sort keys for Overview tables."""

    def __init__(self, text, *, sort_key=None):
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other):
        if not isinstance(other, _SortableOverviewItem):
            return super().__lt__(other)

        self_key = self._sort_key
        other_key = other._sort_key
        if self_key is not None and other_key is not None:
            try:
                if self_key != other_key:
                    return self_key < other_key
            except TypeError:
                pass
        elif self_key is not None:
            return True
        elif other_key is not None:
            return False

        return super().__lt__(other)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_number(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    with suppress(TypeError, ValueError):
        return int(text)
    with suppress(TypeError, ValueError):
        return float(text)
    return None


def _location_sort_key(row_data, value):
    record = row_data.get("record")
    if isinstance(record, dict):
        box = _safe_int(record.get("box"))
        position = _safe_int(record.get("position"))
        if box is not None and position is not None:
            return (box, position)

    parts = str(value or "").split(":")
    if len(parts) != 2:
        return None

    box = _safe_int(parts[0])
    position = _safe_int(parts[1])
    if box is None or position is None:
        return None
    return (box, position)


def _column_sort_key(column, value, row_data, *, column_type):
    if column == "location":
        return _location_sort_key(row_data, value)
    if column == "id":
        return _safe_number(value)
    if column_type == "number":
        return _safe_number(value)
    if column_type == "date":
        return parse_date(value)
    return None


def _set_table_columns(self, headers):
    self.ov_table.setRowCount(0)
    self.ov_table.setColumnCount(len(headers))
    self.ov_table.setHorizontalHeaderLabels(headers)
    header = self.ov_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionsMovable(False)
    header.setSectionsClickable(True)
    self.ov_table.setSortingEnabled(False)

    default_widths = {
        "id": 60,
        "location": 80,
        "frozen_at": 100,
        "thaw_events": 200,
        "cell_line": 100,
        "note": 180,
        "short_name": 150,
    }
    for idx, col_name in enumerate(headers):
        if col_name in default_widths:
            self.ov_table.setColumnWidth(idx, default_widths[col_name])
        else:
            self.ov_table.setColumnWidth(idx, 120)


def _rebuild_table_rows(self, records):
    meta = getattr(self, "_current_meta", {})
    from lib.custom_fields import get_color_key

    payload = build_export_rows(records or [], meta=meta)
    self._table_columns = list(payload.get("columns") or [])

    color_key = get_color_key(meta, inventory=records or [])
    rows = []
    for values in payload.get("rows") or []:
        rid_raw = values.get("id")
        record = None
        if rid_raw not in (None, ""):
            try:
                record = self.overview_records_by_id.get(int(rid_raw))
            except (TypeError, ValueError):
                record = None

        box_number = None
        if isinstance(record, dict):
            with suppress(TypeError, ValueError):
                box_number = int(record.get("box"))

        color_value = ""
        if isinstance(record, dict):
            color_value = str(record.get(color_key) or "")
        elif color_key in values:
            color_value = str(values.get(color_key) or "")

        search_text = " ".join(str(values.get(col, "")) for col in self._table_columns).lower()
        rows.append(
            {
                "values": values,
                "record": record,
                "box": box_number,
                "color_value": color_value,
                "search_text": search_text,
            }
        )

    self._table_rows = rows
    self._set_table_columns(self._table_columns)
    self._table_row_records = []
    self._table_version = int(getattr(self, "_table_version", 0) or 0) + 1
    unique_cache = getattr(self, "_column_unique_cache", None)
    if isinstance(unique_cache, dict):
        unique_cache.clear()
    else:
        self._column_unique_cache = {}


def _render_table_rows(self, rows):
    rows_list = list(rows or [])
    self.ov_table.setSortingEnabled(False)
    updates_enabled = bool(self.ov_table.updatesEnabled())
    self.ov_table.setUpdatesEnabled(False)

    RECORD_ROLE = Qt.UserRole + 100

    from app_gui.ui import overview_panel as _ov_panel

    try:
        self.ov_table.setRowCount(len(rows_list))
        self._table_row_records = [None] * len(rows_list)
        column_type_map = {}
        for column in self._table_columns:
            if column == "location":
                column_type_map[column] = "location"
            elif column == "id":
                column_type_map[column] = "number"
            else:
                column_type_map[column] = self._detect_column_type(column)

        for row_index, row_data in enumerate(rows_list):
            values = row_data.get("values") or {}
            color_value = str(row_data.get("color_value") or "")
            row_tint = cell_color(color_value or None)
            row_text_brush = QBrush(QColor(pick_contrasting_text_color(row_tint)))
            record = row_data.get("record")
            self._table_row_records[row_index] = record

            for col_index, column in enumerate(self._table_columns):
                value = values.get(column, "")
                item = _SortableOverviewItem(
                    str(value),
                    sort_key=_column_sort_key(
                        column,
                        value,
                        row_data,
                        column_type=column_type_map.get(column),
                    ),
                )
                item.setData(_ov_panel.TABLE_ROW_TINT_ROLE, row_tint)
                item.setForeground(row_text_brush)

                if col_index == 0:
                    item.setData(RECORD_ROLE, record)

                if column == "id":
                    with suppress(ValueError, TypeError):
                        item.setData(Qt.UserRole, int(value))
                elif column == "location":
                    try:
                        parts = str(value).split(":")
                        if len(parts) == 2:
                            box, pos = int(parts[0]), int(parts[1])
                            item.setData(Qt.UserRole, box * 1000 + pos)
                    except (ValueError, TypeError):
                        pass

                self.ov_table.setItem(row_index, col_index, item)
    finally:
        self.ov_table.setUpdatesEnabled(updates_enabled)
        self.ov_table.setSortingEnabled(True)


def on_table_row_double_clicked(self, row, _col):
    if row < 0 or row >= self.ov_table.rowCount():
        return

    RECORD_ROLE = Qt.UserRole + 100
    first_item = self.ov_table.item(row, 0)
    if not first_item:
        return

    record = first_item.data(RECORD_ROLE)
    if not isinstance(record, dict):
        return

    position = record.get("position")
    if position is None:
        return

    try:
        record_id = int(record.get("id"))
        box_num = int(record.get("box"))
        position = int(position)
    except (TypeError, ValueError):
        return

    self._set_selected_cell(box_num, position)
    self._emit_takeout_prefill_background(box_num, position, record_id)


def _emit_takeout_prefill_background(self, box_num, position, record_id):
    payload = {
        "box": int(box_num),
        "position": int(position),
        "record_id": int(record_id),
    }
    self.request_prefill_background.emit(payload)
    self.status_message.emit(t("overview.prefillTakeoutAuto", id=payload["record_id"]), 2000)


def _emit_add_prefill_background(self, box_num, position):
    payload = {
        "box": int(box_num),
        "position": int(position),
    }
    self.request_add_prefill_background.emit(payload)
    self.status_message.emit(
        t("overview.prefillAddAuto", box=payload["box"], position=payload["position"]),
        2000,
    )


def _emit_add_prefill(self, box_num, position):
    payload = {
        "box": int(box_num),
        "position": int(position),
    }
    self.request_add_prefill.emit(payload)
    self.status_message.emit(
        t("overview.prefillAdd", box=payload["box"], position=payload["position"]),
        2000,
    )
