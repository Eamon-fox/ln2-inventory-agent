"""Table-view and inline-entry helpers for OverviewPanel."""

from contextlib import suppress

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import t, tr
from app_gui.ui.theme import pick_contrasting_text_color
from app_gui.ui.utils import cell_color
from lib.custom_fields import coerce_value, get_color_key, get_effective_fields
from lib.overview_table_query import (
    build_overview_table_projection,
    filter_overview_table_rows,
    normalize_overview_table_column_filters,
    overview_table_column_types,
    paginate_overview_table_rows,
    sort_overview_table_rows,
)
from lib.plan_item_factory import build_add_plan_item
from lib.position_fmt import format_box_position_display, pos_to_display
from lib.schema_aliases import get_input_stored_at
from lib.validators import parse_date


_TABLE_CONFIRM_COLUMN = "__confirm__"
_TABLE_CONFIRM_MARK = "√"
_TABLE_DRAFT_MARK = "+"
_TABLE_RECORD_ROLE = Qt.UserRole + 100
_TABLE_ROW_DATA_ROLE = Qt.UserRole + 101


def _confirm_cell_display(slot_state, resolved_row):
    """Return (display_value, raw_value) for the confirm column."""
    if slot_state in ("staged", "staged_locked"):
        return _TABLE_CONFIRM_MARK, True
    if slot_state == "draft":
        return _TABLE_DRAFT_MARK, False
    # "empty" or unknown
    return "", False


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
    if column == _TABLE_CONFIRM_COLUMN:
        return None
    if column == "location":
        return _location_sort_key(row_data, value)
    if column == "id":
        return _safe_number(value)
    if column_type == "number":
        return _safe_number(value)
    if column_type == "date":
        return parse_date(value)
    return _text_sort_key(value)


def _table_field_definitions(self):
    field_defs = {}
    meta = getattr(self, "_current_meta", {}) or {}
    inventory = getattr(self, "_current_records", []) or []
    for field_def in get_effective_fields(meta, inventory=inventory):
        if not isinstance(field_def, dict):
            continue
        key = str(field_def.get("key") or "").strip()
        if key:
            field_defs[key] = dict(field_def)
    return field_defs


def _table_entry_columns(self):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.entry_columns()
    return {"stored_at", "frozen_at"} | set(_table_field_definitions(self))


def _table_column_editor_config(self, column_name):
    field_defs = _table_field_definitions(self)
    if str(column_name or "") in {"stored_at", "frozen_at"}:
        return {"kind": "date", "options": [], "required": True}

    field_def = field_defs.get(str(column_name or ""))
    if not isinstance(field_def, dict):
        return {"kind": "", "options": [], "required": False}

    options = [str(option) for option in list(field_def.get("options") or []) if str(option or "").strip()]
    field_type = str(field_def.get("type") or "str").strip().lower()
    if options:
        kind = "choice"
    elif field_type == "date":
        kind = "date"
    else:
        kind = "text"
    return {
        "kind": kind,
        "options": options,
        "required": bool(field_def.get("required")),
    }


def _table_row_slot_key(row_data):
    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is None or position is None:
        return None
    return (box, position)


def _normalize_add_item_positions(item):
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    raw_positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    if not raw_positions:
        raw_positions = [item.get("position")]

    normalized = []
    for raw_position in raw_positions:
        position = _safe_int(raw_position)
        if position is None or position <= 0 or position in normalized:
            continue
        normalized.append(position)
    return tuple(sorted(normalized))


def _blank_entry_values(self):
    return {column: "" for column in sorted(_table_entry_columns(self))}


def _normalize_entry_values(self, values):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.normalize_entry_values(values)
    normalized = _blank_entry_values(self)
    for column in normalized:
        normalized[column] = str((values or {}).get(column, "") or "").strip()
    stored_at = str(get_input_stored_at(normalized, default="") or "").strip()
    normalized["stored_at"] = stored_at
    normalized["frozen_at"] = stored_at
    return normalized


def _entry_values_signature(self, values):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.entry_values_signature(values)
    normalized = _normalize_entry_values(self, values)
    return tuple((column, normalized[column]) for column in sorted(normalized))


