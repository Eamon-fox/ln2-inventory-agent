"""Runtime and worker lifecycle helpers for AIPanel."""

import json
from contextlib import suppress

from PySide6.QtCore import QThread, Qt

from app_gui.error_localizer import localize_error_payload
from app_gui.event_compactor import compact_operation_event_for_context
from app_gui.gui_config import AI_HISTORY_LIMIT, AI_OPERATION_CONTEXT_LIMIT
from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon
from app_gui.ui.utils import compact_json
from app_gui.ui.workers import AgentRunWorker

_MISSING = object()


def _on_run_stop_toggle(self):
    """Toggle between run and stop based on current state."""
    clear_attention = getattr(self, "_clear_run_button_attention", None)
    if callable(clear_attention):
        clear_attention()
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
            # Previous run can still be draining after stop is requested.
            # Re-issue cooperative stop, then detach stale worker/thread refs so
            # a new run can start immediately while late callbacks are ignored.
            worker = getattr(self, "ai_run_worker", None)
            if worker is not None and hasattr(worker, "request_stop"):
                try:
                    worker.request_stop()
                except Exception:
                    pass
            self.ai_run_thread = None
            self.ai_run_worker = None
        self.ai_stop_requested = False

    prompt = self.ai_prompt.toPlainText().strip()
    if not prompt:
        self.status_message.emit(tr("ai.enterPrompt"), 2000)
        return

    retry_turn_id = getattr(self, "_retry_existing_turn_id", None)
    self._begin_user_turn(
        prompt,
        reuse_turn_id=retry_turn_id,
        append_user=not bool(retry_turn_id),
    )
    self._retry_existing_turn_id = None
    self._current_user_prompt = prompt
    # Record prompt history for Up/Down key recall.
    if not self._prompt_history or self._prompt_history[-1] != prompt:
        self._prompt_history.append(prompt)
    self._prompt_history_index = -1
    self._history_snapshot_from_stream_end = False
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
        recent_events = self.ai_operation_events[-AI_OPERATION_CONTEXT_LIMIT:]
        context_events = [compact_operation_event_for_context(event) for event in recent_events]
        context_msg = json.dumps(context_events, ensure_ascii=False, separators=(",", ":"))
        history.append({"role": "user", "content": f"[Operation Results]\n{context_msg}"})

    self.ai_run_worker = AgentRunWorker(
        bridge=self.agent_session or self.bridge,
        yaml_path=self.yaml_path_getter(),
        query=prompt,
        model=model,
        max_steps=self.ai_steps.value(),
        history=history,
        summary_state=self.ai_summary_state,
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


def _show_nonblocking_ai_dialog(self, dialog):
    dialog.setAttribute(Qt.WA_DeleteOnClose, True)
    dialog.setWindowModality(Qt.NonModal)
    dialog.setModal(False)
    self._floating_dialog_refs.append(dialog)

    def _release_ref(_result=0):
        with suppress(ValueError):
            self._floating_dialog_refs.remove(dialog)

    dialog.finished.connect(_release_ref)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def _set_waiting_for_user_reply(self, waiting):
    prompt = getattr(self, "ai_prompt", None)
    if prompt is None:
        return
    prompt.setEnabled(not bool(waiting))


def _pending_ai_wait_matches(self, state):
    if not isinstance(state, dict):
        return False
    if self._pending_ai_dialog_state is not state:
        return False
    worker = state.get("worker")
    if worker is not None and worker is not self.ai_run_worker:
        return False
    trace_id = str(state.get("trace_id") or "").strip()
    active_trace_id = str(getattr(self, "ai_active_trace_id", "") or "").strip()
    if trace_id and active_trace_id and trace_id != active_trace_id:
        return False
    return True


def _begin_pending_ai_wait(self, *, worker=None, trace_id=None, closer=None):
    self._dismiss_pending_ai_wait(cancel_worker=True)
    state = {
        "worker": worker,
        "trace_id": str(trace_id or "").strip(),
        "closer": closer,
        "done": False,
    }
    self._pending_ai_dialog_state = state
    self._set_waiting_for_user_reply(True)
    return state


def _finalize_pending_ai_wait(self, state, *, answer=_MISSING, cancel=False):
    if not isinstance(state, dict) or state.get("done"):
        return False

    is_current = self._pending_ai_dialog_state is state
    matches_current = self._pending_ai_wait_matches(state)
    state["done"] = True

    if is_current:
        self._pending_ai_dialog_state = None
        self._set_waiting_for_user_reply(False)

    worker = state.get("worker")
    if worker is not None and matches_current:
        try:
            if cancel:
                if hasattr(worker, "cancel_answer"):
                    worker.cancel_answer()
            elif answer is not _MISSING and hasattr(worker, "set_answer"):
                worker.set_answer(answer)
        except Exception:
            return False
    return matches_current


def _dismiss_pending_ai_wait(self, cancel_worker=False):
    state = self._pending_ai_dialog_state
    if not isinstance(state, dict):
        return

    self._pending_ai_dialog_state = None
    self._set_waiting_for_user_reply(False)
    if state.get("done"):
        return

    state["done"] = True
    worker = state.get("worker")
    if cancel_worker and worker is not None:
        trace_id = str(state.get("trace_id") or "").strip()
        active_trace_id = str(getattr(self, "ai_active_trace_id", "") or "").strip()
        if worker is self.ai_run_worker and (not trace_id or not active_trace_id or trace_id == active_trace_id):
            with suppress(Exception):
                if hasattr(worker, "cancel_answer"):
                    worker.cancel_answer()

    closer = state.get("closer")
    if callable(closer):
        with suppress(Exception):
            closer()


def _handle_pending_ai_dialog_closed(self, state):
    if not isinstance(state, dict) or state.get("done"):
        return
    self._finalize_pending_ai_wait(state, cancel=True)


def _handle_question_event(self, event_data):
    """Handle question event from agent: show dialog and unblock worker."""
    sender = self.sender() if hasattr(self, "sender") else None
    if sender is not None and sender is not self.ai_run_worker:
        return

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
    self._show_question_dialog(
        question_text,
        options,
        worker=self.ai_run_worker,
        trace_id=event_data.get("trace_id"),
    )


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

    worker = self.ai_run_worker
    trace_id = event_data.get("trace_id")
    state_ref = {"state": None}

    def _submit_result(result):
        state = state_ref.get("state")
        if state is not None:
            self._finalize_pending_ai_wait(state, answer=result)
            return
        if worker is self.ai_run_worker and hasattr(worker, "set_answer"):
            worker.set_answer(result)

    try:
        result = self._manage_boxes_request_handler(
            request,
            from_ai=True,
            on_result=_submit_result,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "error_code": "gui_confirmation_failed",
            "message": str(exc),
        }

    if isinstance(result, dict):
        if worker is self.ai_run_worker and hasattr(worker, "set_answer"):
            worker.set_answer(result)
        return

    if result is None:
        return

    closer = getattr(result, "close", None)
    state_ref["state"] = self._begin_pending_ai_wait(
        worker=worker,
        trace_id=trace_id,
        closer=closer if callable(closer) else None,
    )


def _handle_max_steps_ask(self, event_data):
    """System prompt when max_steps is reached, asks user to continue or stop."""
    from PySide6.QtWidgets import QMessageBox

    from app_gui.ui.dialogs.common import create_message_box

    steps = event_data.get("steps", 0)

    if self.ai_streaming_active:
        self._end_stream_chat()

    box = create_message_box(
        self,
        title=tr("ai.maxStepsTitle"),
        text=tr("ai.maxStepsMessage").format(steps=steps),
        icon=QMessageBox.Question,
    )
    continue_btn = box.addButton(QMessageBox.Yes)
    stop_btn = box.addButton(QMessageBox.No)
    box.setDefaultButton(continue_btn)

    def _close_box():
        if box.isVisible():
            box.close()

    state = self._begin_pending_ai_wait(
        worker=self.ai_run_worker,
        trace_id=event_data.get("trace_id"),
        closer=_close_box,
    )
    box.finished.connect(lambda _result, _state=state: self._handle_pending_ai_dialog_closed(_state))

    def _handle_clicked(clicked):
        if clicked == continue_btn:
            self._finalize_pending_ai_wait(state, answer=["continue"])
        elif clicked == stop_btn:
            self._finalize_pending_ai_wait(state, cancel=True)

    box.buttonClicked.connect(_handle_clicked)
    self._show_nonblocking_ai_dialog(box)


def _show_question_dialog(self, question_text, options, *, worker=None, trace_id=None):
    """Non-modal dialog for one clarifying question with single-choice + free text."""
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QLineEdit,
        QVBoxLayout,
    )

    from app_gui.ui.dialogs.common import configure_dialog, create_wrapping_label
    from app_gui.ui.utils import md_to_html

    dialog = configure_dialog(QDialog(self))
    dialog.setWindowTitle(tr("ai.questionTitle"))
    layout = QVBoxLayout(dialog)

    label = create_wrapping_label(
        md_to_html(str(question_text or "")),
        rich_text=True,
    )
    layout.addWidget(label)

    combo = QComboBox()
    combo.addItems(list(options or []))
    layout.addWidget(combo)

    input_edit = QLineEdit()
    input_edit.setPlaceholderText("\u8bf7\u8f93\u5165")
    input_edit.setVisible(False)
    layout.addWidget(input_edit)

    error_label = create_wrapping_label("")
    error_label.setStyleSheet("color: #d9534f;")
    error_label.setVisible(False)
    layout.addWidget(error_label)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    layout.addWidget(buttons)

    other_option = options[-1] if options else ""
    state = None

    def _close_dialog():
        if dialog.isVisible():
            dialog.close()

    if worker is not None:
        state = self._begin_pending_ai_wait(
            worker=worker,
            trace_id=trace_id,
            closer=_close_dialog,
        )
        dialog.finished.connect(lambda _result, _state=state: self._handle_pending_ai_dialog_closed(_state))

    def _toggle_other_input():
        selected = str(combo.currentText() or "").strip()
        is_other = bool(other_option and selected == other_option)
        input_edit.setVisible(is_other)
        if is_other:
            input_edit.setFocus()
        if not is_other:
            error_label.setVisible(False)
            error_label.setText("")
            input_edit.clear()

    def _accept():
        selected = str(combo.currentText() or "").strip()
        if other_option and selected == other_option:
            typed = str(input_edit.text() or "").strip()
            if not typed:
                error_label.setText("\u8bf7\u8f93\u5165\u5185\u5bb9\u540e\u518d\u786e\u8ba4\u3002")
                error_label.setVisible(True)
                input_edit.setFocus()
                return
        answer = selected
        if other_option and selected == other_option:
            answer = {
                "selected": selected,
                "text": str(input_edit.text() or "").strip(),
            }
        if state is not None:
            self._finalize_pending_ai_wait(state, answer=answer)
        dialog.accept()

    combo.currentIndexChanged.connect(_toggle_other_input)
    buttons.accepted.connect(_accept)
    buttons.rejected.connect(dialog.reject)
    _toggle_other_input()
    self._show_nonblocking_ai_dialog(dialog)
    return dialog


