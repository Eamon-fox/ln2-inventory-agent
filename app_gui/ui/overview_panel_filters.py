"""Filter helpers for OverviewPanel."""

from datetime import datetime

from PySide6.QtWidgets import QDialog

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr, t
from app_gui.ui.icons import get_icon, Icons
from lib.overview_table_query import (
    detect_overview_table_column_type,
    get_unique_overview_table_values,
    match_overview_table_column_filter,
)


def _refresh_filter_options(self, records, box_numbers):
    from lib.custom_fields import get_color_key

    prev_box = self.ov_filter_box.currentData()
    prev_cell = self.ov_filter_cell.currentData()

    self.ov_filter_box.blockSignals(True)
    self.ov_filter_box.clear()
    self.ov_filter_box.addItem(tr("overview.allBoxes"), None)
    for box_num in box_numbers:
        self.ov_filter_box.addItem(t("overview.boxLabel", box=box_num), box_num)
    index = self.ov_filter_box.findData(prev_box)
    self.ov_filter_box.setCurrentIndex(index if index >= 0 else 0)
    self.ov_filter_box.blockSignals(False)

    meta = getattr(self, "_current_meta", {})
    ck = get_color_key(meta, inventory=records)
    values = sorted({str(rec.get(ck)) for rec in records if rec.get(ck)})
    self.ov_filter_cell.blockSignals(True)
    self.ov_filter_cell.clear()
    self.ov_filter_cell.addItem(tr("overview.allCells"), None)
    for val in values:
        self.ov_filter_cell.addItem(val, val)
    index = self.ov_filter_cell.findData(prev_cell)
    self.ov_filter_cell.setCurrentIndex(index if index >= 0 else 0)
    self.ov_filter_cell.blockSignals(False)


def _apply_filters(self):
    keyword = self.ov_filter_keyword.text().strip().lower()
    selected_box = self.ov_filter_box.currentData()
    selected_cell = self.ov_filter_cell.currentData()
    toggle_checked = bool(self.ov_filter_secondary_toggle.isChecked())

    if self._overview_view_mode == "table":
        self._table_include_inactive = toggle_checked
        include_inactive_loaded = bool(getattr(self, "_stats_include_inactive_loaded", False))
        if self._table_include_inactive != include_inactive_loaded:
            self.refresh()
            return
        self._apply_filters_table(
            keyword=keyword,
            selected_box=selected_box,
            selected_cell=selected_cell,
        )
        return

    self._grid_include_empty_slots = toggle_checked
    self._apply_filters_grid(
        keyword=keyword,
        selected_box=selected_box,
        selected_cell=selected_cell,
        include_empty_slots=self._grid_include_empty_slots,
    )


def _apply_filters_grid(self, keyword, selected_box, selected_cell, include_empty_slots):
    visible_boxes = 0
    visible_slots = 0
    per_box = {box: {"occ": 0, "emp": 0} for box in self.overview_box_groups}

    for (box_num, position), button in self.overview_cells.items():
        record = self.overview_pos_map.get((box_num, position))
        is_empty = record is None
        match_box = selected_box is None or box_num == selected_box
        match_cell = selected_cell is None or (
            record and str(button.property("color_key_value") or "") == selected_cell
        )
        match_empty = include_empty_slots or not is_empty

        if keyword:
            search_text = str(button.property("search_text") or "")
            match_keyword = keyword in search_text
        else:
            match_keyword = True

        visible = bool(match_box and match_cell and match_empty and match_keyword)
        button.setVisible(visible)

        if visible:
            visible_slots += 1
            if is_empty:
                per_box.setdefault(box_num, {"occ": 0, "emp": 0})["emp"] += 1
            else:
                per_box.setdefault(box_num, {"occ": 0, "emp": 0})["occ"] += 1

    for box_num, group in self.overview_box_groups.items():
        stat = per_box.get(box_num, {"occ": 0, "emp": 0})
        total_visible = stat["occ"] + stat["emp"]
        group.setVisible(total_visible > 0)
        if total_visible > 0:
            visible_boxes += 1

        live = self.overview_box_live_labels.get(box_num)
        if live:
            live.setText(t("overview.filteredCount", occupied=stat["occ"], empty=stat["emp"]))

    self._prune_empty_multi_selection()

    if self.overview_selected_key:
        selected_button = self.overview_cells.get(self.overview_selected_key)
        if selected_button and selected_button.isHidden():
            self._clear_selected_cell()
            self._reset_detail()

    self.ov_status.setText(
        t(
            "overview.filterStatus",
            slots=visible_slots,
            boxes=visible_boxes,
            time=datetime.now().strftime("%H:%M:%S"),
        )
    )


