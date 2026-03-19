"""Reusable SVG watermark overlay widget for panel decorations."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel

from app_gui.ui.theme import resolve_theme_token


class SvgWatermarkLabel(QLabel):
    """Render a tinted SVG watermark with fixed opacity and right-top anchoring."""

    def __init__(
        self,
        parent=None,
        *,
        opacity=0.07,
        target_ratio=0.24,
        min_width=96,
        max_width=180,
        margin_top=12,
        margin_right=12,
    ):
        super().__init__(parent)
        self._renderer = None
        self._svg_path = ""
        self._opacity = self._clamp_float(opacity, 0.0, 1.0)
        self._target_ratio = max(0.0, float(target_ratio))
        self._min_width = max(1, int(min_width))
        self._max_width = max(self._min_width, int(max_width))
        self._margin_top = max(0, int(margin_top))
        self._margin_right = max(0, int(margin_right))
        self._tint_color = QColor(resolve_theme_token("watermark-tint", fallback="#94a3b8"))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAlignment(Qt.AlignCenter)
        self.hide()

    @staticmethod
    def _clamp_float(value, minimum, maximum):
        num = float(value)
        return max(float(minimum), min(float(maximum), num))

    def set_opacity(self, value):
        opacity = self._clamp_float(value, 0.0, 1.0)
        if abs(opacity - self._opacity) < 1e-6:
            return
        self._opacity = opacity
        self.refresh_pixmap()

    def set_tint_color(self, color):
        tint = QColor(color)
        if not tint.isValid():
            return
        self._tint_color = tint
        self.refresh_pixmap()

    def set_svg_path(self, path):
        svg_path = str(path or "").strip()
        if not svg_path:
            self._svg_path = ""
            self._renderer = None
            self.clear()
            self.hide()
            return False

        if svg_path == self._svg_path and self._renderer is not None and self._renderer.isValid():
            return True

        renderer = QSvgRenderer(svg_path)
        if not renderer.isValid():
            self._svg_path = ""
            self._renderer = None
            self.clear()
            self.hide()
            return False

        self._svg_path = svg_path
        self._renderer = renderer
        self.refresh_pixmap()
        return True

    def _aspect_ratio(self):
        renderer = self._renderer
        if renderer is None:
            return 1.0

        view_box = renderer.viewBoxF()
        if view_box.width() > 0 and view_box.height() > 0:
            return float(view_box.height()) / float(view_box.width())

        default_size = renderer.defaultSize()
        if default_size.width() > 0 and default_size.height() > 0:
            return float(default_size.height()) / float(default_size.width())

        return 1.0

    def update_geometry_for(self, parent_rect):
        if parent_rect is None:
            return

        parent_width = max(0, int(parent_rect.width()))
        parent_height = max(0, int(parent_rect.height()))
        if parent_width <= 0 or parent_height <= 0:
            return

        target_width = int(round(parent_width * self._target_ratio))
        target_width = max(self._min_width, min(self._max_width, target_width))
        target_height = max(1, int(round(target_width * self._aspect_ratio())))

        max_height = max(1, parent_height - (self._margin_top * 2))
        if target_height > max_height:
            scale = float(max_height) / float(target_height)
            target_height = max(1, int(round(target_height * scale)))
            target_width = max(1, int(round(target_width * scale)))

        x_pos = int(parent_rect.x()) + parent_width - self._margin_right - target_width
        y_pos = int(parent_rect.y()) + self._margin_top
        x_pos = max(int(parent_rect.x()), x_pos)
        y_pos = max(int(parent_rect.y()), y_pos)

        self.setGeometry(x_pos, y_pos, target_width, target_height)
        self.refresh_pixmap()

    def refresh_pixmap(self):
        renderer = self._renderer
        if renderer is None or not renderer.isValid():
            self.clear()
            return

        width = int(self.width())
        height = int(self.height())
        if width <= 0 or height <= 0:
            self.clear()
            return

        base = QPixmap(width, height)
        base.fill(Qt.transparent)

        painter = QPainter(base)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(painter)
        painter.end()

        tinted = QPixmap(width, height)
        tinted.fill(Qt.transparent)

        tint_painter = QPainter(tinted)
        tint_painter.setRenderHint(QPainter.Antialiasing, True)
        tint_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        tint_painter.drawPixmap(0, 0, base)
        tint_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        color = QColor(self._tint_color)
        color.setAlphaF(self._opacity)
        tint_painter.fillRect(tinted.rect(), color)
        tint_painter.end()

        self.setPixmap(tinted)

