from datetime import datetime
import time
from PySide6.QtCore import Qt, Signal, QThread, QEvent
from PySide6.QtGui import QTextCursor, QTextDocumentFragment
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QCheckBox, 
    QGroupBox, QTextEdit, QFormLayout, QSpinBox
)
from app_gui.ui.workers import AgentRunWorker
from app_gui.ui.utils import build_panel_header, compact_json
from app_gui.plan_outcome import collect_blocked_items, summarize_plan_execution
from lib.config import AUDIT_LOG_FILE
import os
import json

AI_HELP_TEXT = """AI Assistant Panel - Natural Language Operations

This panel lets you control inventory using natural language commands.

SETUP:
1. Configure your DeepSeek API key in Settings
2. Uncheck "Mock LLM" to enable real AI responses
3. Mock mode is useful for testing without API calls

USAGE:
Type requests in plain language, for example:
- "Show me all K562 samples"
- "Move sample 5 to position 10 in box 2"
- "How many empty slots in box 1?"
- "Thaw samples at positions 1, 2, and 3"

HOW IT WORKS:
1. AI analyzes your request
2. Generates a plan of operations
3. Plan items appear in Operations panel
4. Review and execute from Plan mode

TIPS:
- Be specific about box numbers and positions
- Use record IDs when referring to samples
- Check generated plans before executing
- Use mock mode to learn without API costs"""