def _staged_add_slot_map(self):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.staged_slot_map()
    store = getattr(self, "_plan_store_ref", None)
    if store is None or not hasattr(store, "list_items"):
        return {}

    field_defs = _table_field_definitions(self)
    color_key = get_color_key(
        getattr(self, "_current_meta", {}) or {},
        inventory=getattr(self, "_current_records", []) or [],
    )
    slot_map = {}
    try:
        plan_items = store.list_items()
    except Exception:
        plan_items = []

    for item in list(plan_items or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "").strip().lower() != "add":
            continue

        box = _safe_int(item.get("box"))
        positions = _normalize_add_item_positions(item)
        if box is None or not positions:
            continue

        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        values = _blank_entry_values(self)
        stored_at = str(get_input_stored_at(payload, default="") or "").strip()
        if stored_at:
            values["stored_at"] = stored_at
        for key in field_defs:
            raw_value = fields.get(key)
            values[key] = "" if raw_value in (None, "") else str(raw_value)
        color_value = str(values.get(color_key) or fields.get(color_key) or "")
        editable = len(positions) == 1
        for position in positions:
            slot_map[(box, position)] = {
                "item": item,
                "positions": positions,
                "values": dict(values),
                "color_value": color_value,
                "editable": editable,
            }
    return slot_map


def _staged_entry_values_for_slot(self, slot_key):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.staged_entry_values_for_slot(slot_key)
    if slot_key is None:
        return _blank_entry_values(self)
    staged = _staged_add_slot_map(self).get(tuple(slot_key))
    if not staged:
        return _blank_entry_values(self)
    return _normalize_entry_values(self, staged.get("values") or {})


def _display_table_columns(self, data_columns):
    columns = [str(column or "") for column in list(data_columns or [])]
    if not bool(getattr(self, "_table_include_inactive", False)):
        columns.append(_TABLE_CONFIRM_COLUMN)
    return columns


def _row_search_text(columns, values):
    return " ".join(str((values or {}).get(column, "")) for column in list(columns or [])).lower()


def _overlay_current_view_rows(self, rows, data_columns):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        return draft_store.resolve_rows(list(rows or []), data_columns)

    staged_map = _staged_add_slot_map(self)
    draft_map = dict(getattr(self, "_table_draft_by_slot", {}) or {})
    color_key = get_color_key(
        getattr(self, "_current_meta", {}) or {},
        inventory=getattr(self, "_current_records", []) or [],
    )
    overlayed_rows = []

    for raw_row in list(rows or []):
        row_data = dict(raw_row or {})
        values = dict(row_data.get("values") or {})
        slot_key = _table_row_slot_key(row_data)
        row_kind = str(row_data.get("row_kind") or "")
        row_confirmed = False
        row_locked = False

        if row_kind == "empty_slot" and slot_key is not None:
            staged = staged_map.get(slot_key)
            draft_values = draft_map.get(slot_key)
            if isinstance(draft_values, dict):
                values.update(_normalize_entry_values(self, draft_values))
                row_locked = bool(staged and not staged.get("editable"))
            elif staged:
                values.update(_normalize_entry_values(self, staged.get("values") or {}))
                row_confirmed = True
                row_locked = not bool(staged.get("editable"))

            row_data["color_value"] = str(values.get(color_key) or "")

        row_data["values"] = values
        row_data["row_confirmed"] = row_confirmed
        row_data["row_locked"] = row_locked
        row_data["search_text"] = _row_search_text(data_columns, values)
        overlayed_rows.append(row_data)

    return overlayed_rows


