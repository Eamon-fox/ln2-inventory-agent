"""Runtime behavior helpers for OverviewPanel."""

from PySide6.QtCore import QEvent, Qt, QSignalBlocker
from PySide6.QtWidgets import QWidget

from app_gui.i18n import tr
from app_gui.ui.overview_panel_cell_button import CellButton

_GRID_NAVIGATION_KEYS = {
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
}
_GRID_HOVER_EVENT_TYPES = (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove)
_GRID_NAVIGATION_TARGET_KINDS = {"cell", "scroll", "viewport", "grid"}
_GRID_ZOOM_TARGET_KINDS = {"scroll", "viewport"}


def _resolve_grid_runtime_target(self, obj):
    if obj is None:
        return "", None

    coordinates = None
    if isinstance(obj, CellButton):
        coordinates = _grid_cell_coordinates(obj)
        return "cell", coordinates

    scroll = getattr(self, "ov_scroll", None)
    if obj is scroll:
        return "scroll", None

    viewport = scroll.viewport() if scroll is not None else None
    if obj is viewport:
        return "viewport", None
    if obj is getattr(self, "ov_boxes_widget", None):
        return "grid", None
    return "", None


def _grid_cell_coordinates(obj):
    if obj is None:
        return None

    box_num = obj.property("overview_box")
    position = obj.property("overview_position")
    if box_num is None or position is None:
        return None

    try:
        return int(box_num), int(position)
    except (TypeError, ValueError):
        return None


def _grid_navigation_direction(self, obj, event):
    if event.type() != QEvent.KeyPress:
        return None
    if getattr(self, "_overview_view_mode", "grid") != "grid":
        return None
    if event.modifiers() != Qt.NoModifier:
        return None
    target_kind, _target_coordinates = _resolve_grid_runtime_target(self, obj)
    if target_kind not in _GRID_NAVIGATION_TARGET_KINDS:
        return None
    return _GRID_NAVIGATION_KEYS.get(event.key())


def _handle_grid_navigation_keypress(self, obj, event):
    direction = _grid_navigation_direction(self, obj, event)
    return bool(direction and self._navigate_grid_selection(direction))

def _handle_grid_zoom_wheel(self, obj, event):
    if event.type() != QEvent.Wheel:
        return False
    target_kind, _target_coordinates = _resolve_grid_runtime_target(self, obj)
    if target_kind not in _GRID_ZOOM_TARGET_KINDS:
        return False
    if not (event.modifiers() & Qt.ControlModifier):
        return False

    import time
    from app_gui.ui.overview_panel_zoom import _WHEEL_ZOOM_MIN_INTERVAL

    now = time.monotonic()
    if now - getattr(self, "_last_wheel_zoom_time", 0) < _WHEEL_ZOOM_MIN_INTERVAL:
        return True

    self._last_wheel_zoom_time = now
    delta = event.angleDelta().y()
    if delta > 0:
        self._set_zoom(self._zoom_level + 0.1)
    elif delta < 0:
        self._set_zoom(self._zoom_level - 0.1)
    return True


def _handle_grid_hover_event(self, obj, event):
    if event.type() not in _GRID_HOVER_EVENT_TYPES:
        return False

    target_kind, coordinates = _resolve_grid_runtime_target(self, obj)
    if target_kind != "cell":
        return False
    if coordinates is None:
        return False

    box_num, position = coordinates
    self.on_cell_hovered(box_num, position)
    return False


def _handle_grid_runtime_event(self, obj, event):
    if _handle_grid_navigation_keypress(self, obj, event):
        return True
    if _handle_grid_zoom_wheel(self, obj, event):
        return True
    _handle_grid_hover_event(self, obj, event)
    return False


def _apply_filters_now(self):
    self._apply_filters()


def _filter_debounce_delay_ms(self):
    delay_ms = int(getattr(self, "_filter_debounce_ms", 120) or 120)
    return max(0, delay_ms)


def _should_debounce_filter_application(self):
    if not self.isVisible():
        return False
    if getattr(self, "_filter_apply_timer", None) is None:
        return False
    return _filter_debounce_delay_ms(self) > 0


def _on_filter_keyword_changed(self, _text=""):
    # Keep tests/headless behavior synchronous while debouncing visible UI typing.
    if not _should_debounce_filter_application(self):
        _apply_filters_now(self)
        return
    self._schedule_apply_filters()