def _apply_filters_table(self, keyword, selected_box, selected_cell):
    response = self._query_table_rows(
        keyword=keyword,
        selected_box=selected_box,
        selected_cell=selected_cell,
    )
    if (not isinstance(response, dict) or not response.get("ok")) and str(
        getattr(self, "_table_sort_by", "") or ""
    ) != "location":
        message = str((response or {}).get("message") or "")
        if "sort_by must be one of:" in message:
            self._table_sort_by = "location"
            self._table_sort_order = "asc"
            response = self._query_table_rows(
                keyword=keyword,
                selected_box=selected_box,
                selected_cell=selected_cell,
            )

    if not isinstance(response, dict) or not response.get("ok"):
        self._table_rows = []
        self._table_columns = []
        self._table_data_columns = []
        self._table_header_labels = {}
        self._table_column_types = {}
        self._table_version = int(getattr(self, "_table_version", 0) or 0) + 1
        if hasattr(self, "ov_table"):
            self.ov_table.setRowCount(0)
            self.ov_table.setColumnCount(0)
        self.ov_status.setText(
            t(
                "overview.loadFailed",
                error=localize_error_payload(
                    response or {},
                    fallback=(response or {}).get("message", "unknown error"),
                ),
            )
        )
        return

    result = dict(response.get("result") or {})
    data_columns = list(result.get("columns") or [])
    columns = self._display_table_columns(data_columns)
    header_labels = self._resolve_table_header_labels(columns)
    if (
        columns != list(getattr(self, "_table_columns", []) or [])
        or data_columns != list(getattr(self, "_table_data_columns", []) or [])
        or header_labels != dict(getattr(self, "_table_header_labels", {}) or {})
    ):
        self._table_data_columns = list(data_columns)
        self._table_columns = list(columns)
        self._set_table_columns(self._table_columns, header_labels=header_labels)
    else:
        self._table_data_columns = list(data_columns)
        self._table_columns = list(columns)
        self._table_header_labels = dict(header_labels)
    self._table_column_types = dict(result.get("column_types") or {})
    self._table_rows = list(result.get("rows") or [])
    self._table_version = int(getattr(self, "_table_version", 0) or 0) + 1
    self._column_unique_cache = {}

    applied_filters = dict(result.get("applied_filters") or {})
    self._table_sort_by = str(applied_filters.get("sort_by") or getattr(self, "_table_sort_by", "location"))
    self._table_sort_order = str(
        applied_filters.get("sort_order") or getattr(self, "_table_sort_order", "asc")
    )

    self._render_table_rows(self._table_rows)
    self._sync_table_sort_indicator()

    matched_boxes = list(result.get("matched_boxes") or [])
    total_count = int(result.get("total_count") or len(self._table_rows))

    status_parts = [
        t(
            "overview.filterStatusTable",
            records=total_count,
            boxes=len(matched_boxes),
            time=datetime.now().strftime("%H:%M:%S"),
        )
    ]

    if self._column_filters:
        active_filters = len(self._column_filters)
        status_parts.append(tr("overview.activeFilters").format(count=active_filters))

    self.ov_status.setText(" | ".join(status_parts))


def on_toggle_filters(self, checked):
    self.ov_filter_advanced_widget.setVisible(bool(checked))
    toggle_label = tr("overview.hideFilters") if checked else tr("overview.moreFilters")
    self.ov_filter_toggle_btn.setToolTip(toggle_label)
    if hasattr(self.ov_filter_toggle_btn, "setAccessibleName"):
        self.ov_filter_toggle_btn.setAccessibleName(toggle_label)
    icon_name = Icons.CHEVRON_UP if checked else Icons.CHEVRON_DOWN
    self.ov_filter_toggle_btn.setIcon(get_icon(icon_name))