def _query_current_table_rows(self, *, keyword, selected_box, selected_cell):
    projection = build_overview_table_projection(
        getattr(self, "_current_records", []) or [],
        meta=getattr(self, "_current_meta", {}) or {},
        layout=getattr(self, "_current_layout", {}) or {},
        include_empty_slots=True,
    )
    data_columns = list(projection.get("columns") or [])
    normalized_sort_by = str(getattr(self, "_table_sort_by", "location") or "location")
    if normalized_sort_by not in {str(column) for column in data_columns}:
        normalized_sort_by = "location" if "location" in data_columns else (data_columns[0] if data_columns else "location")
        self._table_sort_by = normalized_sort_by

    normalized_column_filters = normalize_overview_table_column_filters(
        data_columns,
        dict(getattr(self, "_column_filters", {}) or {}),
    )
    current_rows = _overlay_current_view_rows(self, projection.get("rows") or [], data_columns)
    filtered_rows, matched_boxes = filter_overview_table_rows(
        current_rows,
        keyword=keyword,
        box=selected_box,
        color_value=selected_cell,
        include_inactive=False,
        column_filters=normalized_column_filters,
    )
    column_types = overview_table_column_types(
        data_columns,
        meta=getattr(self, "_current_meta", {}) or {},
        rows=filtered_rows,
    )
    sorted_rows = sort_overview_table_rows(
        filtered_rows,
        sort_by=normalized_sort_by,
        sort_order=str(getattr(self, "_table_sort_order", "asc") or "asc"),
        column_types=column_types,
    )
    paged_rows, normalized_limit, normalized_offset = paginate_overview_table_rows(
        sorted_rows,
        limit=None,
        offset=0,
    )

    display_rows = []
    for row_data in paged_rows:
        display_rows.append(
            {
                "row_kind": row_data.get("row_kind"),
                "record_id": row_data.get("record_id"),
                "record": row_data.get("record"),
                "box": row_data.get("box"),
                "position": row_data.get("position"),
                "active": bool(row_data.get("active")),
                "color_value": row_data.get("color_value"),
                "values": dict(row_data.get("values") or {}),
                "row_confirmed": bool(row_data.get("row_confirmed")),
                "row_locked": bool(row_data.get("row_locked")),
                "slot_state": str(row_data.get("slot_state") or ""),
            }
        )

    return {
        "ok": True,
        "result": {
            "columns": data_columns,
            "column_types": column_types,
            "rows": display_rows,
            "color_key": projection.get("color_key"),
            "total_count": len(sorted_rows),
            "display_count": len(display_rows),
            "matched_boxes": matched_boxes,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "has_more": False,
            "applied_filters": {
                "keyword": str(keyword or "").strip(),
                "box": selected_box,
                "color_value": None if selected_cell in (None, "") else str(selected_cell),
                "include_inactive": False,
                "column_filters": normalized_column_filters,
                "sort_by": normalized_sort_by,
                "sort_order": str(getattr(self, "_table_sort_order", "asc") or "asc"),
                "sort_nulls": "last",
            },
        },
    }


def display_table_column_label(column_name):
    if str(column_name or "") == _TABLE_CONFIRM_COLUMN:
        return _TABLE_CONFIRM_MARK
    key = _OVERVIEW_TABLE_COLUMN_LABEL_KEYS.get(str(column_name or "").strip())
    if not key:
        return str(column_name or "")
    return tr(key, default=str(column_name or ""))


def _resolve_table_header_labels(self, columns):
    field_labels = {}
    for field_def in _table_field_definitions(self).values():
        key = str(field_def.get("key") or "").strip()
        if key:
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
    self._table_row_signatures = []
    self._table_render_shape_key = None
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
        _TABLE_CONFIRM_COLUMN: 34,
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
    if bool(getattr(self, "_table_include_inactive", False)):
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
    return _query_current_table_rows(
        self,
        keyword=keyword,
        selected_box=selected_box,
        selected_cell=selected_cell,
    )


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

    column_name = str(columns[logical_index] or "location")
    if column_name == _TABLE_CONFIRM_COLUMN:
        return
    self._table_sort_by = column_name
    self._table_sort_order = "desc" if order == Qt.DescendingOrder else "asc"


def _table_cell_is_editable(self, row_data, column_name):
    if bool(getattr(self, "_table_include_inactive", False)):
        return False
    if str(row_data.get("row_kind") or "") != "empty_slot":
        return False
    if bool(row_data.get("row_locked")):
        return False
    return str(column_name or "") in _table_entry_columns(self)


def _row_text_brush(color_value):
    tint_hex = cell_color(color_value or None)
    return tint_hex, QBrush(QColor(pick_contrasting_text_color(tint_hex)))


def _column_type_map(self):
    column_type_map = dict(getattr(self, "_table_column_types", {}) or {})
    for column in list(getattr(self, "_table_columns", []) or []):
        if column in column_type_map or column == _TABLE_CONFIRM_COLUMN:
            continue
        if column == "location":
            column_type_map[column] = "location"
        elif column == "id":
            column_type_map[column] = "number"
        else:
            column_type_map[column] = self._detect_column_type(column)
    return column_type_map


