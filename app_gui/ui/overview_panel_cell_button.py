"""Cell widget used by OverviewPanel grid mode."""

from PySide6.QtCore import QEasingCurve, QMimeData, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QPushButton

MIME_TYPE_MOVE = "application/x-ln2-move"


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
        # Keep hover feedback snappy; long animations feel laggy in dense grids.
        self._hover_duration_ms = 80
        self._hover_scale = 1.08
        self._base_rect = QRect()
        self._is_hovered = False
        self._hover_anim = None
        self._hover_anim_on_finished = None
        self._hover_proxy = None

    def set_record_id(self, record_id):
        self.record_id = record_id

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
        proxy = QPushButton(parent)
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
        proxy.setGeometry(self._base_rect)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

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
