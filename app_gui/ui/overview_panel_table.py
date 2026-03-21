"""Table-view and prefill helpers for OverviewPanel."""

from contextlib import suppress

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem

from app_gui.i18n import t, tr
from app_gui.ui.theme import pick_contrasting_text_color
from app_gui.ui.utils import cell_color
from lib.position_fmt import format_box_position_display, pos_to_display
from lib.validators import parse_date


class _SortableOverviewItem(QTableWidgetItem):
    """QTableWidgetItem with explicit typed sort keys for Overview tables."""

    def __init__(self, text, *, sort_key=None):
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other):
        try:
            self_key = getattr(self, "_sort_key", None)
            other_key = getattr(other, "_sort_key", None) if isinstance(other, _SortableOverviewItem) else None

            if self_key is not None and other_key is not None:
                try:
                    if self_key != other_key:
                        return self_key < other_key
                except Exception:
                    pass
            elif self_key is not None:
                return True
            elif other_key is not None:
                return False

            return _item_display_sort_value(self) < _item_display_sort_value(other)
        except Exception:
            # Never let Python exceptions propagate back into Qt's native sorter.
            return False


_OVERVIEW_TABLE_COLUMN_LABEL_KEYS = {
    "frozen_at": "operations.colFrozenAt",
    "stored_at": "operations.colFrozenAt",
    "thaw_events": "operations.colStorageEvents",
    "storage_events": "operations.colStorageEvents",
}


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


def _text_sort_key(value):
    text = str(value or "").strip()
    if not text:
        return None
    return text.casefold()


def _item_display_sort_value(item):
    try:
        text = str(item.text() or "").strip()
    except Exception:
        text = ""
    if not text:
        return (1, "")
    return (0, text.casefold())


def _location_sort_key(row_data, value):
    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is not None and position is not None:
        return (box, position)

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
    return _text_sort_key(value)


def display_table_column_label(column_name):
    key = _OVERVIEW_TABLE_COLUMN_LABEL_KEYS.get(str(column_name or "").strip())
    if not key:
        return str(column_name or "")
    return tr(key, default=str(column_name or ""))


def _resolve_table_header_labels(self, columns):
    from lib.custom_fields import get_effective_fields

    meta = getattr(self, "_current_meta", {}) or {}
    inventory = getattr(self, "_current_records", []) or []
    field_labels = {}
    for field_def in get_effective_fields(meta, inventory=inventory):
        if not isinstance(field_def, dict):
            continue
        key = str(field_def.get("key") or "").strip()
        if not key:
            continue
        field_labels[key] = str(field_def.get("label") or key)

    return {
        str(column or ""): field_labels.get(str(column or ""), display_table_column_label(column))
        for column in list(columns or [])
    }


def _set_table_columns(self, headers, *, header_labels=None):
    raw_columns = [str(header or "") for header in list(headers or [])]
    resolved_labels = dict(header_labels or _resolve_table_header_labels(self, raw_columns))

    self.ov_table.setRowCount(0)
    self.ov_table.setColumnCount(len(raw_columns))
    self._table_header_labels = dict(resolved_labels)
    for idx, col_name in enumerate(raw_columns):
        header_item = QTableWidgetItem(str(resolved_labels.get(col_name, col_name)))
        header_item.setData(Qt.UserRole, col_name)
        self.ov_table.setHorizontalHeaderItem(idx, header_item)
    header = self.ov_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionsMovable(False)
    header.setSectionsClickable(True)
    self.ov_table.setSortingEnabled(False)

    default_widths = {
        "id": 60,
        "location": 220,
        "frozen_at": 100,
        "stored_at": 100,
        "thaw_events": 200,
        "storage_events": 200,
        "cell_line": 100,
        "note": 180,
        "short_name": 150,
    }
    for idx, col_name in enumerate(raw_columns):
        if col_name in default_widths:
            self.ov_table.setColumnWidth(idx, default_widths[col_name])
        else:
            self.ov_table.setColumnWidth(idx, 120)


def _format_location_value(self, row_data, fallback_value):
    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is None or position is None:
        return str(fallback_value or "")

    return format_box_position_display(
        box,
        position,
        layout=getattr(self, "_current_layout", {}) or {},
        box_label=tr("operations.box", default="Box"),
        position_label=tr("operations.position", default="Position"),
    )


def _table_query_payload(self, *, keyword, selected_box, selected_cell):
    return {
        "keyword": keyword,
        "box": selected_box,
        "color_value": selected_cell,
        "include_inactive": bool(getattr(self, "_table_include_inactive", False)),
        "column_filters": dict(getattr(self, "_column_filters", {}) or {}),
        "sort_by": str(getattr(self, "_table_sort_by", "location") or "location"),
        "sort_order": str(getattr(self, "_table_sort_order", "asc") or "asc"),
        "limit": None,
        "offset": 0,
    }


