from PySide6.QtCore import QObject, Signal

class AgentRunWorker(QObject):
    finished = Signal(dict)
    progress = Signal(dict)
    plan_staged = Signal(list)
    question_asked = Signal(dict)

    def __init__(self, bridge, yaml_path, query, model, max_steps, history, thinking_enabled=True):
        super().__init__()
        self._bridge = bridge
        self._yaml_path = yaml_path
        self._query = query
        self._model = model
        self._max_steps = max_steps
        self._history = history
        self._thinking_enabled = bool(thinking_enabled)
        self._tool_runner = None

    def _plan_sink(self, item):
        """Thread-safe callback: emit plan item via Qt signal."""
        self.plan_staged.emit([item])

    def _receive_runner(self, runner):
        """Callback from bridge to capture tool_runner reference."""
        self._tool_runner = runner

    def set_answer(self, answers):
        """Thread-safe: called from GUI main thread to provide user answers."""
        if self._tool_runner:
            self._tool_runner._set_answer(answers)

    def cancel_answer(self):
        """Thread-safe: called from GUI main thread when user cancels."""
        if self._tool_runner:
            self._tool_runner._cancel_answer()

    def run(self):
        try:
            payload = self._bridge.run_agent_query(
                yaml_path=self._yaml_path,
                query=self._query,
                model=self._model,
                max_steps=self._max_steps,
                history=self._history,
                on_event=self._emit_progress,
                plan_sink=self._plan_sink,
                thinking_enabled=self._thinking_enabled,
                _expose_runner=self._receive_runner,
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
        if event.get("type") == "question":
            self.question_asked.emit(event)
        else:
            self.progress.emit(event)