def _row_identity_key(row_data):
    slot_key = _table_row_slot_key(row_data)
    if slot_key is not None:
        return ("slot", slot_key[0], slot_key[1])

    record_id = _safe_int(row_data.get("record_id"))
    if record_id is not None:
        return ("record", record_id)
    return ("kind", str(row_data.get("row_kind") or ""))


def _table_first_row_item(self, row):
    if row < 0 or row >= self.ov_table.rowCount():
        return None
    for column in range(self.ov_table.columnCount()):
        item = self.ov_table.item(row, column)
        if item is not None:
            return item
    return None


def _table_row_data_from_item(item):
    if item is None:
        return {}
    row_data = item.data(_TABLE_ROW_DATA_ROLE)
    if isinstance(row_data, dict):
        return dict(row_data)

    record = item.data(_TABLE_RECORD_ROLE)
    return {
        "row_kind": item.data(Qt.UserRole + 42),
        "box": item.data(Qt.UserRole + 43),
        "position": item.data(Qt.UserRole + 44),
        "record": record if isinstance(record, dict) else None,
        "row_locked": bool(item.data(Qt.UserRole + 49)),
        "row_confirmed": bool(item.data(Qt.UserRole + 50)),
    }


def _table_row_data(self, row):
    return _table_row_data_from_item(_table_first_row_item(self, row))


def _set_cached_row_data(self, row_data):
    target_key = _row_identity_key(row_data)
    rows = list(getattr(self, "_table_rows", []) or [])
    for idx, cached_row in enumerate(rows):
        if _row_identity_key(cached_row) != target_key:
            continue
        rows[idx] = dict(row_data)
        self._table_rows = rows
        return


def _table_column_index(self, column_name):
    try:
        return list(getattr(self, "_table_columns", []) or []).index(str(column_name or ""))
    except ValueError:
        return -1


def _table_row_item(self, row, column_name):
    column_index = _table_column_index(self, column_name)
    if column_index < 0:
        return None
    return self.ov_table.item(row, column_index)


def _snapshot_table_entry_values(self, row, *, row_data=None):
    base_row = dict(row_data or _table_row_data(self, row) or {})
    snapshot = _normalize_entry_values(self, (base_row.get("values") or {}))
    for column_name in snapshot:
        item = _table_row_item(self, row, column_name)
        if item is None:
            continue
        snapshot[column_name] = str(item.text() or "").strip()
    return snapshot


def _row_with_entry_values(self, row_data, entry_values):
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        enriched = dict(row_data or {})
        enriched["_data_columns"] = list(getattr(self, "_table_data_columns", []) or [])
        return draft_store.resolve_single_row(enriched, entry_values)

    next_row = dict(row_data or {})
    values = dict(next_row.get("values") or {})
    values.update(_normalize_entry_values(self, entry_values))
    color_key = get_color_key(
        getattr(self, "_current_meta", {}) or {},
        inventory=getattr(self, "_current_records", []) or [],
    )
    next_row["values"] = values
    next_row["color_value"] = str(values.get(color_key) or "")
    next_row["search_text"] = _row_search_text(getattr(self, "_table_data_columns", []) or [], values)

    slot_key = _table_row_slot_key(next_row)
    staged = _staged_add_slot_map(self).get(slot_key) if slot_key is not None else None
    draft = dict(getattr(self, "_table_draft_by_slot", {}) or {}).get(slot_key)
    next_row["row_locked"] = bool(staged and not staged.get("editable"))
    next_row["row_confirmed"] = bool(staged) and not isinstance(draft, dict)
    return next_row


