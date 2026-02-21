"""Filter helpers for OverviewPanel."""

import os
from datetime import datetime

from PySide6.QtWidgets import QDialog

from app_gui.i18n import tr, t
from app_gui.ui.icons import get_icon, Icons


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
    ck = get_color_key(meta)
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
    show_empty = self.ov_filter_show_empty.isChecked()

    if self._overview_view_mode == "table":
        self._apply_filters_table(
            keyword=keyword,
            selected_box=selected_box,
            selected_cell=selected_cell,
        )
        return

    self._apply_filters_grid(
        keyword=keyword,
        selected_box=selected_box,
        selected_cell=selected_cell,
        show_empty=show_empty,
    )


def _apply_filters_grid(self, keyword, selected_box, selected_cell, show_empty):
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
        match_empty = show_empty or not is_empty

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

    if self.overview_selected_key:
        selected_button = self.overview_cells.get(self.overview_selected_key)
        if selected_button and not selected_button.isVisible():
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
    matched_rows = []
    matched_boxes = set()

    for row_data in self._table_rows:
        box_num = row_data.get("box")
        color_value = str(row_data.get("color_value") or "")

        match_box = selected_box is None or box_num == selected_box
        match_cell = selected_cell is None or color_value == selected_cell

        if keyword:
            match_keyword = keyword in str(row_data.get("search_text") or "")
        else:
            match_keyword = True

        match_column_filters = True
        for column_name, filter_config in self._column_filters.items():
            if not self._match_column_filter(row_data, column_name, filter_config):
                match_column_filters = False
                break

        if not (match_box and match_cell and match_keyword and match_column_filters):
            continue

        matched_rows.append(row_data)
        if box_num is not None:
            matched_boxes.add(box_num)

    self._render_table_rows(matched_rows)

    status_parts = [
        t(
            "overview.filterStatusTable",
            records=len(matched_rows),
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
    self.ov_filter_toggle_btn.setText(
        tr("overview.hideFilters") if checked else tr("overview.moreFilters")
    )
    icon_name = Icons.CHEVRON_UP if checked else Icons.CHEVRON_DOWN
    self.ov_filter_toggle_btn.setIcon(get_icon(icon_name))


def on_clear_filters(self):
    self.ov_filter_keyword.clear()
    self.ov_filter_box.setCurrentIndex(0)
    self.ov_filter_cell.setCurrentIndex(0)
    self.ov_filter_show_empty.setChecked(True)
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

    filter_type = self._detect_column_type(column_name)

    unique_values = None
    if filter_type in ("list", "number"):
        unique_values = self._get_unique_column_values(column_name)

    current_filter = self._column_filters.get(column_name)

    dialog = _ov_panel._ColumnFilterDialog(
        self,
        column_name,
        filter_type,
        unique_values,
        current_filter,
    )

    if dialog.exec() == QDialog.Accepted:
        filter_config = dialog.get_filter_config()

        if filter_config:
            self._column_filters[column_name] = filter_config
            self.ov_table_header.set_column_filtered(column_index, True)
        else:
            self._column_filters.pop(column_name, None)
            self.ov_table_header.set_column_filtered(column_index, False)

        self._apply_filters()
    elif dialog.filter_config == {}:
        self._column_filters.pop(column_name, None)
        self.ov_table_header.set_column_filtered(column_index, False)
        self._apply_filters()


def _detect_column_type(self, column_name):
    """Detect column data type for filtering."""
    known_types = {
        "id": "number",
        "frozen_at": "date",
        "location": "text",
        "thaw_events": "text",
    }

    if column_name in known_types:
        return known_types[column_name]

    try:
        yaml_path = self.yaml_path_getter()
        if yaml_path and os.path.exists(yaml_path):
            from lib.yaml_ops import load_yaml

            data = load_yaml(yaml_path)
            meta = data.get("meta", {})
            custom_fields = meta.get("custom_fields", [])

            for field in custom_fields:
                if field.get("name") == column_name:
                    field_type = field.get("type", "str")
                    if field_type in ("int", "float"):
                        return "number"
                    if field_type == "date":
                        return "date"
    except Exception:
        pass

    unique_values = self._get_unique_column_values(column_name)
    if unique_values and len(unique_values) <= 20:
        return "list"

    return "text"


def _get_unique_column_values(self, column_name):
    """Get unique values and their counts for a column."""
    value_counts = {}

    for row_data in self._table_rows:
        value = row_data.get("values", {}).get(column_name)
        if value is not None and value != "":
            value_str = str(value)
            value_counts[value_str] = value_counts.get(value_str, 0) + 1

    sorted_values = sorted(
        value_counts.items(),
        key=lambda x: (-x[1], x[0]),
    )

    return sorted_values


def _match_column_filter(self, row_data, column_name, filter_config):
    """Check if a row matches a column filter."""
    value = row_data.get("values", {}).get(column_name)

    if filter_config["type"] == "list":
        return str(value) in [str(v) for v in filter_config["values"]]

    if filter_config["type"] == "text":
        search_text = filter_config["text"].lower()
        return search_text in str(value).lower()

    if filter_config["type"] == "number":
        try:
            num_val = float(value) if value not in (None, "") else None
            if num_val is None:
                return False

            min_val = filter_config.get("min")
            max_val = filter_config.get("max")

            if min_val is not None and num_val < min_val:
                return False
            return not (max_val is not None and num_val > max_val)
        except (ValueError, TypeError):
            return False

    if filter_config["type"] == "date":
        try:
            date_str = str(value)
            date_val = datetime.strptime(date_str, "%Y-%m-%d").date()

            date_from = filter_config.get("from")
            date_to = filter_config.get("to")

            if date_from:
                from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
                if date_val < from_date:
                    return False

            if date_to:
                to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
                if date_val > to_date:
                    return False

            return True
        except (ValueError, TypeError):
            return False

    return True
