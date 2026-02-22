import threading

from PySide6.QtCore import QObject, Signal

class AgentRunWorker(QObject):
    finished = Signal(dict)
    progress = Signal(dict)
    question_asked = Signal(dict)

    def __init__(self, bridge, yaml_path, query, model, max_steps, history,
                 thinking_enabled=True, custom_prompt="", plan_store=None, provider=None):
        super().__init__()
        self._bridge = bridge
        self._yaml_path = yaml_path
        self._query = query
        self._model = model
        self._max_steps = max_steps
        self._history = history
        self._thinking_enabled = bool(thinking_enabled)
        self._custom_prompt = str(custom_prompt or "")
        self._plan_store = plan_store
        self._provider = provider
        self._tool_runner = None
        self._llm_client = None
        self._stop_event = threading.Event()

    def _receive_runner(self, runner):
        """Callback from bridge to capture tool_runner reference."""
        self._tool_runner = runner

    def _receive_llm(self, llm_client):
        """Callback from bridge to capture active llm client reference."""
        self._llm_client = llm_client

    def set_answer(self, answers):
        """Thread-safe: called from GUI main thread to provide user answers."""
        if self._tool_runner:
            self._tool_runner._set_answer(answers)

    def cancel_answer(self):
        """Thread-safe: called from GUI main thread when user cancels."""
        if self._tool_runner:
            self._tool_runner._cancel_answer()

    def request_stop(self):
        """Thread-safe cooperative stop requested by GUI."""
        self._stop_event.set()
        if self._llm_client and hasattr(self._llm_client, "request_stop"):
            try:
                self._llm_client.request_stop()
            except Exception:
                pass
        if self._tool_runner:
            # Unblock any pending question wait immediately.
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
                plan_store=self._plan_store,
                thinking_enabled=self._thinking_enabled,
                custom_prompt=self._custom_prompt,
                _expose_runner=self._receive_runner,
                _expose_llm=self._receive_llm,
                provider=self._provider,
                stop_event=self._stop_event,
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
        if self._stop_event.is_set():
            return
        if not isinstance(event, dict):
            return
        if event.get("type") in ("question", "max_steps_ask", "manage_boxes_confirm"):
            self.question_asked.emit(event)
        else:
            self.progress.emit(event)