def on_clear_filters(self):
    self.ov_filter_keyword.clear()
    self.ov_filter_box.setCurrentIndex(0)
    self.ov_filter_cell.setCurrentIndex(0)
    self.ov_filter_secondary_toggle.blockSignals(True)
    if self._overview_view_mode == "table":
        self._table_include_inactive = False
        self.ov_filter_secondary_toggle.setChecked(False)
    else:
        self._grid_include_empty_slots = True
        self.ov_filter_secondary_toggle.setChecked(True)
    self.ov_filter_secondary_toggle.blockSignals(False)
    if self.ov_filter_toggle_btn.isChecked():
        self.ov_filter_toggle_btn.setChecked(False)

    self._column_filters.clear()
    if hasattr(self, "ov_table_header"):
        for i in range(self.ov_table.columnCount()):
            self.ov_table_header.set_column_filtered(i, False)
    self._apply_filters()


def _on_column_filter_clicked(self, column_index, column_name):
    """Handle filter icon click on a column header."""
    from app_gui.ui import overview_panel as _ov_panel

    columns = list(getattr(self, "_table_columns", []) or [])
    if column_index < 0 or column_index >= len(columns):
        return

    logical_column_name = str(columns[column_index] or "")
    display_column_name = str(
        dict(getattr(self, "_table_header_labels", {}) or {}).get(logical_column_name)
        or str(column_name or "")
        or logical_column_name
    )

    filter_type = self._detect_column_type(logical_column_name)

    unique_values = None
    if filter_type in ("list", "number"):
        unique_values = self._get_unique_column_values(logical_column_name)

    current_filter = self._column_filters.get(logical_column_name)

    dialog = _ov_panel._ColumnFilterDialog(
        self,
        display_column_name,
        filter_type,
        unique_values,
        current_filter,
    )

    if dialog.exec() == QDialog.Accepted:
        filter_config = dialog.get_filter_config()

        if filter_config:
            self._column_filters[logical_column_name] = filter_config
            self.ov_table_header.set_column_filtered(column_index, True)
        else:
            self._column_filters.pop(logical_column_name, None)
            self.ov_table_header.set_column_filtered(column_index, False)

        self._apply_filters()
    elif dialog.filter_config == {}:
        self._column_filters.pop(logical_column_name, None)
        self.ov_table_header.set_column_filtered(column_index, False)
        self._apply_filters()


def _detect_column_type(self, column_name):
    """Detect column data type for filtering."""
    cached_types = dict(getattr(self, "_table_column_types", {}) or {})
    normalized_column = str(column_name or "").strip()
    if normalized_column in cached_types:
        return str(cached_types[normalized_column] or "text")
    return detect_overview_table_column_type(
        normalized_column,
        meta=getattr(self, "_current_meta", {}) or {},
        rows=getattr(self, "_table_rows", []) or [],
    )


def _get_unique_column_values(self, column_name):
    """Get unique values and their counts for a column."""
    table_version = int(getattr(self, "_table_version", 0) or 0)
    cache_key = (str(column_name or ""), table_version)
    cache = getattr(self, "_column_unique_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        self._column_unique_cache = cache
    cached = cache.get(cache_key)
    if cached is not None:
        return list(cached)

    sorted_values = get_unique_overview_table_values(
        getattr(self, "_table_rows", []) or [],
        column_name,
    )

    cache[cache_key] = list(sorted_values)
    return sorted_values


def _match_column_filter(self, row_data, column_name, filter_config):
    """Check if a row matches a column filter."""
    if isinstance(filter_config, dict) and str(filter_config.get("type") or "") == "list":
        values = list(filter_config.get("values") or [])
        values_sig = tuple(str(v) for v in values)
        values_set = filter_config.get("_values_set")
        if (not isinstance(values_set, set)) or filter_config.get("_values_sig") != values_sig:
            values_set = set(values_sig)
            filter_config["_values_set"] = values_set
            filter_config["_values_sig"] = values_sig
    return match_overview_table_column_filter(row_data, column_name, filter_config)