def _schedule_apply_filters(self):
    if not _should_debounce_filter_application(self):
        _apply_filters_now(self)
        return
    self._filter_apply_timer.start(_filter_debounce_delay_ms(self))


def _on_filter_debounce_timeout(self):
    _apply_filters_now(self)


def _normalize_view_mode(mode):
    return mode if mode in {"grid", "table"} else "grid"


def _remember_secondary_toggle_state(self, previous_mode):
    checked = bool(self.ov_filter_secondary_toggle.isChecked())
    if previous_mode == "table":
        self._table_include_inactive = checked
    else:
        self._grid_include_empty_slots = checked


def _sync_secondary_toggle_for_view_mode(self, mode):
    with QSignalBlocker(self.ov_filter_secondary_toggle):
        if mode == "table":
            self.ov_filter_secondary_toggle.setText(tr("overview.showTakenOut"))
            self.ov_filter_secondary_toggle.setToolTip(tr("overview.showTakenOutTooltip"))
            self.ov_filter_secondary_toggle.setChecked(bool(self._table_include_inactive))
        else:
            self.ov_filter_secondary_toggle.setText(tr("overview.showEmpty"))
            self.ov_filter_secondary_toggle.setToolTip("")
            self.ov_filter_secondary_toggle.setChecked(bool(self._grid_include_empty_slots))


def _set_grid_mode_aux_visibility(self, is_grid_mode):
    self._zoom_container.setVisible(bool(is_grid_mode))
    self._box_nav_container.setVisible(bool(is_grid_mode))
    if hasattr(self, "ov_export_csv_btn"):
        self.ov_export_csv_btn.setVisible(bool(is_grid_mode))
        if is_grid_mode:
            self._position_floating_actions()


def _apply_view_mode_ui(self, mode):
    self.ov_view_grid_btn.setChecked(mode == "grid")
    self.ov_view_table_btn.setChecked(mode == "table")
    self._update_view_toggle_icons()
    self._overview_view_mode = mode
    self.ov_view_stack.setCurrentIndex(0 if mode == "grid" else 1)
    _sync_secondary_toggle_for_view_mode(self, mode)
    _set_grid_mode_aux_visibility(self, mode == "grid")


def _view_mode_include_inactive(self, mode):
    return bool(mode == "table" and self._table_include_inactive)


def _on_view_mode_changed(self, mode):
    mode = _normalize_view_mode(mode)
    previous_mode = getattr(self, "_overview_view_mode", "grid")
    _remember_secondary_toggle_state(self, previous_mode)
    _apply_view_mode_ui(self, mode)

    include_inactive = _view_mode_include_inactive(self, mode)
    if include_inactive != bool(getattr(self, "_stats_include_inactive_loaded", False)):
        self.refresh()
        return

    self._apply_filters()


def eventFilter(self, obj, event):
    if obj is self.ov_scroll.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
        self._position_floating_actions()

    if self._handle_grid_runtime_event(obj, event):
        return True

    if _handle_table_escape_key(self, obj, event):
        return True

    return QWidget.eventFilter(self, obj, event)


def _handle_table_escape_key(self, obj, event):
    """Discard inline-entry draft when Escape is pressed in table view."""
    if event.type() != QEvent.KeyPress:
        return False
    if event.key() != Qt.Key_Escape:
        return False
    if getattr(self, "_overview_view_mode", "grid") != "table":
        return False

    ov_table = getattr(self, "ov_table", None)
    if ov_table is None or obj is not ov_table:
        return False

    draft_store = getattr(self, "_draft_store", None)
    if draft_store is None:
        return False

    from app_gui.ui import overview_panel_table as _ov_table

    current_item = ov_table.currentItem()
    if current_item is None:
        return False

    row_data = _ov_table._table_row_data_from_item(current_item)
    if str(row_data.get("row_kind") or "") != "empty_slot":
        return False

    slot_key = _ov_table._table_row_slot_key(row_data)
    if slot_key is None or not draft_store.has_draft(slot_key):
        return False

    draft_store.clear_draft(slot_key)
    row = current_item.row()
    _ov_table._refresh_current_table_view(self)
    return True


def _emit_export_inventory_csv_request(self, checked=False):
    _ = checked
    self.request_export_inventory_csv.emit()
