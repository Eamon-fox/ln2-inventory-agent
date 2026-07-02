"""Zoom and box-navigation collaborator for OverviewPanel.

``OverviewZoomController`` owns the zoom/scroll animation objects and drives
zoom + box navigation against the panel it is constructed with. Shared scalar
state (``_zoom_level``, ``_base_cell_size``, ``_current_font_sizes``) and the
zoom-related widgets stay on the panel because grid rendering, runtime event
handling, the widget tree setup and tests read them directly; this controller
only owns state that is exclusively zoom-private.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QLabel, QPushButton

from app_gui.i18n import t
from app_gui.ui.theme import FONT_SIZE_CELL

# Minimum interval between Ctrl+Wheel zoom steps (seconds).
_WHEEL_ZOOM_MIN_INTERVAL = 0.04  # ~25 fps cap


class OverviewZoomController:
    """Zoom and box-navigation behavior for an ``OverviewPanel``."""

    def __init__(self, panel):
        self._p = panel
        # Animation objects owned exclusively by the zoom concern.
        self._zoom_animation = None
        self._scroll_h_animation = None
        self._scroll_v_animation = None
        self._zoom_proxy = None

    def _set_zoom(self, level, animated=False):
        """Set zoom level with optional animation."""
        p = self._p
        target_level = max(0.2, min(3.0, round(level, 1)))

        if not animated or abs(target_level - p._zoom_level) < 0.05:
            p._zoom_level = target_level
            p._zoom_label.setText(f"{int(p._zoom_level * 100)}%")
            self._apply_zoom(update_labels=True)
            return

        if self._zoom_animation is not None:
            self._zoom_animation.stop()

        if self._zoom_proxy is None:
            self._zoom_proxy = QLabel()
            self._zoom_proxy.setProperty("zoom_value", int(p._zoom_level * 100))

        self._zoom_animation = QPropertyAnimation(self._zoom_proxy, b"zoom_value")
        self._zoom_animation.setDuration(300)
        self._zoom_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._zoom_animation.setStartValue(int(p._zoom_level * 100))
        self._zoom_animation.setEndValue(int(target_level * 100))

        def update_zoom(value):
            p._zoom_level = value / 100.0
            p._zoom_label.setText(f"{value}%")
            # Keep zoom animation smooth: defer label visibility reflow.
            self._apply_zoom(update_labels=False)

        self._zoom_animation.valueChanged.connect(update_zoom)
        self._zoom_animation.finished.connect(lambda: self._apply_zoom(update_labels=True))
        self._zoom_animation.start()

    def _apply_zoom(self, update_labels=True):
        """Resize all existing cell buttons and update font sizes.

        Font size is set via ``QFont.setPixelSize()`` (fast) instead of
        rebuilding stylesheets. Optional ``update_labels`` controls whether
        occupied-cell text visibility is recomputed at this step.
        """
        p = self._p
        cell_size = max(12, int(p._base_cell_size * p._zoom_level))
        font_size_occupied = max(9, int(FONT_SIZE_CELL * p._zoom_level))
        font_size_empty = max(8, int((FONT_SIZE_CELL - 1) * p._zoom_level))
        p._current_font_sizes = (font_size_occupied, font_size_empty)

        container = getattr(p, "ov_boxes_widget", None)
        update_cell_label_visibility = getattr(p, "_update_cell_label_visibility", None)
        if container is not None:
            container.setUpdatesEnabled(False)
        try:
            for button in p.overview_cells.values():
                # Only reset hover on the actually-hovered cell (not all 1500+).
                if getattr(button, "_is_hovered", False) and hasattr(button, "reset_hover_state"):
                    button.reset_hover_state(clear_base=True)
                button.setFixedSize(cell_size, cell_size)
                # Update font size directly — much cheaper than setStyleSheet.
                is_empty = button.property("is_empty")
                fs = font_size_empty if is_empty else font_size_occupied
                font = button.font()
                if font.pixelSize() != fs:
                    font.setPixelSize(fs)
                    button.setFont(font)
                if update_labels and callable(update_cell_label_visibility):
                    update_cell_label_visibility(button)
        finally:
            if container is not None:
                container.setUpdatesEnabled(True)

    def _animate_scroll_to(self, target_h=None, target_v=None, duration=400):
        """Animate scroll bars to target positions."""
        p = self._p
        h_bar = p.ov_scroll.horizontalScrollBar()
        v_bar = p.ov_scroll.verticalScrollBar()

        if self._scroll_h_animation is not None:
            self._scroll_h_animation.stop()
            self._scroll_h_animation = None
        if self._scroll_v_animation is not None:
            self._scroll_v_animation.stop()
            self._scroll_v_animation = None

        if target_h is not None and h_bar.value() != target_h:
            self._scroll_h_animation = QPropertyAnimation(h_bar, b"value", p)
            self._scroll_h_animation.setDuration(duration)
            self._scroll_h_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._scroll_h_animation.setStartValue(h_bar.value())
            self._scroll_h_animation.setEndValue(int(target_h))
            self._scroll_h_animation.start()

        if target_v is not None and v_bar.value() != target_v:
            self._scroll_v_animation = QPropertyAnimation(v_bar, b"value", p)
            self._scroll_v_animation.setDuration(duration)
            self._scroll_v_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._scroll_v_animation.setStartValue(v_bar.value())
            self._scroll_v_animation.setEndValue(int(target_v))
            self._scroll_v_animation.start()

    @staticmethod
    def _calc_fit_zoom(current_zoom, viewport_width, viewport_height, content_width, content_height, fill_ratio):
        if content_width <= 0 or content_height <= 0:
            return None
        zoom_w = (viewport_width * fill_ratio) / content_width * current_zoom
        zoom_h = (viewport_height * fill_ratio) / content_height * current_zoom
        return min(zoom_w, zoom_h)

    @staticmethod
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
        p = self._p
        if not p.overview_box_groups:
            return

        box_numbers = sorted(p.overview_box_groups.keys())
        if not box_numbers:
            return

        first_box = p.overview_box_groups[box_numbers[0]]
        viewport = p.ov_scroll.viewport()
        viewport_width = viewport.width()
        viewport_height = viewport.height()
        target_zoom = self._calc_fit_zoom(
            p._zoom_level,
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
        p = self._p
        if not p.overview_box_groups:
            return

        viewport = p.ov_scroll.viewport()
        content = p.ov_boxes_widget
        viewport_width = viewport.width()
        viewport_height = viewport.height()
        target_zoom = self._calc_fit_zoom(
            p._zoom_level,
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
        p = self._p
        while p._box_nav_layout.count():
            item = p._box_nav_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for box_num in box_numbers:
            btn = QPushButton(str(box_num))
            btn.setFixedSize(24, 24)
            btn.setObjectName("overviewBoxNavButton")
            btn.setToolTip(t("overview.jumpToBox", box=box_num))
            btn.clicked.connect(lambda checked=False, b=box_num: self._jump_to_box(b))
            p._box_nav_layout.addWidget(btn)

    def _jump_to_box(self, box_num):
        """Jump to specific box with animated scroll and zoom."""
        p = self._p
        box_group = p.overview_box_groups.get(box_num)
        if not box_group:
            return

        viewport = p.ov_scroll.viewport()
        viewport_width = viewport.width()
        viewport_height = viewport.height()
        target_zoom = self._calc_fit_zoom(
            p._zoom_level,
            viewport_width,
            viewport_height,
            box_group.sizeHint().width(),
            box_group.sizeHint().height(),
            0.85,
        )
        if target_zoom is None:
            return

        if abs(target_zoom - p._zoom_level) > 0.15:
            self._set_zoom(target_zoom, animated=True)
            self._schedule_center_scroll(box_group, viewport_width, viewport_height)
            return

        target_h, target_v = self._calc_center_scroll_targets(
            box_group,
            viewport_width,
            viewport_height,
        )
        self._animate_scroll_to(target_h, target_v)
