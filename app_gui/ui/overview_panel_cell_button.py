"""Cell widget used by OverviewPanel grid mode."""

from PySide6.QtCore import QEasingCurve, QMimeData, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter, QPalette, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionButton

MIME_TYPE_MOVE = "application/x-ln2-move"
_ELLIPSIS_TEXT = "..."
_CELL_TEXT_MODE_DEFAULT = "default"
_CELL_TEXT_MODE_WRAPPED = "wrapped"
_SELECTION_EDGE_ORDER = ("top", "right", "bottom", "left")


def _normalize_cell_text(text):
    normalized = str(text or "").replace("\r", "\n")
    parts = normalized.split()
    return " ".join(parts)


def _ascii_elide_text(text, font_metrics, max_width):
    normalized = _normalize_cell_text(text)
    if max_width <= 0 or not normalized:
        return ""
    if font_metrics.horizontalAdvance(normalized) <= max_width:
        return normalized

    ellipsis = _ELLIPSIS_TEXT
    while ellipsis and font_metrics.horizontalAdvance(ellipsis) > max_width:
        ellipsis = ellipsis[:-1]
    if not ellipsis:
        return ""

    low = 0
    high = len(normalized)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = normalized[:mid].rstrip()
        if candidate:
            candidate = f"{candidate}{ellipsis}"
        else:
            candidate = ellipsis
        if font_metrics.horizontalAdvance(candidate) <= max_width:
            low = mid
        else:
            high = mid - 1

    prefix = normalized[:low].rstrip()
    return f"{prefix}{ellipsis}" if prefix else ellipsis


def _wrap_cell_text_lines(text, font, max_width, max_lines):
    normalized = _normalize_cell_text(text)
    if max_width <= 0 or max_lines <= 0 or not normalized:
        return []

    font_metrics = QFontMetrics(font)
    if max_lines == 1:
        return [_ascii_elide_text(normalized, font_metrics, max_width)]

    text_layout = QTextLayout(normalized, font)
    text_option = QTextOption()
    text_option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    text_layout.setTextOption(text_option)

    ranges = []
    text_layout.beginLayout()
    try:
        while len(ranges) < max_lines:
            line = text_layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(float(max_width))
            ranges.append((line.textStart(), line.textLength()))
    finally:
        text_layout.endLayout()

    if not ranges:
        return []

    lines = []
    for start, length in ranges:
        lines.append(normalized[start : start + length].strip())

    last_start, last_length = ranges[-1]
    rendered_end = last_start + last_length
    if rendered_end < len(normalized):
        lines[-1] = _ascii_elide_text(normalized[last_start:], font_metrics, max_width)

    return [line for line in lines if line]


