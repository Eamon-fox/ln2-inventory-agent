"""Activity indicator widget for showing agent processing state.

Displays a pulsing dot animation, elapsed time, and current tool name
to give the user visual feedback that the agent is still working.
"""

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel

from app_gui.i18n import tr


# ---------------------------------------------------------------------------
# Pulsing dot indicator (lightweight custom paint, no extra threads)
# ---------------------------------------------------------------------------

class PulsingDot(QWidget):
    """A small dot that fades in/out via opacity animation."""

    _DOT_RADIUS = 4
    _WIDGET_SIZE = 14

    def __init__(self, color: str = "#38bdf8", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._opacity: float = 1.0
        self.setFixedSize(self._WIDGET_SIZE, self._WIDGET_SIZE)

        self._animation = QPropertyAnimation(self, b"dot_opacity")
        self._animation.setDuration(900)
        self._animation.setStartValue(0.25)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.InOutSine)
        self._animation.setLoopCount(-1)  # infinite loop

    # --- Qt property for animation binding ---
    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    dot_opacity = Property(float, _get_opacity, _set_opacity)

    # --- public API ---
    def start(self) -> None:
        self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self._opacity = 1.0
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    # --- painting ---
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.NoPen))
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setBrush(color)
        cx = self.width() / 2
        cy = self.height() / 2
        painter.drawEllipse(
            int(cx - self._DOT_RADIUS),
            int(cy - self._DOT_RADIUS),
            self._DOT_RADIUS * 2,
            self._DOT_RADIUS * 2,
        )
        painter.end()


# ---------------------------------------------------------------------------
# Composite activity indicator bar
# ---------------------------------------------------------------------------

def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string (e.g. '5s', '1m 23s')."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    secs = total % 60
    return f"{minutes}m {secs:02d}s"


class ActivityIndicator(QWidget):
    """Horizontal bar: [pulsing dot] [status text] [elapsed time].

    Usage:
        indicator.start("Thinking...")
        indicator.set_tool_name("search_records")
        indicator.stop()
    """

    _TICK_INTERVAL_MS = 1000  # update elapsed label every second

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._start_time: float = 0.0
        self._tool_name: str = ""
        self._running: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._dot = PulsingDot(parent=self)
        layout.addWidget(self._dot)

        self._status_label = QLabel("")
        self._status_label.setObjectName("activityStatusLabel")
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._elapsed_label = QLabel("")
        self._elapsed_label.setObjectName("activityElapsedLabel")
        self._elapsed_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._elapsed_label)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self._TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._update_elapsed)

        self.setVisible(False)

    # --- public API ---

    def start(self, status_text: str = "") -> None:
        """Begin showing the indicator with a status message."""
        self._start_time = time.monotonic()
        self._tool_name = ""
        self._running = True
        text = status_text or tr("ai.activityThinking")
        self._status_label.setText(text)
        self._elapsed_label.setText(_format_elapsed(0))
        self._dot.start()
        self._tick_timer.start()
        self.setVisible(True)

    def stop(self) -> None:
        """Hide the indicator and stop all animations."""
        self._tick_timer.stop()
        self._dot.stop()
        self._tool_name = ""
        self._running = False
        self.setVisible(False)

    def set_tool_name(self, name: str) -> None:
        """Update the status label to show the running tool name."""
        self._tool_name = str(name or "").strip()
        if self._tool_name:
            text = tr("ai.activityRunningTool").format(tool=self._tool_name)
        else:
            text = tr("ai.activityThinking")
        self._status_label.setText(text)

    def elapsed_seconds(self) -> float:
        """Return seconds since start() was called."""
        if self._start_time <= 0:
            return 0.0
        return time.monotonic() - self._start_time

    def is_active(self) -> bool:
        """Return True when the indicator is currently running."""
        return self._running

    # --- private ---

    def _update_elapsed(self) -> None:
        elapsed = self.elapsed_seconds()
        self._elapsed_label.setText(_format_elapsed(elapsed))