def on_stop_ai_agent(self):
    if not self.ai_run_inflight:
        return

    self.ai_stop_requested = True
    if self.ai_run_worker is not None and hasattr(self.ai_run_worker, "request_stop"):
        try:
            self.ai_run_worker.request_stop()
        except Exception:
            pass
    self._dismiss_pending_ai_wait(cancel_worker=False)

    if self.ai_streaming_active:
        self._end_stream_chat()
    self._append_chat("System", tr("ai.runStopped"))
    self.status_message.emit(tr("ai.aiRunStopped"), 3000)
    # Keep worker alive for cooperative shutdown; ignore late progress/final callbacks.
    self.set_busy(False)


def set_busy(self, busy):
    self.ai_run_inflight = busy
    indicator = getattr(self, "_activity_indicator", None)
    if busy:
        # Show stop button state - use default icon color (no color param)
        self.ai_run_btn.setIcon(get_icon(Icons.SQUARE))
        self.ai_run_btn.setToolTip(tr("ai.stop"))
        self.ai_run_btn.setProperty("variant", None)
        self.ai_run_btn.style().unpolish(self.ai_run_btn)
        self.ai_run_btn.style().polish(self.ai_run_btn)
        if indicator is not None:
            indicator.start()
    else:
        # Show run button state - white icon for primary variant
        self.ai_run_btn.setIcon(get_icon(Icons.PLAY, color="#ffffff"))
        self.ai_run_btn.setToolTip(tr("ai.runAgent"))
        self.ai_run_btn.setProperty("variant", "primary")
        self.ai_run_btn.style().unpolish(self.ai_run_btn)
        self.ai_run_btn.style().polish(self.ai_run_btn)
        if indicator is not None:
            indicator.stop()
    self.ai_run_btn.setEnabled(True)
    if hasattr(self, "ai_model_switch_btn"):
        self.ai_model_switch_btn.setEnabled((not busy) and bool(self._iter_model_switch_options()))


