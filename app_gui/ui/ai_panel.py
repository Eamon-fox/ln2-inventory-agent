from datetime import datetime
from PySide6.QtCore import Qt, Signal, QThread, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QCheckBox, 
    QGroupBox, QTextEdit, QFormLayout, QSpinBox
)
from app_gui.ui.workers import AgentRunWorker
from app_gui.ui.utils import compact_json
from lib.config import AUDIT_LOG_FILE
import os
import json

class AIPanel(QWidget):
    operation_completed = Signal(bool)
    status_message = Signal(str, int) # msg, timeout

    def __init__(self, bridge, yaml_path_getter):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        
        self.ai_history = []
        self.ai_run_inflight = False
        self.ai_run_thread = None
        self.ai_run_worker = None
        self.ai_active_trace_id = None

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

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
        self.ai_model.setPlaceholderText("e.g. deepseek-chat")

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
        self.ai_model.setPlaceholderText("Mock mode enabled" if use_mock else "e.g. deepseek-chat")

    def set_prompt(self, text):
        self.ai_prompt.setPlainText(str(text or "").strip())
        self.ai_prompt.setFocus()

    def on_clear(self):
        self.ai_chat.clear()
        self.ai_report.clear()
        self.ai_history = []
        self.ai_active_trace_id = None
        self.status_message.emit("AI memory cleared", 2000)

    def _append_chat(self, role, text):
        stamp = datetime.now().strftime("%H:%M:%S")
        
        # Markdown rendering
        # We can construct HTML for better look
        color = "#38bdf8" if role == "Agent" else "#a3e635" # Blue for agent, Green for user
        
        html = f"""
        <div style="margin-bottom: 8px;">
            <span style="color: {color}; font-weight: bold;">[{stamp}] {role}</span>
            <br/>
        </div>
        """
        self.ai_chat.append(html)
        if hasattr(self.ai_chat, "insertMarkdown"):
            self.ai_chat.insertMarkdown(text)
        else:
            self.ai_chat.insertPlainText(text)
        self.ai_chat.append("\n") # Spacer

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
        self.ai_report.clear()
        self.status_message.emit("Agent thinking...", 2000)
        
        self.start_worker(prompt)

    def start_worker(self, prompt):
        model = self.ai_model.text().strip() or None
        history = [dict(item) for item in self.ai_history if isinstance(item, dict)]
        
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
        
        self._append_chat("Agent", final_text)
        self._append_history("assistant", final_text)

        self.operation_completed.emit(bool(response.get("ok")))
        
        # Audit trace
        trace_id = raw_result.get("trace_id")
        self._load_audit(trace_id, raw_result)

    def on_thread_finished(self):
        self.ai_run_thread = None
        self.ai_run_worker = None

    def _append_history(self, role, text):
        self.ai_history.append({"role": role, "content": text})
        if len(self.ai_history) > 20:
            self.ai_history = self.ai_history[-20:]

    def _load_audit(self, trace_id, run_result):
        # Basic audit loading
        self.ai_report.setPlainText(json.dumps(run_result, indent=2))
        # Could reuse logic from main to load audit log file
        pass