class CellButton(QPushButton):
    doubleClicked = Signal(int, int)
    dropReceived = Signal(int, int, int, int, int)

    def __init__(self, text, box, pos, parent=None):
        super().__init__(text, parent)
        self.box = box
        self.pos = pos
        self.record_id = None
        self.setAcceptDrops(True)
        self._drag_start_pos = None
        self._last_mouse_modifiers = Qt.NoModifier
        # Keep hover feedback snappy; long animations feel laggy in dense grids.
        self._hover_duration_ms = 80
        self._hover_scale = 1.08
        self._base_rect = QRect()
        self._is_hovered = False
        self._hover_anim = None
        self._hover_anim_on_finished = None
        self._hover_proxy = None
        self._selection_outer_proxy = None
        self._selection_inner_proxy = None
        self._selection_visible = False
        self._selection_active = False
        self._selection_edges = ()
        self._selection_color = QColor("#63b3ff")
        self._operation_marker = ""
        self._operation_move_id = None
        self._text_display_mode = _CELL_TEXT_MODE_DEFAULT
        self.setProperty("cell_text_mode", self._text_display_mode)
        self._operation_badge = QLabel(self)
        self._operation_badge.setObjectName("OverviewCellOperationBadge")
        self._operation_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._operation_badge.hide()

    def set_record_id(self, record_id):
        self.record_id = record_id

    def last_click_modifiers(self):
        return self._last_mouse_modifiers

    def _scaled_rect(self):
        if not self._base_rect.isValid() or self._base_rect.width() <= 0 or self._base_rect.height() <= 0:
            return QRect()
        width = max(1, int(round(self._base_rect.width() * self._hover_scale)))
        height = max(1, int(round(self._base_rect.height() * self._hover_scale)))
        dx = (width - self._base_rect.width()) // 2
        dy = (height - self._base_rect.height()) // 2
        return QRect(self._base_rect.x() - dx, self._base_rect.y() - dy, width, height)

    def _ensure_hover_proxy(self):
        if self._hover_proxy is not None:
            return self._hover_proxy
        parent = self.parentWidget() or self
        proxy = CellButton("", self.box, self.pos, parent)
        proxy.setObjectName("OverviewCellHoverProxy")
        proxy.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        proxy.setFocusPolicy(Qt.NoFocus)
        proxy.hide()
        self._hover_anim = QPropertyAnimation(proxy, b"geometry", proxy)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.finished.connect(self._on_hover_animation_finished)
        self._hover_proxy = proxy
        return proxy

    def _on_hover_animation_finished(self):
        callback = self._hover_anim_on_finished
        self._hover_anim_on_finished = None
        if callback is not None:
            callback()

    def _sync_hover_proxy(self):
        proxy = self._ensure_hover_proxy()
        proxy.setText(self.text())
        proxy.setStyleSheet(self.styleSheet())
        proxy.setToolTip(self.toolTip())
        proxy.setFont(self.font())
        proxy.set_text_display_mode(self._text_display_mode)
        proxy.setProperty("is_empty", self.property("is_empty"))
        proxy.setProperty("display_label_full", self.property("display_label_full"))
        proxy.setProperty("position_label", self.property("position_label"))
        proxy.set_record_id(self.record_id)
        proxy.set_operation_marker(self._operation_marker, self._operation_move_id)
        proxy._set_selection_visual_state(
            selected=self._selection_visible,
            ring_color=self._selection_color,
            active=self._selection_active,
            edge_mask=self._selection_edges,
            update=False,
        )
        proxy.setGeometry(self._base_rect)

    @staticmethod
    def _normalize_selection_edges(edge_mask):
        if not edge_mask:
            return ()
        normalized = []
        for raw_edge in edge_mask:
            edge = str(raw_edge or "").strip().lower()
            if edge in _SELECTION_EDGE_ORDER and edge not in normalized:
                normalized.append(edge)
        return tuple(normalized)

    def _set_selection_visual_state(self, *, selected=False, ring_color="", active=False, edge_mask=None, update=True):
        color = ring_color if isinstance(ring_color, QColor) else QColor(str(ring_color or "").strip())
        if not color.isValid():
            color = QColor("#63b3ff")

        self._selection_visible = bool(selected)
        self._selection_active = bool(selected and active)
        self._selection_edges = (
            self._normalize_selection_edges(edge_mask)
            if self._selection_visible
            else ()
        )
        self._selection_color = QColor(color)
        self.setProperty("selection_active", self._selection_active)
        self.setProperty("selection_edges", ",".join(self._selection_edges))
        if update:
            self.update()

    def _selection_overlay_rect(self):
        inset = max(1, min(3, min(self.width(), self.height()) // 10))
        rect = self.rect().adjusted(inset, inset, -inset, -inset)
        if rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        return rect

    def _selection_active_rect(self):
        inset = max(3, min(6, min(self.width(), self.height()) // 5))
        rect = self.rect().adjusted(inset, inset, -inset, -inset)
        if rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        return rect

    def _paint_selection_overlay(self, painter):
        if not self._selection_visible:
            return

        color = QColor(self._selection_color)
        if not color.isValid():
            color = QColor("#63b3ff")

        overlay_rect = self._selection_overlay_rect()
        if not overlay_rect.isValid():
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        is_empty = bool(self.property("is_empty"))

        # --- Layer 1: Soft filled tint over the whole cell ---
        # This creates the "unified region" feel for contiguous selections.
        if is_empty:
            fill_color = QColor(color)
            fill_color.setAlpha(38 if self._selection_active else 25)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill_color)
            painter.drawRect(self.rect())

        # --- Layer 2: Exposed-edge contour lines ---
        # Drawn at the overlay_rect boundary on exposed edges only,
        # so adjacent selected cells merge into one visual block.
        if is_empty and self._selection_edges:
            edge_color = QColor(color)
            edge_color.setAlpha(160 if self._selection_active else 120)
            edge_pen = QPen(edge_color)
            edge_pen.setWidthF(1.5)
            edge_pen.setCapStyle(Qt.FlatCap)
            edge_pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(edge_pen)
            painter.setBrush(Qt.NoBrush)

            left = float(overlay_rect.left())
            top = float(overlay_rect.top())
            right = float(overlay_rect.right())
            bottom = float(overlay_rect.bottom())
            if "top" in self._selection_edges:
                painter.drawLine(left, top, right, top)
            if "right" in self._selection_edges:
                painter.drawLine(right, top, right, bottom)
            if "bottom" in self._selection_edges:
                painter.drawLine(left, bottom, right, bottom)
            if "left" in self._selection_edges:
                painter.drawLine(left, top, left, bottom)

        # --- Layer 3: Active cell accent ---
        # A small bottom-center indicator dot instead of a full inner rect,
        # so the active cell is distinguishable without being loud.
        if self._selection_active:
            dot_color = QColor(color)
            dot_color.setAlpha(200)
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot_color)
            dot_radius = max(1.5, min(3.0, min(self.width(), self.height()) / 14.0))
            cx = self.rect().center().x()
            cy = self.rect().bottom() - dot_radius - max(2.0, self.height() * 0.08)
            painter.drawEllipse(int(cx - dot_radius), int(cy - dot_radius),
                                int(dot_radius * 2), int(dot_radius * 2))

        painter.restore()

    def set_selection_ring(self, selected=False, ring_color="", *, active=False, edge_mask=None):
        normalized_edges = self._normalize_selection_edges(edge_mask)
        if bool(selected) and not normalized_edges:
            normalized_edges = _SELECTION_EDGE_ORDER

        self._set_selection_visual_state(
            selected=bool(selected),
            ring_color=ring_color,
            active=bool(active),
            edge_mask=normalized_edges,
        )

        hover_proxy = self._hover_proxy
        if hover_proxy is not None:
            hover_proxy._set_selection_visual_state(
                selected=bool(selected),
                ring_color=self._selection_color,
                active=bool(active),
                edge_mask=normalized_edges,
                update=hover_proxy.isVisible(),
            )

    def set_text_display_mode(self, mode):
        normalized = str(mode or "").strip().lower()
        target = _CELL_TEXT_MODE_WRAPPED if normalized == _CELL_TEXT_MODE_WRAPPED else _CELL_TEXT_MODE_DEFAULT
        if self._text_display_mode == target:
            return
        self._text_display_mode = target
        self.setProperty("cell_text_mode", target)
        self.update()

    def text_display_mode(self):
        return self._text_display_mode

    def _text_padding(self):
        rect = self.contentsRect()
        horizontal = max(3, min(8, rect.width() // 9))
        vertical = max(2, min(6, rect.height() // 9))
        return horizontal, vertical

    def _wrapped_text_rect(self, option):
        rect = self.style().subElementRect(QStyle.SE_PushButtonContents, option, self)
        horizontal_padding, vertical_padding = self._text_padding()
        rect = rect.adjusted(horizontal_padding, vertical_padding, -horizontal_padding, -vertical_padding)

        badge = self._operation_badge
        if badge is not None and badge.isVisible():
            badge_height = max(badge.height(), badge.sizeHint().height())
            rect.setBottom(max(rect.top(), rect.bottom() - badge_height - 2))

        if rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        return rect

    def _paint_wrapped_text(self, painter, option, text):
        text_rect = self._wrapped_text_rect(option)
        if not text_rect.isValid():
            return

        line_height = max(1, painter.fontMetrics().lineSpacing())
        max_lines = max(1, text_rect.height() // line_height)
        lines = _wrap_cell_text_lines(text, painter.font(), text_rect.width(), max_lines)
        if not lines:
            return

        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setPen(option.palette.color(QPalette.ButtonText))
        painter.setClipRect(text_rect)

        baseline_y = text_rect.top() + painter.fontMetrics().ascent()
        for index, line_text in enumerate(lines):
            painter.drawText(text_rect.left(), baseline_y + index * line_height, line_text)

        painter.restore()

    def paintEvent(self, event):
        if self._text_display_mode != _CELL_TEXT_MODE_WRAPPED:
            super().paintEvent(event)
            painter = QPainter(self)
            self._paint_selection_overlay(painter)
            return

        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        display_text = str(option.text or self.text() or "")
        option.text = ""
        self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
        self._paint_wrapped_text(painter, option, display_text)
        self._paint_selection_overlay(painter)

    @staticmethod
    def _badge_text_and_color(marker_type, move_id=None):
        marker = str(marker_type or "").strip().lower()
        if marker == "add":
            return "ADD", "#22c55e"
        if marker == "takeout":
            return "OUT", "#ef4444"
        if marker == "edit":
            return "EDT", "#06b6d4"
        if marker == "move-source":
            suffix = f"{int(move_id)}" if move_id not in (None, "") else "?"
            return f"M{suffix}F", "#63b3ff"
        if marker == "move-target":
            suffix = f"{int(move_id)}" if move_id not in (None, "") else "?"
            return f"M{suffix}T", "#63b3ff"
        return "", ""

    def _reposition_operation_badge(self):
        if self._operation_badge is None or not self._operation_badge.isVisible():
            return
        self._operation_badge.adjustSize()
        margin = 1
        x = max(margin, self.width() - self._operation_badge.width() - margin)
        y = max(margin, self.height() - self._operation_badge.height() - margin)
        self._operation_badge.move(x, y)

    def set_operation_marker(self, marker_type=None, move_id=None):
        marker = str(marker_type or "").strip().lower()
        self._operation_marker = marker
        try:
            self._operation_move_id = int(move_id) if move_id is not None else None
        except Exception:
            self._operation_move_id = None

        badge_text, badge_color = self._badge_text_and_color(marker, self._operation_move_id)
        if not badge_text:
            self._operation_badge.hide()
            self.setProperty("operation_marker", "")
            self.setProperty("operation_badge_text", "")
            self.update()
            return

        self.setProperty("operation_marker", marker)
        self.setProperty("operation_badge_text", badge_text)
        self._operation_badge.setText(badge_text)
        self._operation_badge.setStyleSheet(
            f"""
            QLabel#OverviewCellOperationBadge {{
                font-size: 7px;
                font-weight: 700;
                color: {badge_color};
                background-color: rgba(0, 0, 0, 180);
                border-radius: 2px;
                padding: 0px 2px;
            }}
            """
        )
        self._operation_badge.show()
        self._operation_badge.raise_()
        self._reposition_operation_badge()
        self.update()

    def _animate_proxy_to(self, rect, on_finished=None):
        proxy = self._hover_proxy
        if proxy is None or not rect.isValid():
            if on_finished is not None:
                on_finished()
            return
        animation = self._hover_anim
        if animation is None:
            self._ensure_hover_proxy()
            animation = self._hover_anim
        if animation is None:
            if on_finished is not None:
                on_finished()
            return
        animation.stop()
        self._hover_anim_on_finished = on_finished
        animation.setDuration(self._hover_duration_ms)
        animation.setStartValue(proxy.geometry())
        animation.setEndValue(rect)
        animation.start()

    def reset_hover_state(self, clear_base=False):
        if self._hover_anim is not None:
            self._hover_anim.stop()
        self._hover_anim_on_finished = None
        self._is_hovered = False
        if self._hover_proxy is not None:
            self._hover_proxy.hide()
        if clear_base:
            self._base_rect = QRect()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.box, self.pos)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self.start_hover_visual()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.stop_hover_visual()
        super().leaveEvent(event)

    def start_hover_visual(self):
        if not self.isVisible():
            return
        self._is_hovered = True
        rect = self.geometry()
        if rect.isValid() and rect.width() > 0 and rect.height() > 0:
            self._base_rect = QRect(rect)
        else:
            return
        self._sync_hover_proxy()
        self._hover_proxy.show()
        self._hover_proxy.raise_()
        target = self._scaled_rect()
        if target.isValid():
            self._animate_proxy_to(target)

    def stop_hover_visual(self):
        self._is_hovered = False
        proxy = self._hover_proxy
        if proxy is None:
            return
        # Avoid animating shrink-out on leave; many concurrent leave animations
        # cause perceived input lag when moving quickly across cells.
        if self._hover_anim is not None:
            self._hover_anim.stop()
        self._hover_anim_on_finished = None
        proxy.hide()

    def hideEvent(self, event):
        self.reset_hover_state()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_operation_badge()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._reposition_operation_badge()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
            self._last_mouse_modifiers = event.modifiers()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_mouse_modifiers = event.modifiers()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None or self.record_id is None:
            super().mouseMoveEvent(event)
            return

        if (event.pos() - self._drag_start_pos).manhattanLength() < 20:
            super().mouseMoveEvent(event)
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE_MOVE, f"{self.box}:{self.pos}:{self.record_id}".encode())
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)
        self._drag_start_pos = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE_MOVE):
            data = bytes(event.mimeData().data(MIME_TYPE_MOVE)).decode()
            parts = data.split(":")
            if len(parts) == 3:
                from_box = int(parts[0])
                from_pos = int(parts[1])
                record_id = int(parts[2])
                self.dropReceived.emit(from_box, from_pos, self.box, self.pos, record_id)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


__all__ = [
    "CellButton",
    "MIME_TYPE_MOVE",
    "_ascii_elide_text",
    "_wrap_cell_text_lines",
]
