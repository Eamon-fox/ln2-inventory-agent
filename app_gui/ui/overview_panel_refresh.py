"""Data loading and refresh helpers for OverviewPanel."""

from contextlib import suppress
from datetime import datetime
import os

from PySide6.QtCore import QTimer

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import t, tr
from app_gui.ui.utils import build_color_palette
from lib.position_fmt import display_to_box, display_to_pos, get_box_count


def _reset_after_load_failure(self):
    self.overview_records_by_id = {}
    self.overview_pos_map = {}
    self.overview_selected_key = None
    self.overview_empty_multi_selected_keys = set()
    self._current_meta = {}
    self._current_layout = {}
    self._current_records = []
    self._overview_selection_anchor_key = None
    self._table_rows = []
    self._table_columns = []
    self._table_header_labels = {}
    self._table_column_types = {}
    self._table_row_records = []
    self._stats_include_inactive_loaded = False
    self._stats_response_cache = {}
    self._last_stats_cache_key = None
    self._cell_render_signatures = {}
    self._table_version = int(getattr(self, "_table_version", 0) or 0) + 1
    if hasattr(self, "ov_table"):
        self.ov_table.setRowCount(0)
        self.ov_table.setColumnCount(0)
    for group in getattr(self, "overview_box_groups", {}).values():
        with suppress(Exception):
            group.setVisible(False)
    for attr_name, value in (
        ("ov_total_records_value", "0"),
        ("ov_occupied_value", "0"),
        ("ov_empty_value", "0"),
        ("ov_rate_value", "0.0%"),
    ):
        widget = getattr(self, attr_name, None)
        if widget is not None:
            widget.setText(value)
    self._reset_detail()


def _stats_cache_key(yaml_path, include_inactive):
    target_path = os.path.abspath(str(yaml_path or "").strip())
    if not target_path:
        return None
    try:
        stat = os.stat(target_path)
    except OSError:
        return None
    return (
        target_path,
        int(getattr(stat, "st_mtime_ns", 0) or 0),
        int(getattr(stat, "st_size", 0) or 0),
        bool(include_inactive),
    )


def _build_records_by_id(records):
    records_by_id = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        with suppress(ValueError, TypeError):
            records_by_id[int(rec.get("id"))] = rec
    return records_by_id


def _build_position_map(records, layout=None):
    pos_map = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        box = rec.get("box")
        pos = rec.get("position")
        if box in (None, "") or pos in (None, ""):
            continue
        with suppress(ValueError, TypeError):
            box_num = int(display_to_box(box, layout))
            pos_num = int(display_to_pos(pos, layout))
            pos_map[(box_num, pos_num)] = rec
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
        _reset_after_load_failure(self)
        missing_file_message = t("main.fileNotFound", path=yaml_path or "")
        self.ov_status.setText(missing_file_message)
        self.ov_hover_hint.setText(missing_file_message)
        self.ov_hover_hint.setProperty("state", "warning")
        self.ov_hover_hint.style().unpolish(self.ov_hover_hint)
        self.ov_hover_hint.style().polish(self.ov_hover_hint)
        return

    include_inactive = bool(
        self._overview_view_mode == "table" and getattr(self, "_table_include_inactive", False)
    )
    cache_key = _stats_cache_key(yaml_path, include_inactive)
    cached_map = getattr(self, "_stats_response_cache", None)
    if not isinstance(cached_map, dict):
        cached_map = {}
        self._stats_response_cache = cached_map

    stats_response = cached_map.get(cache_key) if cache_key is not None else None
    if stats_response is None:
        stats_response = self.bridge.generate_stats(
            yaml_path,
            include_inactive=include_inactive,
        )
        if cache_key is not None and isinstance(stats_response, dict) and stats_response.get("ok"):
            self._stats_response_cache = {cache_key: stats_response}
            self._last_stats_cache_key = cache_key
        else:
            self._last_stats_cache_key = None
    else:
        self._last_stats_cache_key = cache_key

    if not stats_response.get("ok"):
        _reset_after_load_failure(self)
        self.ov_status.setText(
            t(
                "overview.loadFailed",
                error=localize_error_payload(
                    stats_response,
                    fallback=stats_response.get("message", "unknown error"),
                ),
            )
        )
        return
    self._stats_include_inactive_loaded = include_inactive

    payload = stats_response.get("result", {})
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    meta_payload = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    meta_data = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    self._current_meta = meta_payload or meta_data

    records_preview = payload.get("inventory_preview")
    if isinstance(records_preview, list):
        records = records_preview
    else:
        records = data.get("inventory", []) if isinstance(data.get("inventory"), list) else []
    self._current_records = records

    # Build color palette from meta
    from lib.custom_fields import get_color_key_options

    build_color_palette(get_color_key_options(self._current_meta))

    self.overview_records_by_id = _build_records_by_id(records)
    self.data_loaded.emit(self.overview_records_by_id)

    layout = payload.get("layout", {}) if isinstance(payload.get("layout"), dict) else {}
    if not layout:
        layout = (self._current_meta or {}).get("box_layout", {})
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

    self.overview_pos_map = _build_position_map(records, layout=layout)
    self._prune_empty_multi_selection()

    total_records = int(payload.get("record_count", len(records)) or 0)
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

    _update_hover_hint(self, has_records=(total_records > 0))
    _update_box_live_labels(self, box_numbers, box_stats, rows, cols)
    self._update_box_titles(box_numbers)

    signatures = getattr(self, "_cell_render_signatures", None)
    if not isinstance(signatures, dict):
        signatures = {}
        self._cell_render_signatures = signatures

    for key, button in self.overview_cells.items():
        box_num, position = key
        rec = self.overview_pos_map.get(key)
        signature = self._build_cell_render_signature(box_num, position, rec)
        if signatures.get(key) == signature:
            continue
        self._paint_cell(button, box_num, position, rec)

    self._refresh_filter_options(records, box_numbers)
    self._apply_filters()

    self.ov_status.setText(
        t("overview.loadedStatus", count=total_records, time=datetime.now().strftime("%H:%M:%S"))
    )

    # Update box navigation buttons
    self._update_box_navigation(box_numbers)

    # Warm hover animation system after initial UI render to eliminate first-hover delay.
    if not self._hover_warmed and self.overview_cells:
        QTimer.singleShot(50, self._warm_hover_animation)