def _render_table_row(self, row_index, row_data, column_type_map):
    from app_gui.ui import overview_panel as _ov_panel

    resolved_row = dict(row_data or {})
    values = dict(resolved_row.get("values") or {})
    row_tint, row_text_brush = _row_text_brush(resolved_row.get("color_value"))
    record = resolved_row.get("record")
    if not isinstance(record, dict):
        record_id = _safe_int(resolved_row.get("record_id"))
        if record_id is not None:
            record = self.overview_records_by_id.get(record_id)
            resolved_row["record"] = record
    self._table_row_records[row_index] = record

    slot_state = str(resolved_row.get("slot_state") or "empty")
    for col_index, column in enumerate(list(getattr(self, "_table_columns", []) or [])):
        if column == _TABLE_CONFIRM_COLUMN:
            display_value, raw_value = _confirm_cell_display(slot_state, resolved_row)
            raw_value = bool(raw_value)
        else:
            raw_value = values.get(column, "")
            display_value = _format_location_value(self, resolved_row, raw_value) if column == "location" else raw_value

        item = _SortableOverviewItem(
            str(display_value),
            sort_key=_column_sort_key(
                column,
                raw_value,
                resolved_row,
                column_type=column_type_map.get(column),
            ),
        )
        item.setData(_ov_panel.TABLE_ROW_TINT_ROLE, row_tint)
        item.setData(_ov_panel.TABLE_ROW_KIND_ROLE, str(resolved_row.get("row_kind") or ""))
        item.setData(_ov_panel.TABLE_ROW_BOX_ROLE, _safe_int(resolved_row.get("box")))
        item.setData(_ov_panel.TABLE_ROW_POSITION_ROLE, _safe_int(resolved_row.get("position")))
        item.setData(_ov_panel.TABLE_COLUMN_NAME_ROLE, column)
        item.setData(_ov_panel.TABLE_ROW_LOCKED_ROLE, bool(resolved_row.get("row_locked")))
        item.setData(_ov_panel.TABLE_ROW_CONFIRMED_ROLE, bool(resolved_row.get("row_confirmed")))
        item.setData(_TABLE_RECORD_ROLE, record if isinstance(record, dict) else None)
        item.setData(_TABLE_ROW_DATA_ROLE, dict(resolved_row))
        item.setForeground(row_text_brush)

        editable = _table_cell_is_editable(self, resolved_row, column)
        editor_config = _table_column_editor_config(self, column) if editable else {"kind": "", "options": [], "required": False}
        item.setData(_ov_panel.TABLE_EDITOR_KIND_ROLE, editor_config.get("kind", ""))
        item.setData(_ov_panel.TABLE_EDITOR_OPTIONS_ROLE, list(editor_config.get("options") or []))
        item.setData(_ov_panel.TABLE_EDITOR_REQUIRED_ROLE, bool(editor_config.get("required")))

        flags = item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if editable:
            flags |= Qt.ItemIsEditable
        else:
            flags &= ~Qt.ItemIsEditable
        item.setFlags(flags)

        if column == _TABLE_CONFIRM_COLUMN:
            item.setTextAlignment(int(Qt.AlignCenter))
            if slot_state in ("staged", "staged_locked"):
                item.setForeground(QBrush(QColor("#2e7d32")))  # green for confirmed
            elif slot_state == "draft":
                item.setForeground(QBrush(QColor("#9e9e9e")))  # gray for pending draft
        elif column == "id":
            with suppress(ValueError, TypeError):
                item.setData(Qt.UserRole, int(raw_value))
        elif column == "location":
            box = _safe_int(resolved_row.get("box"))
            position = _safe_int(resolved_row.get("position"))
            if box is not None and position is not None:
                item.setData(Qt.UserRole, box * 1000 + position)

        self.ov_table.setItem(row_index, col_index, item)


def _row_render_signature(row_data, columns):
    values = row_data.get("values") or {}
    record = row_data.get("record")
    record_id = record.get("id") if isinstance(record, dict) else row_data.get("record_id")
    return (
        str(row_data.get("row_kind") or ""),
        _safe_int(row_data.get("box")),
        _safe_int(row_data.get("position")),
        _safe_int(record_id),
        str(row_data.get("color_value") or ""),
        bool(row_data.get("row_confirmed")),
        bool(row_data.get("row_locked")),
        tuple(("" if values.get(col) is None else str(values.get(col))) for col in columns),
    )


