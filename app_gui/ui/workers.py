from PySide6.QtCore import QObject, Signal

class AgentRunWorker(QObject):
    finished = Signal(dict)
    progress = Signal(dict)

    def __init__(self, bridge, yaml_path, query, model, max_steps, mock, history):
        super().__init__()
        self._bridge = bridge
        self._yaml_path = yaml_path
        self._query = query
        self._model = model
        self._max_steps = max_steps
        self._mock = mock
        self._history = history

    def run(self):
        try:
            payload = self._bridge.run_agent_query(
                yaml_path=self._yaml_path,
                query=self._query,
                model=self._model,
                max_steps=self._max_steps,
                mock=self._mock,
                history=self._history,
                on_event=self._emit_progress,
            )
            if not isinstance(payload, dict):
                payload = {"ok": False, "message": "Unexpected response"}
        except Exception as exc:
            payload = {
                "ok": False,
                "error_code": "agent_runtime_failed",
                "message": str(exc),
                "result": None,
            }
        self.finished.emit(payload)

    def _emit_progress(self, event):
        if not isinstance(event, dict):
            return
        self.progress.emit(event)
