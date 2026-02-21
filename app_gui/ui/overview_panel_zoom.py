"""Zoom and navigation helpers for OverviewPanel."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QLabel, QPushButton

from app_gui.i18n import t
from app_gui.ui.theme import FONT_SIZE_CELL


def _set_zoom(self, level, animated=False):
    """Set zoom level with optional animation."""
    target_level = max(0.2, min(3.0, round(level, 1)))

    if not animated or abs(target_level - self._zoom_level) < 0.05:
        self._zoom_level = target_level
        self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")
        self._apply_zoom()
        return

    if self._zoom_animation is not None:
        self._zoom_animation.stop()

    if not hasattr(self, "_zoom_proxy"):
        self._zoom_proxy = QLabel()
        self._zoom_proxy.setProperty("zoom_value", int(self._zoom_level * 100))

    self._zoom_animation = QPropertyAnimation(self._zoom_proxy, b"zoom_value")
    self._zoom_animation.setDuration(300)
    self._zoom_animation.setEasingCurve(QEasingCurve.OutCubic)
    self._zoom_animation.setStartValue(int(self._zoom_level * 100))
    self._zoom_animation.setEndValue(int(target_level * 100))

    def update_zoom(value):
        self._zoom_level = value / 100.0
        self._zoom_label.setText(f"{value}%")
        self._apply_zoom()

    self._zoom_animation.valueChanged.connect(update_zoom)
    self._zoom_animation.start()


def _apply_zoom(self):
    """Resize all existing cell buttons and repaint with scaled font."""
    cell_size = max(12, int(self._base_cell_size * self._zoom_level))
    font_size_occupied = max(9, int(FONT_SIZE_CELL * self._zoom_level))
    font_size_empty = max(8, int((FONT_SIZE_CELL - 1) * self._zoom_level))
    self._current_font_sizes = (font_size_occupied, font_size_empty)
    for button in self.overview_cells.values():
        if hasattr(button, "reset_hover_state"):
            button.reset_hover_state(clear_base=True)
        button.setFixedSize(cell_size, cell_size)
    self._repaint_all_cells()


def _animate_scroll_to(self, target_h=None, target_v=None, duration=400):
    """Animate scroll bars to target positions."""
    h_bar = self.ov_scroll.horizontalScrollBar()
    v_bar = self.ov_scroll.verticalScrollBar()

    if self._scroll_h_animation is not None:
        self._scroll_h_animation.stop()
        self._scroll_h_animation = None
    if self._scroll_v_animation is not None:
        self._scroll_v_animation.stop()
        self._scroll_v_animation = None

    if target_h is not None and h_bar.value() != target_h:
        self._scroll_h_animation = QPropertyAnimation(h_bar, b"value", self)
        self._scroll_h_animation.setDuration(duration)
        self._scroll_h_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_h_animation.setStartValue(h_bar.value())
        self._scroll_h_animation.setEndValue(int(target_h))
        self._scroll_h_animation.start()

    if target_v is not None and v_bar.value() != target_v:
        self._scroll_v_animation = QPropertyAnimation(v_bar, b"value", self)
        self._scroll_v_animation.setDuration(duration)
        self._scroll_v_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_v_animation.setStartValue(v_bar.value())
        self._scroll_v_animation.setEndValue(int(target_v))
        self._scroll_v_animation.start()


def _calc_fit_zoom(current_zoom, viewport_width, viewport_height, content_width, content_height, fill_ratio):
    if content_width <= 0 or content_height <= 0:
        return None
    zoom_w = (viewport_width * fill_ratio) / content_width * current_zoom
    zoom_h = (viewport_height * fill_ratio) / content_height * current_zoom
    return min(zoom_w, zoom_h)


def _calc_center_scroll_targets(target_widget, viewport_width, viewport_height):
    box_pos = target_widget.pos()
    target_h = max(0, box_pos.x() - (viewport_width - target_widget.width()) // 2)
    target_v = max(0, box_pos.y() - (viewport_height - target_widget.height()) // 2)
    return target_h, target_v


def _schedule_center_scroll(self, target_widget, viewport_width, viewport_height, delay_ms=320):
    def scroll_to_widget():
        target_h, target_v = self._calc_center_scroll_targets(
            target_widget,
            viewport_width,
            viewport_height,
        )
        self._animate_scroll_to(target_h, target_v)

    QTimer.singleShot(delay_ms, scroll_to_widget)


def _fit_one_box(self):
    """Smart zoom: fit first box to 90% of viewport with animation."""
    if not self.overview_box_groups:
        return

    box_numbers = sorted(self.overview_box_groups.keys())
    if not box_numbers:
        return

    first_box = self.overview_box_groups[box_numbers[0]]
    viewport = self.ov_scroll.viewport()
    viewport_width = viewport.width()
    viewport_height = viewport.height()
    target_zoom = self._calc_fit_zoom(
        self._zoom_level,
        viewport_width,
        viewport_height,
        first_box.sizeHint().width(),
        first_box.sizeHint().height(),
        0.9,
    )
    if target_zoom is None:
        return

    self._set_zoom(target_zoom, animated=True)
    self._schedule_center_scroll(first_box, viewport_width, viewport_height)


def _fit_all_boxes(self):
    """Smart zoom: fit all boxes in viewport with animation."""
    if not self.overview_box_groups:
        return

    viewport = self.ov_scroll.viewport()
    content = self.ov_boxes_widget
    viewport_width = viewport.width()
    viewport_height = viewport.height()
    target_zoom = self._calc_fit_zoom(
        self._zoom_level,
        viewport_width,
        viewport_height,
        content.sizeHint().width(),
        content.sizeHint().height(),
        0.95,
    )
    if target_zoom is None:
        return

    self._set_zoom(target_zoom, animated=True)
    QTimer.singleShot(320, lambda: self._animate_scroll_to(0, 0))


def _update_box_navigation(self, box_numbers):
    """Update box quick navigation buttons."""
    while self._box_nav_layout.count():
        item = self._box_nav_layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()

    for box_num in box_numbers:
        btn = QPushButton(str(box_num))
        btn.setFixedSize(24, 24)
        btn.setObjectName("overviewBoxNavButton")
        btn.setToolTip(t("overview.jumpToBox", box=box_num))
        btn.clicked.connect(lambda checked=False, b=box_num: self._jump_to_box(b))
        self._box_nav_layout.addWidget(btn)


def _jump_to_box(self, box_num):
    """Jump to specific box with animated scroll and zoom."""
    box_group = self.overview_box_groups.get(box_num)
    if not box_group:
        return

    viewport = self.ov_scroll.viewport()
    viewport_width = viewport.width()
    viewport_height = viewport.height()
    target_zoom = self._calc_fit_zoom(
        self._zoom_level,
        viewport_width,
        viewport_height,
        box_group.sizeHint().width(),
        box_group.sizeHint().height(),
        0.85,
    )
    if target_zoom is None:
        return

    if abs(target_zoom - self._zoom_level) > 0.15:
        self._set_zoom(target_zoom, animated=True)
        self._schedule_center_scroll(box_group, viewport_width, viewport_height)
        return

    target_h, target_v = self._calc_center_scroll_targets(
        box_group,
        viewport_width,
        viewport_height,
    )
    self._animate_scroll_to(target_h, target_v)
