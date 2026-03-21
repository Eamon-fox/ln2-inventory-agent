"""Qt main-thread dispatch helpers for local API GUI handoff."""

from __future__ import annotations

from queue import Empty, Queue

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot


class MainThreadDispatcher(QObject):
    """Run callables on the QObject thread and wait for the result."""

    _call_requested = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._call_requested.connect(self._execute, Qt.QueuedConnection)

    @Slot(object, object)
    def _execute(self, fn, queue_obj):
        try:
            result = fn()
        except Exception as exc:  # pragma: no cover - defensive transport guard
            queue_obj.put((False, exc))
            return
        queue_obj.put((True, result))

    def call(self, fn, *, timeout=5.0):
        if not callable(fn):
            raise TypeError("fn must be callable")
        if QThread.currentThread() == self.thread():
            return fn()

        queue_obj = Queue(maxsize=1)
        self._call_requested.emit(fn, queue_obj)
        try:
            ok, payload = queue_obj.get(timeout=float(timeout or 0))
        except Empty as exc:
            raise TimeoutError("Main-thread dispatch timed out") from exc
        if ok:
            return payload
        raise payload
