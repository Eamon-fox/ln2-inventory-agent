"""Runtime and worker lifecycle helpers for AIPanel."""

import json

from PySide6.QtCore import QThread

from app_gui.error_localizer import localize_error_payload
from app_gui.event_compactor import compact_operation_event_for_context
from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon
from app_gui.ui.utils import compact_json
from app_gui.ui.workers import AgentRunWorker


def _append_assistant_history_once(panel, text):
    content = str(text or "").strip()
    if not content:
        return
    if panel.ai_history:
        last = panel.ai_history[-1]
        if isinstance(last, dict):
            if str(last.get("role") or "") == "assistant" and str(last.get("content") or "").strip() == content:
                return
    panel._append_history("assistant", content)


def _on_run_stop_toggle(self):
    """Toggle between run and stop based on current state."""
    if self.ai_run_inflight:
        self.on_stop_ai_agent()
    else:
        self.on_run_ai_agent()


def on_run_ai_agent(self):
    if self.ai_run_inflight:
        return
    if self.ai_stop_requested:
        thread = getattr(self, "ai_run_thread", None)
        if thread is not None and thread.isRunning():
            self.status_message.emit(tr("ai.aiRunStopped"), 1500)
            return
        self.ai_stop_requested = False

    prompt = self.ai_prompt.toPlainText().strip()
    if not prompt:
        self.status_message.emit(tr("ai.enterPrompt"), 2000)
        return

    self._append_chat("You", prompt)
    self._append_history("user", prompt)
    self.ai_prompt.clear()
    self.ai_active_trace_id = None
    if self.ai_streaming_active:
        self._end_stream_chat()
    self.ai_streaming_active = False
    self.ai_stream_buffer = ""
    self.ai_stream_start_pos = None
    self.ai_last_stream_block = None
    self.ai_stream_last_render_ts = 0.0
    self.ai_stream_last_render_len = 0
    self._reset_stream_thought_state()
    self.status_message.emit(tr("ai.agentThinking"), 2000)

    self.start_worker(prompt)


def start_worker(self, prompt):
    self.ai_stop_requested = False
    model = self.ai_model.text().strip() or None
    history = [dict(item) for item in self.ai_history if isinstance(item, dict)]

    if self.ai_operation_events:
        recent_events = self.ai_operation_events[-5:]
        context_events = [compact_operation_event_for_context(event) for event in recent_events]
        context_msg = json.dumps(context_events, ensure_ascii=False, separators=(",", ":"))
        history.append({"role": "user", "content": f"[Operation Results]\n{context_msg}"})

    self.ai_run_worker = AgentRunWorker(
        bridge=self.bridge,
        yaml_path=self.yaml_path_getter(),
        query=prompt,
        model=model,
        max_steps=self.ai_steps.value(),
        history=history,
        thinking_enabled=self.ai_thinking_enabled.isChecked(),
        custom_prompt=self.ai_custom_prompt,
        plan_store=self._plan_store,
        provider=self.ai_provider.text().strip() or None,
    )
    self.ai_run_thread = QThread(self)
    self.ai_run_worker.moveToThread(self.ai_run_thread)

    self.ai_run_thread.started.connect(self.ai_run_worker.run)
    self.ai_run_worker.progress.connect(self.on_progress)
    self.ai_run_worker.question_asked.connect(self._handle_question_event)
    self.ai_run_worker.finished.connect(self.on_finished)
    self.ai_run_worker.finished.connect(self.ai_run_thread.quit)
    self.ai_run_worker.finished.connect(self.ai_run_worker.deleteLater)
    self.ai_run_thread.finished.connect(self.ai_run_thread.deleteLater)
    self.ai_run_thread.finished.connect(self.on_thread_finished)

    self.set_busy(True)
    self.ai_run_thread.start()


def _handle_question_event(self, event_data):
    """Handle question event from agent: show dialog and unblock worker."""
    if self.ai_stop_requested:
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    if event_data.get("type") == "manage_boxes_confirm":
        return self._handle_manage_boxes_confirm(event_data)

    if event_data.get("type") == "max_steps_ask":
        return self._handle_max_steps_ask(event_data)

    question_text = str(event_data.get("question") or "").strip()
    options_raw = event_data.get("options") or []
    options = [
        str(item).strip()
        for item in options_raw
        if isinstance(item, str) and str(item).strip()
    ]
    if not question_text or len(options) < 2:
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    if self.ai_streaming_active:
        self._end_stream_chat()
    self._append_tool_message(tr("ai.questionAsking"))

    answer = self._show_question_dialog(question_text, options)

    if answer is not None:
        if self.ai_run_worker:
            self.ai_run_worker.set_answer(answer)
    else:
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()


