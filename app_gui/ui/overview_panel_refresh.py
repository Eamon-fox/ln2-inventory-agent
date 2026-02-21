"""Data loading and refresh helpers for OverviewPanel."""

from contextlib import suppress
from datetime import datetime
import os

from PySide6.QtCore import QTimer

from app_gui.i18n import t, tr
from app_gui.ui.utils import build_color_palette
from lib.position_fmt import get_box_count


def _reset_after_load_failure(self):
    self.overview_records_by_id = {}
    self.overview_selected_key = None
    self._reset_detail()


def _build_records_by_id(records):
    records_by_id = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        with suppress(ValueError, TypeError):
            records_by_id[int(rec.get("id"))] = rec
    return records_by_id


def _build_position_map(records):
    pos_map = {}
    for rec in records:
        box = rec.get("box")
        pos = rec.get("position")
        if box is None or pos is None:
            continue
        pos_map[(int(box), int(pos))] = rec
    return pos_map


def _update_hover_hint(self, has_records):
    if not has_records:
        self.ov_hover_hint.setText(tr("overview.emptyHint"))
        self.ov_hover_hint.setProperty("state", "warning")
        self.ov_hover_hint.style().unpolish(self.ov_hover_hint)
        self.ov_hover_hint.style().polish(self.ov_hover_hint)
        return

    self.ov_hover_hint.setText(tr("overview.hoverHint"))
    self.ov_hover_hint.setProperty("state", "default")
    self.ov_hover_hint.style().unpolish(self.ov_hover_hint)
    self.ov_hover_hint.style().polish(self.ov_hover_hint)


def _update_box_live_labels(self, box_numbers, box_stats, rows, cols):
    for box_num in box_numbers:
        stats_item = box_stats.get(str(box_num), {})
        occupied = stats_item.get("occupied", 0)
        empty = stats_item.get("empty", rows * cols)
        total = stats_item.get("total", rows * cols)
        live = self.overview_box_live_labels.get(box_num)
        if live is not None:
            live.setText(t("overview.occupiedCount", occupied=occupied, total=total, empty=empty))


def refresh(self):
    yaml_path = self.yaml_path_getter()
    self.ov_status.setText(tr("overview.statusLoading"))
    if not yaml_path or not os.path.isfile(yaml_path):
        self.ov_status.setText(t("main.fileNotFound", path=yaml_path or ""))
        _reset_after_load_failure(self)
        return

    stats_response = self.bridge.generate_stats(yaml_path)
    if not stats_response.get("ok"):
        self.ov_status.setText(t("overview.loadFailed", error=stats_response.get("message", "unknown error")))
        _reset_after_load_failure(self)
        return

    payload = stats_response.get("result", {})
    data = payload.get("data", {})
    records = data.get("inventory", [])
    self._current_meta = data.get("meta", {})
    self._current_records = records

    # Build color palette from meta
    from lib.custom_fields import get_color_key_options

    build_color_palette(get_color_key_options(self._current_meta))

    self.overview_records_by_id = _build_records_by_id(records)
    self.data_loaded.emit(self.overview_records_by_id)

    layout = payload.get("layout", {})
    stats = payload.get("stats", {})
    overall = stats.get("overall", {})
    box_stats = stats.get("boxes", {})

    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    self._current_layout = layout
    box_numbers = sorted([int(k) for k in box_stats], key=int)
    if not box_numbers:
        box_count = get_box_count(layout)
        box_numbers = list(range(1, box_count + 1))

    shape = (rows, cols, tuple(box_numbers))
    if self.overview_shape != shape:
        self._rebuild_boxes(rows, cols, box_numbers)

    self.overview_pos_map = _build_position_map(records)

    total_records = len(records)
    total_occupied = overall.get("total_occupied", 0)
    total_empty = overall.get("total_empty", 0)
    occupancy_rate = overall.get("occupancy_rate", 0)
    self.ov_total_records_value.setText(str(total_records))
    self.ov_occupied_value.setText(str(total_occupied))
    self.ov_empty_value.setText(str(total_empty))
    self.ov_rate_value.setText(f"{occupancy_rate:.1f}%")

    # Emit stats for status bar
    self.stats_changed.emit(
        {
            "total": total_records,
            "occupied": total_occupied,
            "empty": total_empty,
            "rate": occupancy_rate,
        }
    )

    _update_hover_hint(self, has_records=bool(records))
    _update_box_live_labels(self, box_numbers, box_stats, rows, cols)

    for key, button in self.overview_cells.items():
        box_num, position = key
        rec = self.overview_pos_map.get(key)
        self._paint_cell(button, box_num, position, rec)

    self._rebuild_table_rows(records)
    self._refresh_filter_options(records, box_numbers)
    self._apply_filters()

    self.ov_status.setText(
        t("overview.loadedStatus", count=len(records), time=datetime.now().strftime("%H:%M:%S"))
    )

    # Update box navigation buttons
    self._update_box_navigation(box_numbers)

    # Warm hover animation system after initial UI render to eliminate first-hover delay.
    if not self._hover_warmed and self.overview_cells:
        QTimer.singleShot(50, self._warm_hover_animation)