def _render_table_rows(self, rows):
    rows_list = list(rows or [])
    columns = list(getattr(self, "_table_columns", []) or [])
    column_type_map = _column_type_map(self)
    shape_key = (tuple(columns), tuple(sorted(column_type_map.items())))
    prev_shape_key = getattr(self, "_table_render_shape_key", None)
    prev_signatures = list(getattr(self, "_table_row_signatures", []) or [])
    new_signatures = [_row_render_signature(row, columns) for row in rows_list]

    need_full_rebuild = (
        prev_shape_key != shape_key
        or self.ov_table.rowCount() != len(rows_list)
        or len(prev_signatures) != len(rows_list)
    )

    self.ov_table.setSortingEnabled(False)
    updates_enabled = bool(self.ov_table.updatesEnabled())
    self.ov_table.setUpdatesEnabled(False)
    self._ignore_table_item_change = True

    try:
        if need_full_rebuild:
            self.ov_table.setRowCount(len(rows_list))
            self._table_row_records = [None] * len(rows_list)
            for row_index, row_data in enumerate(rows_list):
                _render_table_row(self, row_index, row_data, column_type_map)
        else:
            if len(self._table_row_records) < len(rows_list):
                self._table_row_records.extend(
                    [None] * (len(rows_list) - len(self._table_row_records))
                )
            for row_index, (sig, row_data) in enumerate(zip(new_signatures, rows_list)):
                if prev_signatures[row_index] == sig:
                    continue
                _render_table_row(self, row_index, row_data, column_type_map)
    finally:
        self._ignore_table_item_change = False
        self.ov_table.setUpdatesEnabled(updates_enabled)
        self.ov_table.setSortingEnabled(True)

    self._table_row_signatures = new_signatures
    self._table_render_shape_key = shape_key


def _refresh_table_entry_row_visual(self, row, *, row_data=None):
    if row < 0 or row >= self.ov_table.rowCount():
        return
    current_row = dict(row_data or _table_row_data(self, row) or {})
    current_item = self.ov_table.currentItem()
    selected_row = current_item.row() if current_item is not None else row
    current_column = current_item.column() if current_item is not None else 0

    sorting_enabled = bool(self.ov_table.isSortingEnabled())
    self.ov_table.setSortingEnabled(False)
    self._ignore_table_item_change = True
    try:
        _render_table_row(self, row, current_row, _column_type_map(self))
    finally:
        self._ignore_table_item_change = False
        self.ov_table.setSortingEnabled(sorting_enabled)

    signatures = list(getattr(self, "_table_row_signatures", []) or [])
    if 0 <= row < len(signatures):
        columns = list(getattr(self, "_table_columns", []) or [])
        signatures[row] = _row_render_signature(current_row, columns)
        self._table_row_signatures = signatures

    if 0 <= selected_row < self.ov_table.rowCount():
        target = self.ov_table.item(selected_row, current_column) or _table_first_row_item(self, selected_row)
        if target is not None:
            self.ov_table.setCurrentItem(target)


def _canonical_choice_value(value, options):
    text = str(value or "").strip()
    if not text:
        return ""
    for option in list(options or []):
        if option == text:
            return option
    lowered = text.casefold()
    for option in list(options or []):
        if str(option).casefold() == lowered:
            return option
    return None


def _normalize_table_entry_payload(self, row_data, *, snapshot):
    normalized = _normalize_entry_values(self, snapshot)
    stored_at = str(get_input_stored_at(normalized, default="") or "").strip()
    if not stored_at:
        header_labels = dict(getattr(self, "_table_header_labels", {}) or {})
        field_label = header_labels.get("stored_at") or header_labels.get("frozen_at") or "stored_at"
        return None, tr(
            "errors.userFacing.missingRequiredField",
            default="Missing required field: {field}",
            field=field_label,
        )
    if parse_date(stored_at) is None:
        return None, localize_error_payload({"error_code": "invalid_date"})

    field_defs = _table_field_definitions(self)
    fields = {}
    for key, field_def in field_defs.items():
        raw_text = str(normalized.get(key, "") or "").strip()
        field_label = str(field_def.get("label") or key)
        required = bool(field_def.get("required"))
        options = [str(option) for option in list(field_def.get("options") or []) if str(option or "").strip()]

        if not raw_text:
            if required:
                return None, tr(
                    "errors.userFacing.missingRequiredField",
                    default="Missing required field: {field}",
                    field=field_label,
                )
            continue

        if options:
            canonical = _canonical_choice_value(raw_text, options)
            if canonical is None:
                return None, localize_error_payload({"error_code": "invalid_field_options"})
            raw_text = canonical

        try:
            coerced = coerce_value(raw_text, field_def.get("type", "str"))
        except Exception as exc:
            if str(field_def.get("type") or "").strip().lower() == "date":
                return None, localize_error_payload({"error_code": "invalid_date"})
            return None, str(exc)

        if coerced is not None:
            fields[key] = coerced

    box = _safe_int(row_data.get("box"))
    position = _safe_int(row_data.get("position"))
    if box is None or position is None:
        return None, localize_error_payload({"error_code": "invalid_position"})

    return {
        "box": box,
        "positions": [position],
        "stored_at": stored_at,
        "fields": fields,
    }, ""


