"""Data loading and refresh collaborator for OverviewPanel.

``OverviewRefreshController`` owns the read-snapshot refresh pipeline. It keeps
no private state (all inventory/grid state lives on the panel); it exists to
group the data-load flow into a single named responsibility.
"""

from contextlib import suppress
from datetime import datetime
import os

from PySide6.QtCore import QTimer

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import t, tr
from app_gui.ui.utils import build_color_palette
from lib.diagnostics import new_trace_id, span
from lib.position_fmt import display_to_box, display_to_pos, get_box_count
from lib.yaml_ops import clear_read_snapshot, read_snapshot_context


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


class OverviewRefreshController:
    """Read-snapshot refresh pipeline for an ``OverviewPanel``."""

    def __init__(self, panel):
        self._p = panel

    def refresh(self):
        trace_id = new_trace_id("gui-refresh")
        try:
            with read_snapshot_context(trace_id):
                with span("ui.overview_refresh", trace_id=trace_id, source="refresh"):
                    return self._refresh_impl()
        finally:
            clear_read_snapshot(trace_id)

    def _reset_after_load_failure(self):
        p = self._p
        p.overview_records_by_id = {}
        p.overview_pos_map = {}
        p.overview_selected_key = None
        p.overview_empty_multi_selected_keys = set()
        p._current_meta = {}
        p._current_layout = {}
        p._current_records = []
        p._overview_selection_anchor_key = None
        p._table_rows = []
        p._table_columns = []
        p._table_data_columns = []
        p._table_header_labels = {}
        p._table_column_types = {}
        p._table_row_records = []
        p._stats_include_inactive_loaded = False
        p._stats_response_cache = {}
        p._last_stats_cache_key = None
        p._cell_render_signatures = {}
        p._table_version = int(getattr(p, "_table_version", 0) or 0) + 1
        if hasattr(p, "ov_table"):
            p.ov_table.setRowCount(0)
            p.ov_table.setColumnCount(0)
        for group in getattr(p, "overview_box_groups", {}).values():
            with suppress(Exception):
                group.setVisible(False)
        for attr_name, value in (
            ("ov_total_records_value", "0"),
            ("ov_occupied_value", "0"),
            ("ov_empty_value", "0"),
            ("ov_rate_value", "0.0%"),
        ):
            widget = getattr(p, attr_name, None)
            if widget is not None:
                widget.setText(value)
        p._reset_detail()

    def _update_hover_hint(self, has_records):
        p = self._p
        if not has_records:
            p.ov_hover_hint.setText(tr("overview.emptyHint"))
            p.ov_hover_hint.setProperty("state", "warning")
            p.ov_hover_hint.style().unpolish(p.ov_hover_hint)
            p.ov_hover_hint.style().polish(p.ov_hover_hint)
            return

        p.ov_hover_hint.setText(tr("overview.hoverHint"))
        p.ov_hover_hint.setProperty("state", "default")
        p.ov_hover_hint.style().unpolish(p.ov_hover_hint)
        p.ov_hover_hint.style().polish(p.ov_hover_hint)

    def _update_box_live_labels(self, box_numbers, box_stats, rows, cols):
        p = self._p
        for box_num in box_numbers:
            stats_item = box_stats.get(str(box_num), {})
            occupied = stats_item.get("occupied", 0)
            empty = stats_item.get("empty", rows * cols)
            total = stats_item.get("total", rows * cols)
            live = p.overview_box_live_labels.get(box_num)
            if live is not None:
                live.setText(t("overview.occupiedCount", occupied=occupied, total=total, empty=empty))

    def _refresh_impl(self):
        p = self._p
        yaml_path = p.yaml_path_getter()
        p.ov_status.setText(tr("overview.statusLoading"))
        if not yaml_path or not os.path.isfile(yaml_path):
            self._reset_after_load_failure()
            missing_file_message = t("main.fileNotFound", path=yaml_path or "")
            p.ov_status.setText(missing_file_message)
            p.ov_hover_hint.setText(missing_file_message)
            p.ov_hover_hint.setProperty("state", "warning")
            p.ov_hover_hint.style().unpolish(p.ov_hover_hint)
            p.ov_hover_hint.style().polish(p.ov_hover_hint)
            return

        include_inactive = bool(
            p._overview_view_mode == "table" and getattr(p, "_table_include_inactive", False)
        )
        cache_key = _stats_cache_key(yaml_path, include_inactive)
        cached_map = getattr(p, "_stats_response_cache", None)
        if not isinstance(cached_map, dict):
            cached_map = {}
            p._stats_response_cache = cached_map

        stats_response = cached_map.get(cache_key) if cache_key is not None else None
        if stats_response is None:
            stats_response = p.bridge.generate_stats(
                yaml_path,
                include_inactive=include_inactive,
            )
            if cache_key is not None and isinstance(stats_response, dict) and stats_response.get("ok"):
                p._stats_response_cache = {cache_key: stats_response}
                p._last_stats_cache_key = cache_key
            else:
                p._last_stats_cache_key = None
        else:
            p._last_stats_cache_key = cache_key

        if not stats_response.get("ok"):
            self._reset_after_load_failure()
            p.ov_status.setText(
                t(
                    "overview.loadFailed",
                    error=localize_error_payload(
                        stats_response,
                        fallback=stats_response.get("message", "unknown error"),
                    ),
                )
            )
            return
        p._stats_include_inactive_loaded = include_inactive

        payload = stats_response.get("result", {})
        data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
        meta_payload = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
        meta_data = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
        p._current_meta = meta_payload or meta_data

        records_preview = payload.get("inventory_preview")
        if isinstance(records_preview, list):
            records = records_preview
        else:
            records = data.get("inventory", []) if isinstance(data.get("inventory"), list) else []
        p._current_records = records

        # Build color palette from meta
        from lib.custom_fields import get_color_key_options

        build_color_palette(get_color_key_options(p._current_meta))

        p.overview_records_by_id = _build_records_by_id(records)
        p.data_loaded.emit(p.overview_records_by_id)

        layout = payload.get("layout", {}) if isinstance(payload.get("layout"), dict) else {}
        if not layout:
            layout = (p._current_meta or {}).get("box_layout", {})
        stats = payload.get("stats", {})
        overall = stats.get("overall", {})
        box_stats = stats.get("boxes", {})

        rows = int(layout.get("rows", 9))
        cols = int(layout.get("cols", 9))
        p._current_layout = layout
        draft_store = getattr(p, "_draft_store", None)
        if draft_store is not None:
            draft_store.set_field_context(p._current_meta, p._current_records, layout)
        box_numbers = sorted([int(k) for k in box_stats], key=int)
        if not box_numbers:
            box_count = get_box_count(layout)
            box_numbers = list(range(1, box_count + 1))

        shape = (rows, cols, tuple(box_numbers))
        if p.overview_shape != shape:
            p._rebuild_boxes(rows, cols, box_numbers)

        p.overview_pos_map = _build_position_map(records, layout=layout)
        p._prune_empty_multi_selection()

        total_records = int(payload.get("record_count", len(records)) or 0)
        total_occupied = overall.get("total_occupied", 0)
        total_empty = overall.get("total_empty", 0)
        occupancy_rate = overall.get("occupancy_rate", 0)
        p.ov_total_records_value.setText(str(total_records))
        p.ov_occupied_value.setText(str(total_occupied))
        p.ov_empty_value.setText(str(total_empty))
        p.ov_rate_value.setText(f"{occupancy_rate:.1f}%")

        # Emit stats for status bar
        p.stats_changed.emit(
            {
                "total": total_records,
                "occupied": total_occupied,
                "empty": total_empty,
                "rate": occupancy_rate,
            }
        )

        self._update_hover_hint(has_records=(total_records > 0))
        self._update_box_live_labels(box_numbers, box_stats, rows, cols)
        p._update_box_titles(box_numbers)

        signatures = getattr(p, "_cell_render_signatures", None)
        if not isinstance(signatures, dict):
            signatures = {}
            p._cell_render_signatures = signatures

        for key, button in p.overview_cells.items():
            box_num, position = key
            rec = p.overview_pos_map.get(key)
            signature = p._build_cell_render_signature(box_num, position, rec)
            if signatures.get(key) == signature:
                continue
            p._paint_cell(button, box_num, position, rec)

        p._refresh_filter_options(records, box_numbers)
        p._apply_filters()

        p.ov_status.setText(
            t("overview.loadedStatus", count=total_records, time=datetime.now().strftime("%H:%M:%S"))
        )

        # Update box navigation buttons
        p._update_box_navigation(box_numbers)

        # Warm hover animation system after initial UI render to eliminate first-hover delay.
        if not p._hover_warmed and p.overview_cells:
            QTimer.singleShot(50, p._warm_hover_animation)
