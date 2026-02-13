from datetime import datetime
import time
import re
import random
from PySide6.QtCore import Qt, Signal, QThread, QEvent
from PySide6.QtGui import QTextCursor, QPalette, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit,
    QTextEdit, QSpinBox, QCheckBox
)
from app_gui.ui.workers import AgentRunWorker
from app_gui.ui.utils import compact_json, CollapsibleBox
from app_gui.event_compactor import compact_operation_event_for_context
from app_gui.i18n import tr
from app_gui.plan_outcome import collect_blocked_items, summarize_plan_execution
from lib.config import AUDIT_LOG_FILE
import os
import json


_ROLE_COLORS = {
    "dark": {
        "Agent": "#38bdf8",
        "You": "#a3e635",
        "Tool": "#f59e0b",
        "System": "#f97316",
        "muted": "#9ca3af",
        "link": "#60a5fa",
    },
    "light": {
        "Agent": "#0284c7",
        "You": "#4d7c0f",
        "Tool": "#b45309",
        "System": "#c2410c",
        "muted": "#64748b",
        "link": "#2563eb",
    },
}


def _get_role_color(role, is_dark=True):
    theme = "dark" if is_dark else "light"
    return _ROLE_COLORS.get(theme, {}).get(role, "#a3e635")


PLACEHOLDER_EXAMPLES_EN = [
    "Find K562-related records and summarize count",
    "List today's takeout/thaw events",
    "Recommend 2 consecutive empty slots",
    "Show all empty positions in box A1",
    "Add a new plasmid record",
    "Move tube from box A1:1 to B2:3",
    "Help me audit today's risky operations",
    "Check if any records have conflicting positions",
    "Summarize inventory distribution by box",
    "Find records that may need attention",
]

PLACEHOLDER_EXAMPLES_ZH = [
    "查找 K562 相关记录并汇总数量",
    "列出今天的取出/复苏事件",
    "推荐 2 个连续空位",
    "显示盒子 A1 的所有空位",
    "添加一条新的质粒记录",
    "将管子从盒子 A1:1 移到 B2:3",
    "帮我审计今天的高风险操作",
    "检查是否有位置冲突的记录",
    "按盒子汇总库存分布",
    "查找可能需要关注的记录",
]


def _is_dark_mode(widget):
    try:
        palette = widget.palette()
        bg_color = palette.color(QPalette.Window)
        return bg_color.lightness() < 128
    except Exception:
        return True


import mistune