def _current_table_filter_args(self):
    return {
        "keyword": self.ov_filter_keyword.text().strip().lower(),
        "selected_box": self.ov_filter_box.currentData(),
        "selected_cell": self.ov_filter_cell.currentData(),
    }


def _refresh_current_table_view(self):
    if getattr(self, "_overview_view_mode", "grid") != "table":
        return
    self._apply_filters_table(**_current_table_filter_args(self))


def _confirm_table_entry_row(self, row):
    row_data = _table_row_data(self, row)
    if str(row_data.get("row_kind") or "") != "empty_slot":
        return False
    if bool(getattr(self, "_table_include_inactive", False)):
        return False
    if bool(row_data.get("row_locked")) and bool(row_data.get("row_confirmed")):
        return False

    slot_key = _table_row_slot_key(row_data)
    if slot_key is None:
        return False

    snapshot = _snapshot_table_entry_values(self, row, row_data=row_data)
    payload, error_text = _normalize_table_entry_payload(self, row_data, snapshot=snapshot)
    if payload is None:
        if error_text:
            self.status_message.emit(error_text, 4000)
        return True

    item = build_add_plan_item(
        box=payload["box"],
        positions=payload["positions"],
        stored_at=payload["stored_at"],
        fields=payload["fields"],
        source="overview_table",
    )
    self.plan_items_requested.emit([item])

    draft_store = getattr(self, "_draft_store", None)
    staged = _staged_add_slot_map(self).get(slot_key)
    if draft_store is not None:
        if staged is not None:
            draft_store.clear_draft(slot_key)
        else:
            draft_store.set_draft(slot_key, snapshot)
    else:
        if staged is not None:
            self._table_draft_by_slot.pop(slot_key, None)
        else:
            self._table_draft_by_slot[slot_key] = dict(snapshot)

    _refresh_current_table_view(self)
    return True


def _unconfirm_table_entry_row(self, row):
    """Remove a staged single-slot add item when the user clicks the confirm column again."""
    row_data = _table_row_data(self, row)
    if str(row_data.get("row_kind") or "") != "empty_slot":
        return False
    if not row_data.get("row_confirmed"):
        return False

    slot_key = _table_row_slot_key(row_data)
    if slot_key is None:
        return False

    staged = _staged_add_slot_map(self).get(slot_key)
    if staged is None or not staged.get("editable"):
        return False  # only single-slot (editable) items can be unconfirmed from table

    box, position = slot_key
    self.plan_item_removal_requested.emit([{
        "action": "add",
        "box": box,
        "position": position,
    }])

    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        draft_store.clear_draft(slot_key)
    else:
        self._table_draft_by_slot.pop(slot_key, None)

    return True


def _format_add_prefill_positions_text(self, positions):
    layout = getattr(self, "_current_layout", {}) or {}
    return ",".join(pos_to_display(int(position), layout) for position in list(positions or []))


def _emit_takeout_prefill_background(self, box_num, position, record_id):
    payload = {
        "box": int(box_num),
        "position": int(position),
        "record_id": int(record_id),
    }
    self.request_prefill_background.emit(payload)
    self.status_message.emit(t("overview.prefillTakeoutAuto", id=payload["record_id"]), 2000)


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