def _handle_manage_boxes_confirm(self, event_data):
    """Handle GUI confirmation request for manage_boxes tool."""
    request = event_data.get("request") if isinstance(event_data, dict) else None
    if not isinstance(request, dict):
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    if not callable(self._manage_boxes_request_handler):
        self._append_tool_message("`manage_boxes` needs GUI confirmation, but no handler is available.")
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    try:
        result = self._manage_boxes_request_handler(request)
    except Exception as exc:
        result = {
            "ok": False,
            "error_code": "gui_confirmation_failed",
            "message": str(exc),
        }

    if not isinstance(result, dict):
        if self.ai_run_worker:
            self.ai_run_worker.cancel_answer()
        return

    if self.ai_run_worker:
        self.ai_run_worker.set_answer(result)


def _handle_max_steps_ask(self, event_data):
    """System prompt when max_steps is reached, asks user to continue or stop."""
    from PySide6.QtWidgets import QMessageBox

    steps = event_data.get("steps", 0)

    if self.ai_streaming_active:
        self._end_stream_chat()

    reply = QMessageBox.question(
        self,
        tr("ai.maxStepsTitle"),
        tr("ai.maxStepsMessage").format(steps=steps),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )

    if reply == QMessageBox.Yes and self.ai_run_worker:
        self.ai_run_worker.set_answer(["continue"])
    elif self.ai_run_worker:
        self.ai_run_worker.cancel_answer()


def _show_question_dialog(self, question_text, options):
    """Modal dialog for one clarifying question with single-choice options."""
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QLabel,
        QVBoxLayout,
    )

    dialog = QDialog(self)
    dialog.setWindowTitle(tr("ai.questionTitle"))
    dialog.setMinimumWidth(400)
    layout = QVBoxLayout(dialog)

    label = QLabel(str(question_text or ""))
    label.setWordWrap(True)
    layout.addWidget(label)

    combo = QComboBox()
    combo.addItems(list(options or []))
    layout.addWidget(combo)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() == QDialog.Accepted:
        return combo.currentText()
    return None


def on_stop_ai_agent(self):
    if not self.ai_run_inflight:
        return

    self.ai_stop_requested = True
    if self.ai_run_worker is not None and hasattr(self.ai_run_worker, "request_stop"):
        try:
            self.ai_run_worker.request_stop()
        except Exception:
            pass

    if self.ai_streaming_active:
        self._end_stream_chat()
    self._append_chat("System", tr("ai.runStopped"))
    self.status_message.emit(tr("ai.aiRunStopped"), 3000)
    # Keep worker alive for cooperative shutdown; ignore late progress/final callbacks.
    self.set_busy(False)


def set_busy(self, busy):
    self.ai_run_inflight = busy
    if busy:
        # Show stop button state - use default icon color (no color param)
        self.ai_run_btn.setText(tr("ai.stop"))
        self.ai_run_btn.setIcon(get_icon(Icons.SQUARE))
        self.ai_run_btn.setProperty("variant", None)
        self.ai_run_btn.style().unpolish(self.ai_run_btn)
        self.ai_run_btn.style().polish(self.ai_run_btn)
    else:
        # Show run button state - white icon for primary variant
        self.ai_run_btn.setText(tr("ai.runAgent"))
        self.ai_run_btn.setIcon(get_icon(Icons.PLAY, color="#ffffff"))
        self.ai_run_btn.setProperty("variant", "primary")
        self.ai_run_btn.style().unpolish(self.ai_run_btn)
        self.ai_run_btn.style().polish(self.ai_run_btn)
    self.ai_run_btn.setEnabled(True)
    if hasattr(self, "ai_model_switch_btn"):
        self.ai_model_switch_btn.setEnabled((not busy) and bool(self._iter_model_switch_options()))


def on_progress(self, event):
    if self.ai_stop_requested:
        return

    event_type = str(event.get("event") or event.get("type") or "").strip()
    trace_id = event.get("trace_id")

    if event_type == "run_start":
        self.ai_active_trace_id = event.get("trace_id")
        return

    if self.ai_active_trace_id and trace_id and trace_id != self.ai_active_trace_id:
        return

    handlers = {
        "tool_end": self._handle_progress_tool_end,
        "tool_start": self._handle_progress_tool_start,
        "chunk": self._handle_progress_chunk,
        "error": self._handle_progress_error,
        "stream_end": self._handle_progress_stream_end,
        "step_end": self._handle_progress_step_end,
        "max_steps": self._handle_progress_max_steps,
    }
    handler = handlers.get(event_type)
    if callable(handler):
        handler(event)


def _extract_progress_observation(self, event):
    data = event.get("data") or {}
    raw_output = (data.get("output") or {}).get("content")
    raw_obs = event.get("observation")
    if isinstance(raw_obs, dict):
        return raw_obs
    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _handle_progress_tool_end(self, event):
    data = event.get("data") or {}
    name = str(data.get("name") or event.get("action") or "tool")
    raw_obs = self._extract_progress_observation(event)
    status = "OK" if raw_obs.get("ok") else "FAIL"
    hint = raw_obs.get("_hint")

    self._append_tool_message(f"`{name}` finished: **{status}**")
    if hint:
        self._append_tool_message(f"Hint: {hint}")

    blocked_items = raw_obs.get("blocked_items")
    if isinstance(blocked_items, list) and blocked_items:
        summary_text = self._blocked_items_summary(name, blocked_items)
        details_json = json.dumps(
            {
                "tool": name,
                "error_code": raw_obs.get("error_code"),
                "message": raw_obs.get("message"),
                "blocked_items": blocked_items,
            },
            ensure_ascii=False,
            indent=2,
        )
        self._append_chat_with_collapsible("System", summary_text, details_json)