def _md_to_html(text, is_dark=True):
    """Convert markdown text to HTML for QTextEdit.append()."""
    if not text:
        return ""
    return mistune.html(text)

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
        self.ai_stream_thought_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        # Render markdown stream every 50ms, plus one forced final pass.
        self.ai_stream_render_interval_sec = 0.05
        self.ai_last_role = None
        self.ai_stream_has_thought = False
        self.ai_thinking_collapsed = False
        self.ai_stream_thought_collapsed = False
        self.ai_stream_thought_id = None
        self.ai_message_blocks = []

        self.setup_ui()
        self.refresh_placeholder()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        # Controls (hidden, values managed via Settings)
        self.ai_model = QLineEdit()
        self.ai_steps = QSpinBox()
        self.ai_steps.setRange(1, 20)
        self.ai_thinking_enabled = QCheckBox()

        # ── Chat area (takes most space) ──
        self.ai_chat = QTextEdit()
        self.ai_chat.setObjectName("aiChatArea")
        self.ai_chat.setReadOnly(True)
        self.ai_chat.setAcceptRichText(True)
        self.ai_chat.setPlaceholderText(tr("ai.chatPlaceholder"))
        self.ai_chat.document().setDefaultStyleSheet(
            "p { margin-top: 2px; margin-bottom: 2px; }"
        )
        self.ai_chat.viewport().installEventFilter(self)
        layout.addWidget(self.ai_chat, 1)

        # ── Bottom dock: prompt input + controls ──
        dock = QWidget()
        dock.setObjectName("aiPromptDock")
        dock_layout = QVBoxLayout(dock)
        dock_layout.setContentsMargins(0, 6, 0, 0)
        dock_layout.setSpacing(4)

        # Input container (rounded, subtle background)
        input_container = QWidget()
        input_container.setObjectName("aiInputContainer")
        ic_layout = QVBoxLayout(input_container)
        ic_layout.setContentsMargins(0, 4, 0, 4)
        ic_layout.setSpacing(2)

        self.ai_prompt = QTextEdit()
        self.ai_prompt.setObjectName("aiPromptInput")
        self.ai_prompt.setFixedHeight(72)
        self.ai_prompt.installEventFilter(self)
        ic_layout.addWidget(self.ai_prompt)

        # Action bar inside input container
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(8, 0, 8, 0)
        action_bar.setSpacing(4)

        self.ai_run_btn = QPushButton(tr("ai.runAgent"))
        self.ai_run_btn.setProperty("variant", "primary")
        self.ai_run_btn.setFixedHeight(24)
        self.ai_run_btn.clicked.connect(self.on_run_ai_agent)
        action_bar.addWidget(self.ai_run_btn)

        self.ai_stop_btn = QPushButton(tr("ai.stop"))
        self.ai_stop_btn.setFixedHeight(24)
        self.ai_stop_btn.setEnabled(False)
        self.ai_stop_btn.clicked.connect(self.on_stop_ai_agent)
        action_bar.addWidget(self.ai_stop_btn)

        ai_clear_btn = QPushButton(tr("ai.clear"))
        ai_clear_btn.setFixedHeight(24)
        ai_clear_btn.setProperty("variant", "ghost")
        ai_clear_btn.clicked.connect(self.on_clear)
        action_bar.addWidget(ai_clear_btn)

        action_bar.addStretch()

        # Shortcut hint (subtle, right-aligned)
        hint = QLabel("Enter ↵  Shift+Enter ⏎")
        hint.setProperty("muted", True)
        hint.setStyleSheet("font-size: 11px; padding-right: 2px;")
        action_bar.addWidget(hint)

        ic_layout.addLayout(action_bar)
        dock_layout.addWidget(input_container)

        layout.addWidget(dock)

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
        if (
            event.type() == QEvent.MouseButtonRelease
            and obj is self.ai_chat.viewport()
        ):
            self._handle_chat_anchor_click(event)
        return super().eventFilter(obj, event)

    def _handle_chat_anchor_click(self, event):
        if not isinstance(event, QMouseEvent):
            return
        pos = event.pos()
        doc = self.ai_chat.document()
        cursor = self.ai_chat.cursorForPosition(pos)
        anchor = cursor.charFormat().anchorHref()
        if anchor == "toggle_thought":
            self._toggle_current_thought_collapsed()

    def _toggle_current_thought_collapsed(self):
        if self.ai_streaming_active:
            if not self.ai_stream_has_thought or not self.ai_stream_thought_buffer:
                return
            self.ai_stream_thought_collapsed = not self.ai_stream_thought_collapsed
            self._rerender_stream_with_thought_markdown_in_place(force=True)
        else:
            if not hasattr(self.ai_chat, "textCursor"):
                return
            cursor = self.ai_chat.textCursor()
            click_pos = cursor.position()
            for block in reversed(self.ai_message_blocks):
                start = block.get("start")
                end = block.get("end")
                if start is not None and end is not None and start <= click_pos <= end:
                    block["collapsed"] = not block.get("collapsed", False)
                    self._rerender_saved_message_block(block)
                    break

    def _rerender_saved_message_block(self, block):
        if not isinstance(block, dict):
            return False
        start = block.get("start")
        end = block.get("end")
        if start is None or end is None:
            return False
        if not hasattr(self.ai_chat, "textCursor"):
            return False

        is_dark = _is_dark_mode(self)
        thought_buffer = block.get("thought_buffer", "")
        answer_buffer = block.get("answer_buffer", "")
        collapsed = block.get("collapsed", False)

        answer_html = _md_to_html(str(answer_buffer or ""), is_dark)

        combined_html = ""
        muted_color = _get_role_color("muted", is_dark)
        link_color = _get_role_color("link", is_dark)
        if thought_buffer:
            if collapsed:
                expand_text = tr("ai.expandThinking")
                combined_html += f'<div style="color: {muted_color}; font-style: italic;"><a href="toggle_thought" style="color: {muted_color};">Thinking... ({expand_text})</a></div>'
            else:
                thought_html = _md_to_html(str(thought_buffer or ""), is_dark)
                collapse_text = tr("ai.collapseThinking")
                combined_html += f'<div style="color: {muted_color};">{thought_html}<br/><a href="toggle_thought" style="color: {link_color};">[{collapse_text}]</a></div>'
        if answer_html:
            if combined_html:
                combined_html += "<br/>"
            combined_html += answer_html

        if not combined_html:
            return False

        try:
            cursor = self.ai_chat.textCursor()
            cursor.setPosition(int(start))
            cursor.setPosition(int(end), QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self._insert_markdown_with_cursor(cursor, combined_html)
            new_end = cursor.position()
            block["end"] = new_end
            delta = new_end - end
            for other_block in self.ai_message_blocks:
                if other_block is block:
                    continue
                other_start = other_block.get("start")
                other_end = other_block.get("end")
                if other_start is not None and other_start > end:
                    other_block["start"] = other_start + delta
                if other_end is not None and other_end > end:
                    other_block["end"] = other_end + delta
            self._move_chat_cursor_to_end()
            return True
        except Exception:
            return False

    def set_prompt(self, text):
        self.ai_prompt.setPlainText(str(text or "").strip())
        self.ai_prompt.setFocus()

    def refresh_placeholder(self):
        """Refresh placeholder with a random example (called once on init)."""
        if self.ai_prompt.toPlainText().strip():
            return
        from app_gui.i18n import get_language
        lang = get_language()
        pool = PLACEHOLDER_EXAMPLES_ZH if lang.startswith("zh") else PLACEHOLDER_EXAMPLES_EN
        self.ai_prompt.setPlaceholderText(random.choice(pool))

    def _reset_stream_thought_state(self):
        self.ai_stream_has_thought = False
        self.ai_stream_thought_buffer = ""
        self.ai_stream_thought_collapsed = False
        self.ai_stream_thought_id = None

    def _update_thinking_collapse_btn_text(self):
        if self.ai_thinking_collapsed:
            self.ai_thinking_collapse_btn.setText(tr("ai.expandThinking"))
        else:
            self.ai_thinking_collapse_btn.setText(tr("ai.collapseThinking"))

    def _toggle_thinking_collapse(self):
        self.ai_thinking_collapsed = not self.ai_thinking_collapsed
        self._update_thinking_collapse_btn_text()

    def on_clear(self):
        self.ai_chat.clear()
        self.ai_history = []
        self.ai_message_blocks = []
        self.ai_active_trace_id = None
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self._reset_stream_thought_state()
        self.status_message.emit(tr("ai.memoryCleared"), 2000)

    def _build_header_html(self, role, compact=False, is_dark=True):
        """Return header HTML string (no insertion)."""
        stamp = datetime.now().strftime("%H:%M:%S")
        color = _get_role_color(role, is_dark)
        self.ai_last_role = role

        if compact:
            return f'<span style="color: {color};">[{role}]</span> '
        return f'<br/><span style="color: {color}; font-weight: bold;">[{stamp}] {role}</span>'

    def _append_chat_header(self, role, compact=False):
        """Append a standalone header (used by stream + collapsible paths)."""
        is_dark = _is_dark_mode(self)
        self._move_chat_cursor_to_end()
        html = self._build_header_html(role, compact=compact, is_dark=is_dark)
        self.ai_chat.append(html)

    def _move_chat_cursor_to_end(self):
        if not hasattr(self.ai_chat, "textCursor") or not hasattr(self.ai_chat, "setTextCursor"):
            return
        cursor = self.ai_chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.ai_chat.setTextCursor(cursor)

    def _should_use_compact(self):
        """Check if tool messages should be compact (attached to previous message)."""
        return self.ai_last_role in ("You", "Agent", "Tool")

    def _append_tool_message(self, text):
        """Append tool message, using compact mode if appropriate."""
        compact = self._should_use_compact()
        self._append_chat("Tool", text, compact=compact)

    def _append_chat(self, role, text, compact=False):
        """Append header then content."""
        is_dark = _is_dark_mode(self)
        header_html = self._build_header_html(role, compact=compact, is_dark=is_dark)
        self._move_chat_cursor_to_end()
        if compact:
            # Compact: single line, inline formatting only (no block elements)
            body = str(text or "")
            body = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', body)
            body = re.sub(r'`([^`]+)`', r'\1', body)
            self.ai_chat.append(header_html + body)
        else:
            body_html = _md_to_html(str(text or ""), is_dark)
            self.ai_chat.append(header_html)
            self.ai_chat.append(body_html)

    def _begin_stream_chat(self, role="Agent"):
        if self.ai_streaming_active:
            return
        self.ai_streaming_active = True
        self.ai_stream_buffer = ""
        self.ai_stream_thought_buffer = ""
        self.ai_stream_has_thought = False
        self.ai_stream_thought_collapsed = self.ai_thinking_collapsed
        self.ai_stream_thought_id = f"thought_{id(self)}_{time.monotonic_ns()}"
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self._append_chat_header(role)
        self.ai_chat.append("")
        self._move_chat_cursor_to_end()
        if hasattr(self.ai_chat, "textCursor"):
            self.ai_stream_start_pos = self.ai_chat.textCursor().position()

    def _append_stream_chunk(self, text, channel="answer"):
        chunk = str(text or "")
        if not chunk:
            return

        stream_channel = str(channel or "answer").strip().lower()
        if stream_channel not in {"answer", "thought"}:
            stream_channel = "answer"

        is_first_answer_after_thought = (
            stream_channel == "answer"
            and self.ai_stream_has_thought
            and not self.ai_stream_buffer
        )

        if not self.ai_streaming_active:
            self._begin_stream_chat("Agent")

        if stream_channel == "thought":
            self.ai_stream_has_thought = True
            self.ai_stream_thought_buffer += chunk
        else:
            self.ai_stream_buffer += chunk

        # Fallback for minimal chat stubs without cursor APIs (unit tests).
        if not hasattr(self.ai_chat, "textCursor"):
            if is_first_answer_after_thought:
                self.ai_chat.insertPlainText("\n")
            self.ai_chat.insertPlainText(chunk)
            return

        self._rerender_stream_with_thought_markdown_in_place(force=False)

    def _end_stream_chat(self):
        if not self.ai_streaming_active:
            return

        self._rerender_stream_with_thought_markdown_in_place(force=True)

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

        if self.ai_stream_has_thought and self.ai_stream_thought_buffer:
            self.ai_message_blocks.append({
                "start": start_pos,
                "end": end_pos,
                "thought_buffer": self.ai_stream_thought_buffer,
                "answer_buffer": self.ai_stream_buffer,
                "collapsed": self.ai_stream_thought_collapsed,
            })

        self.ai_chat.append("")
        self.ai_streaming_active = False
        self.ai_stream_start_pos = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self._reset_stream_thought_state()

    def _replace_stream_block_with_html(self, block, html_text):
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
            self._insert_markdown_with_cursor(cursor, str(html_text or ""))
            self._move_chat_cursor_to_end()
            return True
        except Exception:
            return False

    def _rerender_stream_with_thought_markdown_in_place(self, force=False):
        if not self.ai_streaming_active:
            return False
        if self.ai_stream_start_pos is None:
            return False
        if not hasattr(self.ai_chat, "textCursor"):
            return False

        interval = max(0.0, float(self.ai_stream_render_interval_sec or 0.0))
        now = time.monotonic()
        if not force and interval > 0.0 and (now - float(self.ai_stream_last_render_ts or 0.0)) < interval:
            return False

        self._move_chat_cursor_to_end()
        end_pos = self.ai_chat.textCursor().position()
        block = {
            "start": self.ai_stream_start_pos,
            "end": end_pos,
            "text": self.ai_stream_buffer,
        }

        is_dark = _is_dark_mode(self)
        answer_html = _md_to_html(str(self.ai_stream_buffer or ""), is_dark)

        combined_html = ""
        muted_color = _get_role_color("muted", is_dark)
        link_color = _get_role_color("link", is_dark)
        if self.ai_stream_has_thought and self.ai_stream_thought_buffer:
            if self.ai_stream_thought_collapsed:
                expand_text = tr("ai.expandThinking")
                combined_html += f'<div style="color: {muted_color}; font-style: italic;"><a href="toggle_thought" style="color: {muted_color};">Thinking... ({expand_text})</a></div>'
            else:
                thought_html = _md_to_html(str(self.ai_stream_thought_buffer or ""), is_dark)
                collapse_text = tr("ai.collapseThinking")
                combined_html += f'<div style="color: {muted_color};">{thought_html}<br/><a href="toggle_thought" style="color: {link_color};">[{collapse_text}]</a></div>'
        if answer_html:
            if combined_html:
                combined_html += "<br/>"
            combined_html += answer_html

        if not combined_html:
            return False

        ok = self._replace_stream_block_with_html(block, combined_html)
        if not ok:
            return False

        self.ai_stream_last_render_ts = now
        self.ai_stream_last_render_len = len(self.ai_stream_buffer) + len(self.ai_stream_thought_buffer)

        self._move_chat_cursor_to_end()
        new_end = self.ai_chat.textCursor().position()
        self.ai_last_stream_block = {
            "start": self.ai_stream_start_pos,
            "end": new_end,
            "text": self.ai_stream_buffer,
        }
        return True

    def _insert_markdown_with_cursor(self, cursor, html_text):
        """Insert pre-rendered HTML at cursor position (used by streaming rerender)."""
        html_text = str(html_text or "")
        if cursor is not None and hasattr(self.ai_chat, "setTextCursor"):
            self.ai_chat.setTextCursor(cursor)

        if hasattr(self.ai_chat, "textCursor"):
            cursor = self.ai_chat.textCursor()
            cursor.insertHtml(html_text)
            if hasattr(self.ai_chat, "setTextCursor"):
                self.ai_chat.setTextCursor(cursor)
            return

        self.ai_chat.insertPlainText(html_text)

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
            is_dark = _is_dark_mode(self)
            highlighted = _md_to_html(str(markdown_text or ""), is_dark)
            self._insert_markdown_with_cursor(cursor, highlighted)
            self._move_chat_cursor_to_end()
            return True
        except Exception:
            return False

    def on_run_ai_agent(self):
        if self.ai_run_inflight:
            return
        
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
        )
        self.ai_run_thread = QThread(self)
        self.ai_run_worker.moveToThread(self.ai_run_thread)
        
        self.ai_run_thread.started.connect(self.ai_run_worker.run)
        self.ai_run_worker.progress.connect(self.on_progress)
        self.ai_run_worker.plan_staged.connect(self.plan_items_staged.emit)
        self.ai_run_worker.question_asked.connect(self._handle_question_event)
        self.ai_run_worker.finished.connect(self.on_finished)
        self.ai_run_worker.finished.connect(self.ai_run_thread.quit)
        self.ai_run_worker.finished.connect(self.ai_run_worker.deleteLater)
        self.ai_run_thread.finished.connect(self.ai_run_thread.deleteLater)
        self.ai_run_thread.finished.connect(self.on_thread_finished)
        
        self.set_busy(True)
        self.ai_run_thread.start()

    def _handle_question_event(self, event_data):
        """Handle question event from agent — show dialog, unblock worker."""
        if event_data.get("type") == "max_steps_ask":
            return self._handle_max_steps_ask(event_data)

        questions = event_data.get("questions", [])
        if not questions:
            if self.ai_run_worker:
                self.ai_run_worker.cancel_answer()
            return

        if self.ai_streaming_active:
            self._end_stream_chat()
        self._append_tool_message(tr("ai.questionAsking"))

        answers = self._show_question_dialog(questions)

        if answers is not None:
            if self.ai_run_worker:
                self.ai_run_worker.set_answer(answers)
        else:
            if self.ai_run_worker:
                self.ai_run_worker.cancel_answer()

    def _handle_max_steps_ask(self, event_data):
        """System-level prompt when max_steps is reached — ask user to continue or stop."""
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

    def _show_question_dialog(self, questions):
        """Modal dialog for user to answer agent questions.

        Returns list of answers, or None if cancelled.
        """
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QComboBox,
            QLineEdit, QCheckBox, QDialogButtonBox,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ai.questionTitle"))
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)

        answer_widgets = []

        for q in questions:
            header = q.get("header", "")
            question_text = q.get("question", "")
            options = q.get("options", [])
            multiple = q.get("multiple", False)

            label = QLabel(f"<b>{header}</b>: {question_text}")
            label.setWordWrap(True)
            layout.addWidget(label)

            if options and multiple:
                checkbox_group = []
                for opt in options:
                    cb = QCheckBox(opt)
                    layout.addWidget(cb)
                    checkbox_group.append(cb)
                answer_widgets.append(("checkbox_group", checkbox_group))
            elif options:
                combo = QComboBox()
                combo.addItems(options)
                layout.addWidget(combo)
                answer_widgets.append(("combo", combo))
            else:
                edit = QLineEdit()
                layout.addWidget(edit)
                answer_widgets.append(("text", edit))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            answers = []
            for widget_type, widget in answer_widgets:
                if widget_type == "checkbox_group":
                    answers.append([cb.text() for cb in widget if cb.isChecked()])
                elif widget_type == "combo":
                    answers.append(widget.currentText())
                else:
                    answers.append(widget.text())
            return answers
        return None

    def on_stop_ai_agent(self):
        if self.ai_run_thread and self.ai_run_thread.isRunning():
            # Terminate is harsh, but ReactAgent is sync.
            # We will just detach signals and kill it.
            # Ideally we have a 'stop' flag in worker, but worker is running a blocking call.
            self.ai_run_thread.terminate()
            self.set_busy(False)
            self._append_chat("System", tr("ai.runStopped"))
            self.status_message.emit(tr("ai.aiRunStopped"), 3000)

    def set_busy(self, busy):
        self.ai_run_inflight = busy
        self.ai_run_btn.setEnabled(not busy)
        self.ai_run_btn.setText(tr("ai.running") if busy else tr("ai.runAgent"))
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
            return

        if event_type == "tool_start":
            if self.ai_streaming_active:
                self._end_stream_chat()

            data = event.get("data") or {}
            name = str(data.get("name") or event.get("action") or "tool")
            self._append_tool_message(f"Running `{name}`...")
            return

        if event_type == "chunk":
            chunk = event.get("data")
            channel = str(((event.get("meta") or {}).get("channel") or "answer")).strip().lower()
            if isinstance(chunk, str) and chunk:
                self._append_stream_chunk(chunk, channel=channel)
            return

        if event_type == "error":
            err = event.get("data") or event.get("message") or "unknown error"
            return

        if event_type == "stream_end":
            status = (event.get("data") or {}).get("status")
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

        if event_type == "max_steps":
            pass

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

        elif event_type == "plan_cleared":
            cleared_count = event.get("cleared_count", 0)
            action_counts = event.get("action_counts") if isinstance(event.get("action_counts"), dict) else {}
            parts = []
            for k, v in sorted(action_counts.items(), key=lambda kv: str(kv[0])):
                try:
                    parts.append(f"{k}={int(v)}")
                except Exception:
                    parts.append(f"{k}={v}")
            breakdown = f" ({', '.join(parts)})" if parts else ""
            summary_text = f"**Plan cleared**: {cleared_count} item(s) removed{breakdown}"
            self._append_chat_with_collapsible("System", summary_text, details_json)

    def _append_chat_with_collapsible(self, role, summary, details_json):
        is_dark = _is_dark_mode(self)
        header_html = self._build_header_html(role, is_dark=is_dark)
        body_html = _md_to_html(str(summary or ""), is_dark)
        self._move_chat_cursor_to_end()
        self.ai_chat.append(header_html)
        self.ai_chat.append(body_html)

        details_text = str(details_json or "")
        escaped_details = details_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        collapsible_html = CollapsibleBox.render_html(
            summary="📋 Details",
            content=escaped_details,
            is_dark=is_dark,
            collapsed=True,
            max_preview_chars=80
        )

        self._move_chat_cursor_to_end()
        if hasattr(self.ai_chat, "textCursor"):
            cursor = self.ai_chat.textCursor()
            cursor.insertHtml(collapsible_html)
        else:
            self.ai_chat.append(collapsible_html)

        self.ai_chat.append("")

    def _load_audit(self, trace_id, run_result):
        pass