def _query_table_rows(self, *, keyword, selected_box, selected_cell):
    payload = _table_query_payload(
        self,
        keyword=keyword,
        selected_box=selected_box,
        selected_cell=selected_cell,
    )
    yaml_path = self.yaml_path_getter()
    filter_records = getattr(self.bridge, "filter_records", None)
    if not callable(filter_records):
        return {
            "ok": False,
            "message": "OverviewPanel bridge must provide filter_records()",
        }
    return filter_records(yaml_path=yaml_path, **payload)


def _sync_table_sort_indicator(self):
    header = getattr(self, "ov_table_header", None)
    columns = list(getattr(self, "_table_columns", []) or [])
    if header is None or not columns:
        return

    sort_by = str(getattr(self, "_table_sort_by", "location") or "location")
    if sort_by not in columns:
        sort_by = "location" if "location" in columns else columns[0]
        self._table_sort_by = sort_by

    sort_order = str(getattr(self, "_table_sort_order", "asc") or "asc").lower()
    qt_order = Qt.DescendingOrder if sort_order == "desc" else Qt.AscendingOrder
    section_index = columns.index(sort_by)

    self._ignore_table_sort_change = True
    try:
        header.setSortIndicatorShown(True)
        header.setSortIndicator(section_index, qt_order)
    finally:
        self._ignore_table_sort_change = False


def _on_table_sort_changed(self, logical_index, order):
    if bool(getattr(self, "_ignore_table_sort_change", False)):
        return
    columns = list(getattr(self, "_table_columns", []) or [])
    if logical_index < 0 or logical_index >= len(columns):
        return

    self._table_sort_by = str(columns[logical_index] or "location")
    self._table_sort_order = "desc" if order == Qt.DescendingOrder else "asc"
    # Header clicks already trigger Qt's in-place table sort. Rebuilding rows
    # synchronously from this signal can invalidate items while the native sort
    # stack is still active and crash the process.


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
        column_type_map = dict(getattr(self, "_table_column_types", {}) or {})
        for column in self._table_columns:
            if column not in column_type_map:
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
            if not isinstance(record, dict):
                record_id = row_data.get("record_id")
                if record_id not in (None, ""):
                    with suppress(TypeError, ValueError):
                        record = self.overview_records_by_id.get(int(record_id))
            self._table_row_records[row_index] = record

            for col_index, column in enumerate(self._table_columns):
                value = values.get(column, "")
                display_value = _format_location_value(self, row_data, value) if column == "location" else value
                item = _SortableOverviewItem(
                    str(display_value),
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
                        box = _safe_int(row_data.get("box"))
                        pos = _safe_int(row_data.get("position"))
                        if box is not None and pos is not None:
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

    self._clear_empty_multi_selection(clear_anchor=True, clear_active=False)
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


def _format_add_prefill_positions_text(self, positions):
    layout = getattr(self, "_current_layout", {}) or {}
    return ",".join(pos_to_display(int(position), layout) for position in list(positions or []))


def _emit_add_prefill_background(self, box_num, position, *, positions=None):
    payload = {
        "box": int(box_num),
        "position": int(position),
    }
    normalized_positions = []
    for raw_position in list(positions or []):
        with suppress(TypeError, ValueError):
            normalized_positions.append(int(raw_position))
    normalized_positions = sorted(set(normalized_positions))
    if len(normalized_positions) > 1:
        payload["positions"] = normalized_positions

    self.request_add_prefill_background.emit(payload)
    position_text = (
        _format_add_prefill_positions_text(self, normalized_positions)
        if normalized_positions
        else payload["position"]
    )
    self.status_message.emit(
        t("overview.prefillAddAuto", box=payload["box"], position=position_text),
        2000,
    )


def _emit_add_prefill(self, box_num, position, *, positions=None):
    payload = {
        "box": int(box_num),
        "position": int(position),
    }
    normalized_positions = []
    for raw_position in list(positions or []):
        with suppress(TypeError, ValueError):
            normalized_positions.append(int(raw_position))
    normalized_positions = sorted(set(normalized_positions))
    if len(normalized_positions) > 1:
        payload["positions"] = normalized_positions

    self.request_add_prefill.emit(payload)
    position_text = (
        _format_add_prefill_positions_text(self, normalized_positions)
        if normalized_positions
        else payload["position"]
    )
    self.status_message.emit(
        t("overview.prefillAdd", box=payload["box"], position=position_text),
        2000,
    )
