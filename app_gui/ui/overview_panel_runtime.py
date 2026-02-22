"""Runtime behavior helpers for OverviewPanel."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QWidget

from app_gui.i18n import tr


def _on_view_mode_changed(self, mode):
    if mode not in {"grid", "table"}:
        mode = "grid"

    previous_mode = getattr(self, "_overview_view_mode", "grid")
    if previous_mode == "table":
        self._table_include_inactive = bool(self.ov_filter_secondary_toggle.isChecked())
    else:
        self._grid_include_empty_slots = bool(self.ov_filter_secondary_toggle.isChecked())

    # Update button states
    self.ov_view_grid_btn.setChecked(mode == "grid")
    self.ov_view_table_btn.setChecked(mode == "table")

    # Update icons based on checked state
    self._update_view_toggle_icons()

    self._overview_view_mode = mode
    self.ov_view_stack.setCurrentIndex(0 if mode == "grid" else 1)

    self.ov_filter_secondary_toggle.blockSignals(True)
    if mode == "table":
        self.ov_filter_secondary_toggle.setText(tr("overview.showTakenOut"))
        self.ov_filter_secondary_toggle.setChecked(bool(self._table_include_inactive))
    else:
        self.ov_filter_secondary_toggle.setText(tr("overview.showEmpty"))
        self.ov_filter_secondary_toggle.setChecked(bool(self._grid_include_empty_slots))
    self.ov_filter_secondary_toggle.setToolTip("")
    self.ov_filter_secondary_toggle.blockSignals(False)

    # Show/hide zoom controls and box navigation based on view mode
    # Only show in grid mode, hide in table mode
    is_grid_mode = mode == "grid"
    self._zoom_container.setVisible(is_grid_mode)
    self._box_nav_container.setVisible(is_grid_mode)

    include_inactive = bool(mode == "table" and self._table_include_inactive)
    if include_inactive != bool(getattr(self, "_stats_include_inactive_loaded", False)):
        self.refresh()
        return

    self._apply_filters()


def eventFilter(self, obj, event):
    # Ctrl+Wheel zoom on scroll area
    if obj is self.ov_scroll and event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
        delta = event.angleDelta().y()
        if delta > 0:
            self._set_zoom(self._zoom_level + 0.1)
        elif delta < 0:
            self._set_zoom(self._zoom_level - 0.1)
        return True  # consume event
    if event.type() in (QEvent.Enter, QEvent.HoverEnter, QEvent.HoverMove, QEvent.MouseMove):
        box_num = obj.property("overview_box")
        position = obj.property("overview_position")
        if box_num is not None and position is not None:
            self.on_cell_hovered(int(box_num), int(position))
    return QWidget.eventFilter(self, obj, event)