def _prefill_table_record_row(self, row_data):
    normalized_row = dict(row_data or {})
    row_kind = str(normalized_row.get("row_kind") or "")
    slot_key = _table_row_slot_key(normalized_row)

    if row_kind == "empty_slot" and slot_key is not None:
        staged = _staged_add_slot_map(self).get(slot_key)
        if staged and len(tuple(staged.get("positions") or ())) > 1:
            _emit_add_prefill_background(
                self,
                slot_key[0],
                slot_key[1],
                positions=tuple(staged.get("positions") or ()),
            )
            return True

        _emit_add_prefill_background(self, slot_key[0], slot_key[1])
        return True

    record = normalized_row.get("record")
    if not isinstance(record, dict):
        record_id = _safe_int(normalized_row.get("record_id"))
        if record_id is not None:
            record = self.overview_records_by_id.get(record_id)
            normalized_row["record"] = record

    if not isinstance(record, dict):
        return False

    box_num = _safe_int(record.get("box", normalized_row.get("box")))
    position = _safe_int(record.get("position", normalized_row.get("position")))
    record_id = _safe_int(record.get("id", normalized_row.get("record_id")))
    if box_num is None or position is None or record_id is None:
        return False

    _emit_takeout_prefill_background(self, box_num, position, record_id)
    return True


def on_table_cell_clicked(self, row, column):
    item = self.ov_table.item(row, column) or _table_first_row_item(self, row)
    if item is None:
        return

    row_data = _table_row_data_from_item(item)
    column_name = str(item.data(Qt.UserRole + 45) or "")
    if column_name == _TABLE_CONFIRM_COLUMN:
        # Staged + editable (single-slot) → toggle off (unconfirm)
        if (
            row_data.get("row_confirmed")
            and not row_data.get("row_locked")
            and str(row_data.get("row_kind") or "") == "empty_slot"
        ):
            if _unconfirm_table_entry_row(self, row):
                return
        # Otherwise try to confirm (draft → staged)
        if _confirm_table_entry_row(self, row):
            return

    _prefill_table_record_row(self, row_data)


def on_table_row_double_clicked(self, row, column):
    on_table_cell_clicked(self, row, column)


def _on_table_item_changed(self, item):
    from app_gui.ui import overview_panel as _ov_panel

    if bool(getattr(self, "_ignore_table_item_change", False)):
        return
    if item is None:
        return

    column_name = str(item.data(_ov_panel.TABLE_COLUMN_NAME_ROLE) or "")
    if column_name not in _table_entry_columns(self):
        return

    row_data = _table_row_data_from_item(item)
    if not _table_cell_is_editable(self, row_data, column_name):
        return

    row = int(item.row())
    slot_key = _table_row_slot_key(row_data)
    if slot_key is None:
        return

    snapshot = _snapshot_table_entry_values(self, row, row_data=row_data)
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        draft_store.set_draft(slot_key, snapshot)
    else:
        staged_values = _staged_entry_values_for_slot(self, slot_key)
        if _entry_values_signature(self, snapshot) == _entry_values_signature(self, staged_values):
            self._table_draft_by_slot.pop(slot_key, None)
        elif all(not str(value or "").strip() for value in snapshot.values()) and all(
            not str(value or "").strip() for value in staged_values.values()
        ):
            self._table_draft_by_slot.pop(slot_key, None)
        else:
            self._table_draft_by_slot[slot_key] = dict(snapshot)

    next_row = _row_with_entry_values(self, row_data, snapshot)
    _set_cached_row_data(self, next_row)
    _refresh_table_entry_row_visual(self, row, row_data=next_row)


def _on_plan_store_changed(self):
    if getattr(self, "_overview_view_mode", "grid") != "table":
        return
    if bool(getattr(self, "_table_include_inactive", False)):
        return
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is not None:
        draft_store.reconcile_with_staged()
    _refresh_current_table_view(self)


def _on_table_context_menu(self, pos):
    """Show context menu for table rows with draft-discard option."""
    from PySide6.QtWidgets import QMenu

    item = self.ov_table.itemAt(pos)
    if item is None:
        return

    row_data = _table_row_data_from_item(item)
    if str(row_data.get("row_kind") or "") != "empty_slot":
        return

    slot_key = _table_row_slot_key(row_data)
    draft_store = getattr(self, "_draft_store", None)
    if draft_store is None or slot_key is None or not draft_store.has_draft(slot_key):
        return

    menu = QMenu(self)
    discard_action = menu.addAction(t("overview.discardDraft", default="Discard changes"))
    chosen = menu.exec_(self.ov_table.viewport().mapToGlobal(pos))
    if chosen is discard_action:
        draft_store.clear_draft(slot_key)
        _refresh_current_table_view(self)