def on_progress(self, event):
    sender = self.sender() if hasattr(self, "sender") else None
    if sender is not None and sender is not self.ai_run_worker:
        return

    if self.ai_stop_requested:
        return

    event_type = str(event.get("event") or event.get("type") or "").strip()
    trace_id = event.get("trace_id")

    if event_type == "run_start":
        self.ai_active_trace_id = event.get("trace_id")
        self._history_snapshot_from_stream_end = False
        current_prompt = getattr(self, "_current_user_prompt", None)
        if current_prompt:
            self._append_history("user", current_prompt)
        return

    if self.ai_active_trace_id and trace_id and trace_id != self.ai_active_trace_id:
        return

    handlers = {
        "context_checkpoint": self._handle_progress_context_checkpoint,
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


def _extract_agent_error_payload(response, raw_result):
    payload = {}
    for source in (raw_result, response):
        if not isinstance(source, dict):
            continue
        error_code = str(source.get("error_code") or "").strip()
        message = str(source.get("message") or "").strip()
        details = source.get("details")
        if error_code and not payload.get("error_code"):
            payload["error_code"] = error_code
        if message and not payload.get("message"):
            payload["message"] = message
        if isinstance(details, dict) and details and not payload.get("details"):
            payload["details"] = details
    return payload


def _summarize_agent_error(payload):
    if not isinstance(payload, dict):
        return ""

    message = str(payload.get("message") or "").strip()
    if message:
        return message

    localized = localize_error_payload(
        {
            "error_code": payload.get("error_code"),
            "details": payload.get("details"),
        },
        fallback="",
    ).strip()
    if localized:
        return localized
    return ""


def _render_agent_error(self, payload, *, trace_id=""):
    summary = _summarize_agent_error(payload) or "Unknown error"
    final_text = summary
    details_payload = {}
    if isinstance(payload, dict):
        details_payload.update(payload)
    trace_text = str(trace_id or "").strip()
    if trace_text:
        details_payload.setdefault("trace_id", trace_text)
    if details_payload:
        self._append_chat_with_collapsible(
            "System",
            final_text,
            details_payload,
            collapsed_preview_lines=0,
        )
    else:
        self._append_chat("System", final_text)
    return final_text


def _handle_progress_tool_end(self, event):
    data = event.get("data") or {}
    name = str(data.get("name") or event.get("action") or "tool")
    raw_obs = self._extract_progress_observation(event)

    if not raw_obs.get("ok"):
        reason = str(raw_obs.get("message") or "").strip()
        if reason:
            self._append_tool_message(f"FAIL: {reason}")
        else:
            self._append_tool_message(
                f"FAIL: {localize_error_payload(raw_obs, fallback='unknown error')}"
            )

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

    _apply_tool_ui_effects(self, raw_obs)


def _handle_progress_tool_start(self, event):
    if self.ai_streaming_active:
        self._end_stream_chat()

    data = event.get("data") or {}
    name = str(data.get("name") or event.get("action") or "tool")

    # Update activity indicator with current tool name
    indicator = getattr(self, "_activity_indicator", None)
    if indicator is not None:
        indicator.set_tool_name(name)

    status_text = str(event.get("status_text") or "").strip()
    if status_text:
        self._append_tool_message(status_text)
        return

    self._append_tool_message(f"Running `{name}`...")


def _handle_progress_chunk(self, event):
    chunk = event.get("data")
    channel = str(((event.get("meta") or {}).get("channel") or "answer")).strip().lower()
    if isinstance(chunk, str) and chunk:
        # Streaming text means LLM is responding; clear tool name from indicator
        indicator = getattr(self, "_activity_indicator", None)
        if indicator is not None:
            indicator.set_tool_name("")
        self._append_stream_chunk(chunk, channel=channel)


def _handle_progress_step_end(self, event):
    # Parse step_end payload from the normalized progress producer.
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


def _handle_progress_context_checkpoint(self, event):
    data = event.get("data") or {}
    message = str(data.get("message") or "").strip()
    checkpoint_id = str(data.get("checkpoint_id") or "").strip()
    if checkpoint_id:
        self.ai_summary_state = {
            **(self.ai_summary_state or {}),
            "checkpoint_id": checkpoint_id,
        }
    if message:
        self._append_chat("System", message)


def _handle_progress_stream_end(self, event):
    data = event.get("data") or {}
    raw_messages = data.get("messages")
    summary_state = data.get("summary_state")
    self.ai_summary_state = summary_state if isinstance(summary_state, dict) else None
    last_user_ts = data.get("last_user_ts")
    if isinstance(last_user_ts, (int, float)):
        self._mark_active_turn_done(status="stream_end", user_ts=float(last_user_ts))
    if not isinstance(raw_messages, list):
        return

    normalized = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant", "tool"}:
            continue

        content = str(item.get("content") or "").strip()
        if role == "user" and content.startswith("[Operation Results]\n"):
            continue
        tool_calls = item.get("tool_calls") if role == "assistant" else None
        if role == "assistant":
            has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
            if not content and not has_tool_calls:
                continue
        elif not content:
            continue

        entry = {"role": role, "content": content}

        ts = item.get("timestamp")
        if isinstance(ts, (int, float)):
            entry = {**entry, "timestamp": float(ts)}

        if role == "assistant":
            has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
            if isinstance(tool_calls, list):
                entry = {**entry, "tool_calls": list(tool_calls)}
            reasoning = str(item.get("reasoning_content") or "")
            if reasoning or has_tool_calls:
                entry = {**entry, "reasoning_content": reasoning}
        elif role == "tool":
            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if not tool_call_id:
                continue
            entry = {**entry, "tool_call_id": tool_call_id}

        normalized.append(entry)

    if normalized:
        self.ai_history = normalized[-AI_HISTORY_LIMIT:]
        self._history_snapshot_from_stream_end = True


def _handle_progress_max_steps(_event):
    return


def _apply_tool_ui_effects(panel, raw_obs):
    effects = raw_obs.get("ui_effects") if isinstance(raw_obs, dict) else None
    if not isinstance(effects, list):
        return
    for effect in effects:
        if _apply_tool_ui_effect(panel, effect, raw_obs=raw_obs) is False:
            break


def _apply_tool_ui_effect(panel, effect, *, raw_obs=None):
    if not isinstance(effect, dict):
        return True

    effect_type = str(effect.get("type") or "").strip().lower()
    if effect_type == "migration_mode":
        handler = getattr(panel, "set_migration_mode_enabled", None)
        if callable(handler):
            handler(bool(effect.get("enabled")))
        return True

    if effect_type == "open_dataset":
        target_path = str(
            effect.get("target_path")
            or ((raw_obs or {}).get("target_path") if isinstance(raw_obs, dict) else "")
            or ""
        ).strip()
        return _handle_open_dataset_effect(
            panel,
            target_path=target_path,
        )
    return True


def _handle_open_dataset_effect(panel, *, target_path):
    if not target_path:
        panel._append_tool_message("UI effect `open_dataset` is missing target_path.")
        return False

    switch_handler = getattr(panel, "_import_dataset_handler", None)
    if not callable(switch_handler):
        panel._append_tool_message(f"Imported dataset ready: `{target_path}`")
        return False

    try:
        opened_path = switch_handler(target_path)
    except Exception as exc:
        panel._append_tool_message(f"Import succeeded but opening dataset failed: {exc}")
        return False

    opened_text = str(opened_path or target_path).strip() or target_path
    panel._append_tool_message(f"Imported dataset opened: `{opened_text}`")
    return True


def on_finished(self, response):
    sender = self.sender() if hasattr(self, "sender") else None
    if sender is not None and sender is not self.ai_run_worker:
        return

    self._dismiss_pending_ai_wait(cancel_worker=False)
    stream_end_snapshot_applied = bool(getattr(self, "_history_snapshot_from_stream_end", False))

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

        if not stream_end_snapshot_applied:
            if streamed_text:
                self._append_history("assistant", streamed_text)
            if stop_note:
                self._append_history("assistant", stop_note)

        self.set_busy(False)
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self._reset_stream_thought_state()
        self.operation_completed.emit(False)
        self._history_snapshot_from_stream_end = False
        return

    self.set_busy(False)
    response = response if isinstance(response, dict) else {}

    raw_result = response.get("result")
    protocol_error = False
    if not isinstance(raw_result, dict):
        raw_result = {}
        protocol_error = bool(response.get("ok"))
    self.ai_summary_state = raw_result.get("summary_state") if isinstance(raw_result.get("summary_state"), dict) else self.ai_summary_state
    error_payload = _extract_agent_error_payload(response, raw_result)

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

    rendered_error_notice = False
    if not protocol_error and not bool(response.get("ok")) and error_payload:
        final_text = _render_agent_error(
            self,
            error_payload,
            trace_id=str(raw_result.get("trace_id") or ""),
        )
        rendered_error_notice = True

    used_stream_markdown_rewrite = False
    if not rendered_error_notice and streamed_text and final_text.strip() == streamed_text and not had_thought_stream:
        used_stream_markdown_rewrite = self._replace_stream_block_with_markdown(
            self.ai_last_stream_block,
            final_text,
        )

    if rendered_error_notice:
        pass
    elif not streamed_text:
        self._append_chat("Agent", final_text)
    elif final_text.strip() != streamed_text:
        # Keep a final canonical message if streamed chunks differ.
        self._append_chat("Agent", final_text)
    elif not used_stream_markdown_rewrite:
        # Could not rewrite in-place (e.g. limited chat stub); avoid duplicate append.
        pass

    turn = self._mark_active_turn_done(
        status="error" if rendered_error_notice else "complete",
        answer_text=final_text,
    )
    if turn is not None:
        self._append_turn_actions(
            turn.get("turn_id"),
            include_copy=not rendered_error_notice,
            retry_label=tr("ai.actionRetry") if rendered_error_notice else tr("ai.actionTryAgain"),
        )

    self.ai_stream_buffer = ""
    self.ai_stream_start_pos = None
    self.ai_stream_last_render_ts = 0.0
    self.ai_stream_last_render_len = 0
    self._pause_stream_thought_timer()
    if not had_thought_stream:
        self._reset_stream_thought_state()
        self.ai_last_stream_block = None
    if not stream_end_snapshot_applied:
        self._append_history("assistant", final_text)

    if response.get("error_code") == "api_key_required":
        self.status_message.emit("API key missing. See chat for setup steps.", 6000)

    self.operation_completed.emit(bool(response.get("ok")))

    trace_id = raw_result.get("trace_id")
    self._load_audit(trace_id, raw_result)
    self._history_snapshot_from_stream_end = False


def on_thread_finished(self):
    sender = self.sender() if hasattr(self, "sender") else None
    if sender is not None and sender is not self.ai_run_thread:
        return

    self._dismiss_pending_ai_wait(cancel_worker=False)
    self.ai_stop_requested = False
    self.ai_run_thread = None
    self.ai_run_worker = None