def _handle_progress_tool_start(self, event):
    if self.ai_streaming_active:
        self._end_stream_chat()

    data = event.get("data") or {}
    name = str(data.get("name") or event.get("action") or "tool")
    self._append_tool_message(f"Running `{name}`...")


def _handle_progress_chunk(self, event):
    chunk = event.get("data")
    channel = str(((event.get("meta") or {}).get("channel") or "answer")).strip().lower()
    if isinstance(chunk, str) and chunk:
        self._append_stream_chunk(chunk, channel=channel)


def _handle_progress_step_end(self, event):
    # Parse step_end payload for compatibility with legacy producer fields.
    step = event.get("step")
    action = str(event.get("action") or "tool")
    raw_obs = event.get("observation") or {}
    status = "OK" if raw_obs.get("ok") else "FAIL"
    summary = raw_obs.get("message")
    if not raw_obs.get("ok"):
        summary = localize_error_payload(raw_obs, fallback=summary or "")
    hint = raw_obs.get("_hint")
    if not summary and raw_obs.get("result"):
        summary = compact_json(raw_obs.get("result"), 120)

    line = f"Step {step}: {action} -> {status}"
    if summary:
        line += f" | {summary}"
    if hint:
        line += f" | hint: {hint}"
    _ = line


def _handle_progress_error(event):
    err = event.get("data") or event.get("message") or "unknown error"
    _ = err


def _handle_progress_stream_end(event):
    status = (event.get("data") or {}).get("status")
    _ = status


def _handle_progress_max_steps(_event):
    return


def on_finished(self, response):
    if self.ai_stop_requested:
        response = response if isinstance(response, dict) else {}
        raw_result = response.get("result")
        if not isinstance(raw_result, dict):
            raw_result = {}

        stop_note = str(raw_result.get("final") or response.get("message") or tr("ai.runStopped")).strip()
        stop_note = stop_note.replace("**", "").strip()

        streamed_text = self.ai_stream_buffer.strip()
        if self.ai_streaming_active:
            self._end_stream_chat()
            streamed_text = str((self.ai_last_stream_block or {}).get("text") or "").strip()

        if streamed_text:
            _append_assistant_history_once(self, streamed_text)
        if stop_note:
            _append_assistant_history_once(self, stop_note)

        self.set_busy(False)
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self._reset_stream_thought_state()
        self.operation_completed.emit(False)
        return

    self.set_busy(False)
    response = response if isinstance(response, dict) else {}

    raw_result = response.get("result")
    protocol_error = False
    if not isinstance(raw_result, dict):
        raw_result = {}
        protocol_error = bool(response.get("ok"))

    if protocol_error:
        final_text = "Internal protocol error: missing result payload."
    else:
        final_text = str(raw_result.get("final") or response.get("message") or "").strip()
    if not final_text:
        final_text = "Agent finished without a final message."

    had_thought_stream = bool(self.ai_stream_has_thought)
    streamed_text = self.ai_stream_buffer.strip()
    if self.ai_streaming_active:
        self._end_stream_chat()
        streamed_text = str((self.ai_last_stream_block or {}).get("text") or "").strip()

    used_stream_markdown_rewrite = False
    if streamed_text and final_text.strip() == streamed_text and not had_thought_stream:
        used_stream_markdown_rewrite = self._replace_stream_block_with_markdown(
            self.ai_last_stream_block,
            final_text,
        )

    if not streamed_text:
        self._append_chat("Agent", final_text)
    elif final_text.strip() != streamed_text:
        # Keep a final canonical message if streamed chunks differ.
        self._append_chat("Agent", final_text)
    elif not used_stream_markdown_rewrite:
        # Could not rewrite in-place (e.g. limited chat stub); avoid duplicate append.
        pass

    self.ai_stream_buffer = ""
    self.ai_stream_start_pos = None
    self.ai_last_stream_block = None
    self.ai_stream_last_render_ts = 0.0
    self.ai_stream_last_render_len = 0
    self._reset_stream_thought_state()
    self._append_history("assistant", final_text)

    if response.get("error_code") == "api_key_required":
        self.status_message.emit("API key missing. See chat for setup steps.", 6000)

    self.operation_completed.emit(bool(response.get("ok")))

    trace_id = raw_result.get("trace_id")
    self._load_audit(trace_id, raw_result)


def on_thread_finished(self):
    self.ai_stop_requested = False
    self.ai_run_thread = None
    self.ai_run_worker = None