class AIPanel(QWidget):
    operation_completed = Signal(bool)
    plan_items_staged = Signal(list)
    status_message = Signal(str, int) # msg, timeout

    def __init__(self, bridge, yaml_path_getter):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        
        self.ai_history = []
        self.ai_operation_events = []
        self.ai_run_inflight = False
        self.ai_run_thread = None
        self.ai_run_worker = None
        self.ai_active_trace_id = None
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        # Re-render markdown frequently enough to feel live, but still throttle CPU churn.
        self.ai_stream_render_interval_sec = 0.06
        self.ai_stream_render_min_delta = 8

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addLayout(build_panel_header(self, "AI Assistant", "AI Assistant Help", AI_HELP_TEXT))

        # Toggles
        toggle_row = QHBoxLayout()
        self.ai_toggle_controls_btn = QPushButton("Show Advanced")
        self.ai_toggle_controls_btn.setCheckable(True)
        self.ai_toggle_controls_btn.toggled.connect(self.on_toggle_controls)
        toggle_row.addWidget(self.ai_toggle_controls_btn)

        self.ai_toggle_report_btn = QPushButton("Show Plan Details")
        self.ai_toggle_report_btn.setCheckable(True)
        self.ai_toggle_report_btn.toggled.connect(self.on_toggle_report)
        toggle_row.addWidget(self.ai_toggle_report_btn)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # Controls
        self.ai_controls_box = QGroupBox("Agent Controls")
        controls_form = QFormLayout(self.ai_controls_box)
        self.ai_model = QLineEdit()
        self.ai_model.setPlaceholderText("deepseek-chat")
        self.ai_model.setText("deepseek-chat")

        self.ai_steps = QSpinBox()
        self.ai_steps.setRange(1, 20)
        self.ai_steps.setValue(8)

        self.ai_mock = QCheckBox("Mock LLM (no external API)")
        self.ai_mock.setChecked(True)
        self.ai_mock.stateChanged.connect(self.on_mode_changed)

        controls_form.addRow("DeepSeek Model", self.ai_model)
        controls_form.addRow("Max Steps", self.ai_steps)
        controls_form.addRow("", self.ai_mock)
        layout.addWidget(self.ai_controls_box)

        # Prompt Box
        prompt_box = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_box)

        examples = QHBoxLayout()
        examples.addWidget(QLabel("Quick prompts"))

        quick_prompts = [
            ("Find K562", "Find K562-related records and summarize count with a few representative rows."),
            ("Takeout Today", "List today's takeout/thaw/discard events and summarize by action."),
            ("Suggest Slots", "Recommend 2 consecutive empty slots, prefer boxes with more free space, and explain why."),
        ]
        for label, text in quick_prompts:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, value=text: self.set_prompt(value))
            examples.addWidget(btn)
        examples.addStretch()
        prompt_layout.addLayout(examples)

        self.ai_prompt = QTextEdit()
        self.ai_prompt.setPlaceholderText("Type a natural-language request... (Enter to send, Shift+Enter for newline)")
        self.ai_prompt.setFixedHeight(90)
        self.ai_prompt.installEventFilter(self)
        prompt_layout.addWidget(self.ai_prompt)

        run_row = QHBoxLayout()
        self.ai_run_btn = QPushButton("Run Agent")
        self.ai_run_btn.clicked.connect(self.on_run_ai_agent)
        run_row.addWidget(self.ai_run_btn)

        self.ai_stop_btn = QPushButton("Stop")
        self.ai_stop_btn.setEnabled(False)
        self.ai_stop_btn.clicked.connect(self.on_stop_ai_agent)
        run_row.addWidget(self.ai_stop_btn)

        ai_clear_btn = QPushButton("Clear AI Panel")
        ai_clear_btn.clicked.connect(self.on_clear)
        run_row.addWidget(ai_clear_btn)
        run_row.addStretch()
        prompt_layout.addLayout(run_row)

        # Chat Area
        chat_box = QGroupBox("AI Chat")
        chat_layout = QVBoxLayout(chat_box)
        self.ai_chat = QTextEdit()
        self.ai_chat.setReadOnly(True)
        self.ai_chat.setAcceptRichText(True)
        self.ai_chat.setPlaceholderText("Conversation timeline will appear here.")
        chat_layout.addWidget(self.ai_chat)
        layout.addWidget(chat_box, 3)

        # Report Area
        self.ai_report_box = QGroupBox("Plan / Preview / Result / Audit")
        report_layout = QVBoxLayout(self.ai_report_box)
        self.ai_report = QTextEdit()
        self.ai_report.setReadOnly(True)
        self.ai_report.setPlaceholderText("Structured agent output will appear here.")
        report_layout.addWidget(self.ai_report)
        layout.addWidget(self.ai_report_box, 1)
        
        # Keep input at bottom? No, prompt_box is better at top or mid for access.
        # But wait, in previous version prompt was bottom. Let's move prompt_box to bottom.
        # Removing prompt_box from current position and adding to end.
        layout.removeWidget(prompt_box) # Wait, can't remove easily if added via addLayout.
        # Re-ordering: 
        # 1. Toggles
        # 2. Controls (hidden)
        # 3. Chat (expand)
        # 4. Report (hidden)
        # 5. Prompt (fixed height)
        
        # Redo layout logic:
        # Clear existing layout calls above for order.
        # Actually, `layout` adds sequentially.
        # Current: Toggles -> Controls -> Prompt -> Chat -> Report.
        # Desired: Toggles -> Controls -> Chat -> Report -> Prompt.
        
        # I'll just clear prompt_box from layout and add it at the end.
        # Since I haven't added `prompt_box` to `layout` yet in this script execution order...
        # Oh, I did: `prompt_layout.addLayout(examples)` etc... `prompt_box` is the container.
        # But I haven't called `layout.addWidget(prompt_box)` yet in the code above?
        # Ah, I see `prompt_layout` populated, but not added to main `layout`?
        # Wait, I see `layout.addWidget(chat_box, 3)`.
        # I missed adding `prompt_box` in previous lines? 
        # Ah, I see `prompt_layout` logic.
        
        # Let's fix the order.
        
        # Remove widgets from layout if already added? No, just careful construction.
        # I will reconstruct the layout order properly now.
        
        # Order: 
        # Toggles (added)
        # Controls (added)
        # Chat
        # Report
        # Prompt
        
        # So I won't add prompt_box yet.
        
        self.ai_controls_box.setVisible(False)
        self.ai_report_box.setVisible(False)
        self.on_mode_changed()

        # Add remaining widgets
        layout.addWidget(prompt_box)

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.KeyPress
            and obj is self.ai_prompt
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            mods = event.modifiers()
            if mods & Qt.ShiftModifier:
                return False
            if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                return False
            self.on_run_ai_agent()
            return True
        return super().eventFilter(obj, event)

    def on_toggle_controls(self, checked):
        self.ai_controls_box.setVisible(bool(checked))
        self.ai_toggle_controls_btn.setText("Hide Advanced" if checked else "Show Advanced")

    def on_toggle_report(self, checked):
        self.ai_report_box.setVisible(bool(checked))
        self.ai_toggle_report_btn.setText("Hide Plan Details" if checked else "Show Plan Details")

    def on_mode_changed(self):
        use_mock = self.ai_mock.isChecked()
        self.ai_model.setEnabled(not use_mock)
        self.ai_model.setPlaceholderText("Mock mode enabled" if use_mock else "deepseek-chat")

    def set_prompt(self, text):
        self.ai_prompt.setPlainText(str(text or "").strip())
        self.ai_prompt.setFocus()

    def on_clear(self):
        self.ai_chat.clear()
        self.ai_report.clear()
        self.ai_history = []
        self.ai_active_trace_id = None
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self.status_message.emit("AI memory cleared", 2000)

    def _append_chat_header(self, role):
        self._move_chat_cursor_to_end()
        stamp = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "Agent": "#38bdf8",
            "You": "#a3e635",
            "Tool": "#f59e0b",
            "System": "#f97316",
        }
        color = color_map.get(role, "#a3e635")
 
        html = f"""
        <div style="margin-bottom: 8px;">
            <span style="color: {color}; font-weight: bold;">[{stamp}] {role}</span>
            <br/>
        </div>
        """
        self.ai_chat.append(html)

    def _move_chat_cursor_to_end(self):
        if not hasattr(self.ai_chat, "textCursor") or not hasattr(self.ai_chat, "setTextCursor"):
            return
        cursor = self.ai_chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.ai_chat.setTextCursor(cursor)

    def _append_chat(self, role, text):
        self._append_chat_header(role)
        self._insert_chat_markdown(text)
        self.ai_chat.append("\n") # Spacer

    def _begin_stream_chat(self, role="Agent"):
        if self.ai_streaming_active:
            return
        self.ai_streaming_active = True
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = time.monotonic()
        self.ai_stream_last_render_len = 0
        self._append_chat_header(role)
        self._move_chat_cursor_to_end()
        if hasattr(self.ai_chat, "textCursor"):
            self.ai_stream_start_pos = self.ai_chat.textCursor().position()

    def _append_stream_chunk(self, text):
        chunk = str(text or "")
        if not chunk:
            return
        if not self.ai_streaming_active:
            self._begin_stream_chat("Agent")
        self.ai_stream_buffer += chunk
        self._move_chat_cursor_to_end()
        self.ai_chat.insertPlainText(chunk)
        if hasattr(self.ai_chat, "ensureCursorVisible"):
            self.ai_chat.ensureCursorVisible()

        if self._should_rerender_stream_markdown():
            self._rerender_stream_markdown_in_place()

    def _should_rerender_stream_markdown(self):
        if not self.ai_streaming_active:
            return False

        current_len = len(self.ai_stream_buffer)
        if current_len <= self.ai_stream_last_render_len:
            return False

        delta = current_len - self.ai_stream_last_render_len
        if delta >= max(1, int(self.ai_stream_render_min_delta or 0)):
            return True

        elapsed = time.monotonic() - float(self.ai_stream_last_render_ts or 0.0)
        return elapsed >= float(self.ai_stream_render_interval_sec or 0.0)

    def _rerender_stream_markdown_in_place(self, force=False):
        if not self.ai_streaming_active:
            return False

        if not force and not self._should_rerender_stream_markdown():
            return False

        if self.ai_stream_start_pos is None:
            return False
        if not hasattr(self.ai_chat, "textCursor"):
            return False

        self._move_chat_cursor_to_end()
        end_pos = self.ai_chat.textCursor().position()
        block = {
            "start": self.ai_stream_start_pos,
            "end": end_pos,
            "text": self.ai_stream_buffer,
        }
        ok = self._replace_stream_block_with_markdown(block, self.ai_stream_buffer)
        if not ok:
            return False

        self.ai_stream_last_render_ts = time.monotonic()
        self.ai_stream_last_render_len = len(self.ai_stream_buffer)

        self._move_chat_cursor_to_end()
        new_end = self.ai_chat.textCursor().position()
        self.ai_last_stream_block = {
            "start": self.ai_stream_start_pos,
            "end": new_end,
            "text": self.ai_stream_buffer,
        }
        return True

    def _end_stream_chat(self):
        if not self.ai_streaming_active:
            return

        # Force a final in-place markdown pass for current streamed block.
        self._rerender_stream_markdown_in_place(force=True)

        self._move_chat_cursor_to_end()
        start_pos = self.ai_stream_start_pos
        end_pos = None
        if hasattr(self.ai_chat, "textCursor"):
            end_pos = self.ai_chat.textCursor().position()
        self.ai_last_stream_block = {
            "start": start_pos,
            "end": end_pos,
            "text": self.ai_stream_buffer,
        }

        self.ai_chat.append("\n")
        self.ai_streaming_active = False
        self.ai_stream_start_pos = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0

    def _insert_chat_markdown(self, text):
        markdown_text = str(text or "")
        self._move_chat_cursor_to_end()
        cursor = self.ai_chat.textCursor() if hasattr(self.ai_chat, "textCursor") else None
        self._insert_markdown_with_cursor(cursor, markdown_text)

    def _insert_markdown_with_cursor(self, cursor, markdown_text):
        markdown_text = str(markdown_text or "")
        if cursor is not None and hasattr(self.ai_chat, "setTextCursor"):
            self.ai_chat.setTextCursor(cursor)

        if hasattr(self.ai_chat, "insertMarkdown"):
            self.ai_chat.insertMarkdown(markdown_text)
            return

        # Qt fallback for runtimes where QTextEdit has no insertMarkdown.
        if hasattr(QTextDocumentFragment, "fromMarkdown") and hasattr(self.ai_chat, "textCursor"):
            cursor = self.ai_chat.textCursor()
            fragment = QTextDocumentFragment.fromMarkdown(markdown_text)
            cursor.insertFragment(fragment)
            if hasattr(self.ai_chat, "setTextCursor"):
                self.ai_chat.setTextCursor(cursor)
            return

        self.ai_chat.insertPlainText(markdown_text)

    def _replace_stream_block_with_markdown(self, block, markdown_text):
        if not isinstance(block, dict):
            return False
        start = block.get("start")
        end = block.get("end")
        if start is None or end is None:
            return False
        if not hasattr(self.ai_chat, "textCursor"):
            return False

        try:
            cursor = self.ai_chat.textCursor()
            cursor.setPosition(int(start))
            cursor.setPosition(int(end), QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self._insert_markdown_with_cursor(cursor, markdown_text)
            self._move_chat_cursor_to_end()
            return True
        except Exception:
            return False

    def on_run_ai_agent(self):
        if self.ai_run_inflight:
            return
        
        prompt = self.ai_prompt.toPlainText().strip()
        if not prompt:
            self.status_message.emit("Please enter a prompt.", 2000)
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
        self.ai_report.clear()
        self.status_message.emit("Agent thinking...", 2000)
        
        self.start_worker(prompt)

    def start_worker(self, prompt):
        model = self.ai_model.text().strip() or None
        history = [dict(item) for item in self.ai_history if isinstance(item, dict)]

        if self.ai_operation_events:
            recent_events = self.ai_operation_events[-5:]
            context_msg = json.dumps(recent_events, ensure_ascii=False, indent=2)
            history.append({"role": "user", "content": f"[Operation Results]\n{context_msg}"})

        self.ai_run_worker = AgentRunWorker(
            bridge=self.bridge,
            yaml_path=self.yaml_path_getter(),
            query=prompt,
            model=model,
            max_steps=self.ai_steps.value(),
            mock=self.ai_mock.isChecked(),
            history=history,
        )
        self.ai_run_thread = QThread(self)
        self.ai_run_worker.moveToThread(self.ai_run_thread)
        
        self.ai_run_thread.started.connect(self.ai_run_worker.run)
        self.ai_run_worker.progress.connect(self.on_progress)
        self.ai_run_worker.plan_staged.connect(self.plan_items_staged.emit)
        self.ai_run_worker.finished.connect(self.on_finished)
        self.ai_run_worker.finished.connect(self.ai_run_thread.quit)
        self.ai_run_worker.finished.connect(self.ai_run_worker.deleteLater)
        self.ai_run_thread.finished.connect(self.ai_run_thread.deleteLater)
        self.ai_run_thread.finished.connect(self.on_thread_finished)
        
        self.set_busy(True)
        self.ai_run_thread.start()

    def on_stop_ai_agent(self):
        if self.ai_run_thread and self.ai_run_thread.isRunning():
            # Terminate is harsh, but ReactAgent is sync.
            # We will just detach signals and kill it.
            # Ideally we have a 'stop' flag in worker, but worker is running a blocking call.
            self.ai_run_thread.terminate()
            self.set_busy(False)
            self._append_chat("System", "**Run stopped by user.**")
            self.status_message.emit("AI run stopped.", 3000)

    def set_busy(self, busy):
        self.ai_run_inflight = busy
        self.ai_run_btn.setEnabled(not busy)
        self.ai_run_btn.setText("Running..." if busy else "Run Agent")
        self.ai_stop_btn.setEnabled(busy)

    def on_progress(self, event):
        event_type = str(event.get("event") or event.get("type") or "").strip()
        trace_id = event.get("trace_id")

        if event_type == "run_start":
            self.ai_active_trace_id = event.get("trace_id")
            return

        if self.ai_active_trace_id and trace_id and trace_id != self.ai_active_trace_id:
            return

        if event_type == "tool_end":
            data = event.get("data") or {}
            name = str(data.get("name") or event.get("action") or "tool")
            step = event.get("step")
            raw_output = ((data.get("output") or {}).get("content"))

            raw_obs = event.get("observation")
            if not isinstance(raw_obs, dict):
                if isinstance(raw_output, str):
                    try:
                        parsed = json.loads(raw_output)
                        raw_obs = parsed if isinstance(parsed, dict) else {}
                    except Exception:
                        raw_obs = {}
                else:
                    raw_obs = {}

            status = "OK" if raw_obs.get("ok") else "FAIL"
            summary = raw_obs.get("message")
            hint = raw_obs.get("_hint")
            if not summary and raw_obs.get("result"):
                summary = compact_json(raw_obs.get("result"), 120)

            line = f"Step {step}: {name} -> {status}"
            if summary:
                line += f" | {summary}"
            if hint:
                line += f" | hint: {hint}"
            self.ai_report.append(line)
            self._append_chat("Tool", f"`{name}` finished: **{status}**")
            if hint:
                self._append_chat("Tool", f"Hint: {hint}")
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
            return

        if event_type == "tool_start":
            if self.ai_streaming_active:
                self._end_stream_chat()

            data = event.get("data") or {}
            name = str(data.get("name") or event.get("action") or "tool")
            self._append_chat("Tool", f"Running `{name}`...")
            return

        if event_type == "chunk":
            chunk = event.get("data")
            if isinstance(chunk, str) and chunk:
                self._append_stream_chunk(chunk)
            return

        if event_type == "error":
            err = event.get("data") or event.get("message") or "unknown error"
            self.ai_report.append(f"Agent error: {err}")
            return

        if event_type == "stream_end":
            status = (event.get("data") or {}).get("status")
            if status:
                self.ai_report.append(f"Stream end: {status}")
            return

        if event_type == "step_end":
            step = event.get("step")
            action = str(event.get("action") or "tool")
            raw_obs = event.get("observation") or {}
            status = "OK" if raw_obs.get("ok") else f"FAIL"
            summary = raw_obs.get("message")
            hint = raw_obs.get("_hint")
            if not summary and raw_obs.get("result"):
                summary = compact_json(raw_obs.get("result"), 120)
            
            line = f"Step {step}: {action} -> {status}"
            if summary:
                line += f" | {summary}"
            if hint:
                line += f" | hint: {hint}"
            self.ai_report.append(line)

        if event_type == "max_steps":
            self.ai_report.append("Max steps reached. Returning best-effort summary.")

    def on_finished(self, response):
        self.set_busy(False)
        response = response if isinstance(response, dict) else {}

        raw_result = response.get("result")
        protocol_error = False
        if not isinstance(raw_result, dict):
            raw_result = {}
            protocol_error = bool(response.get("ok"))

        if protocol_error:
            final_text = "Internal protocol error: missing result payload."
            self.ai_report.append("Protocol error: bridge returned ok=true without result object.")
        else:
            final_text = str(raw_result.get("final") or response.get("message") or "").strip()
        if not final_text:
            final_text = "Agent finished without a final message."
            self.ai_report.append("Protocol warning: result.final is empty.")

        streamed_text = self.ai_stream_buffer.strip()
        if self.ai_streaming_active:
            self._end_stream_chat()
            streamed_text = str((self.ai_last_stream_block or {}).get("text") or "").strip()

        used_stream_markdown_rewrite = False
        if streamed_text and final_text.strip() == streamed_text:
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
        self._append_history("assistant", final_text)

        if response.get("error_code") == "api_key_required":
            self.status_message.emit("DeepSeek API key missing. See chat for setup steps.", 6000)

        self.operation_completed.emit(bool(response.get("ok")))
        
        # Audit trace
        trace_id = raw_result.get("trace_id")
        self._load_audit(trace_id, raw_result)

    def on_thread_finished(self):
        self.ai_run_thread = None
        self.ai_run_worker = None

    @staticmethod
    def _format_blocked_item(item):
        action = str(item.get("action") or "?")
        rid = item.get("record_id")
        box = item.get("box")
        pos = item.get("position")
        to_pos = item.get("to_position")
        to_box = item.get("to_box")

        id_text = f"ID {rid}" if rid not in (None, "") else "NEW"
        location = "unknown"
        if box not in (None, "") and pos not in (None, ""):
            location = f"Box {box}:{pos}"
        elif pos not in (None, ""):
            location = f"Pos {pos}"

        if action == "move" and to_pos not in (None, ""):
            if to_box not in (None, ""):
                location = f"{location} -> Box {to_box}:{to_pos}"
            else:
                location = f"{location} -> {to_pos}"

        return f"{action} ({id_text}, {location})"

    def _blocked_items_summary(self, tool_name, blocked_items):
        count = len(blocked_items)
        lines = [f"**Tool blocked** `{tool_name}`: {count} item(s) failed validation"]
        for item in blocked_items[:3]:
            payload = item if isinstance(item, dict) else {}
            desc = self._format_blocked_item(payload)
            message = payload.get("message") or payload.get("error_code") or "Validation failed"
            lines.append(f"- {desc}: {message}")
        if count > 3:
            lines.append(f"- ... and {count - 3} more")
        return "\n".join(lines)

    def _append_history(self, role, text):
        self.ai_history.append({"role": role, "content": text})
        if len(self.ai_history) > 20:
            self.ai_history = self.ai_history[-20:]

    def on_operation_event(self, event):
        """Receive operation events from operations panel and display them."""
        event_type = event.get("type", "unknown")
        timestamp = event.get("timestamp", datetime.now().isoformat())

        self.ai_operation_events.append(event)
        if len(self.ai_operation_events) > 20:
            self.ai_operation_events = self.ai_operation_events[-20:]

        details_json = json.dumps(event, ensure_ascii=False, indent=2)

        if event_type == "plan_execute_blocked":
            report = event.get("report", {})
            blocked_items = collect_blocked_items(report)
            blocked_count = event.get("blocked_count", len(blocked_items))
            summary_lines = [f"**Plan blocked**: {blocked_count} item(s) have validation errors"]
            for item in blocked_items[:3]:
                rec = item.get("item", {})
                err = item.get("message", "Unknown error")
                summary_lines.append(f"- ID {rec.get('record_id', '?')}: {err}")
            if len(blocked_items) > 3:
                summary_lines.append(f"- ... and {len(blocked_items) - 3} more")
            summary_text = "\n".join(summary_lines)
            self._append_chat_with_collapsible("System", summary_text, details_json)

        elif event_type == "plan_executed":
            event_stats = event.get("stats") if isinstance(event.get("stats"), dict) else {}
            report = event.get("report")
            if not isinstance(report, dict):
                report = {"stats": event_stats, "items": []}
            elif not isinstance(report.get("stats"), dict):
                report = dict(report)
                report["stats"] = event_stats
            rollback = event.get("rollback")
            execution_stats = summarize_plan_execution(report, rollback)
            total_count = execution_stats.get("total_count", 0)
            applied_count = execution_stats.get("applied_count", event_stats.get("applied", 0))

            if execution_stats.get("fail_count", 0) <= 0 and event.get("ok", False):
                summary_text = f"**Plan executed succeeded**: {applied_count}/{total_count} operations applied"
            else:
                blocked_count = execution_stats.get("blocked_count", event_stats.get("blocked", 0))
                if execution_stats.get("rollback_ok"):
                    summary_lines = [f"**Plan rejected atomically**: 0/{total_count} operations applied"]
                else:
                    summary_lines = [f"**Plan executed had issues**: {applied_count}/{total_count} operations applied"]
                if blocked_count:
                    summary_lines.append(f"- Blocked: {blocked_count} item(s)")
                blocked_items = collect_blocked_items(report)
                for item in blocked_items[:3]:
                    rec = item.get("item", {})
                    err = item.get("message", "Unknown error")
                    summary_lines.append(f"- ID {rec.get('record_id', '?')}: {err}")
                if len(blocked_items) > 3:
                    summary_lines.append(f"- ... and {len(blocked_items) - 3} more")
                if execution_stats.get("rollback_ok"):
                    summary_lines.append("- Rollback applied: partial changes reverted")
                elif execution_stats.get("rollback_attempted"):
                    summary_lines.append(
                        f"- Rollback failed: {execution_stats.get('rollback_message') or 'unknown error'}"
                    )
                elif execution_stats.get("rollback_message"):
                    summary_lines.append(
                        f"- Rollback unavailable: {execution_stats.get('rollback_message')}"
                    )
                summary_text = "\n".join(summary_lines)
            self._append_chat_with_collapsible("System", summary_text, details_json)

    def _append_chat_with_collapsible(self, role, summary, details_json):
        """Append a chat message and store full details in the report panel."""
        self._append_chat_header(role)
        self._insert_chat_markdown(summary)
        details_text = str(details_json or "")
        detail_line = (
            f"\\n\\n`Raw JSON hidden` ({len(details_text)} chars). "
            "Use **Show Plan Details** to inspect full payload."
        )
        self._insert_chat_markdown(detail_line)
        self.ai_chat.append("")
        self.ai_report.setPlainText(details_text)

    def _load_audit(self, trace_id, run_result):
        self.ai_report.setPlainText(json.dumps(run_result, indent=2))
        pass
