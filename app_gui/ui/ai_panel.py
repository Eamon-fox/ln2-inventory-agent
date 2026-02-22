from datetime import datetime
import time
import re
import random
from PySide6.QtCore import Qt, Signal, QEvent, QSize
from PySide6.QtGui import QTextCursor, QPalette, QMouseEvent, QActionGroup
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QMenu,
    QTextEdit, QSpinBox, QCheckBox
)
from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS
from app_gui.ui.theme import FONT_SIZE_XS, FONT_SIZE_SM, MONO_FONT_CSS_FAMILY, resolve_theme_token
from app_gui.ui.icons import get_icon, Icons
from app_gui.system_notice import build_system_notice, coerce_system_notice
from app_gui.i18n import tr
from app_gui.ui import ai_panel_notice as _ai_notice
from app_gui.ui import ai_panel_event_details as _ai_event_details
from app_gui.ui import ai_panel_runtime as _ai_runtime


_ROLE_COLOR_TOKENS = {
    "Agent": "chat-role-agent",
    "You": "chat-role-you",
    "Tool": "chat-role-tool",
    "System": "chat-role-system",
    "muted": "chat-role-muted",
    "link": "chat-role-link",
}


def _get_role_color(role, is_dark=True):
    theme = "dark" if is_dark else "light"
    token_name = _ROLE_COLOR_TOKENS.get(str(role))
    if not token_name:
        return resolve_theme_token("chat-role-you", mode=theme, fallback="#a3e635")
    return resolve_theme_token(token_name, mode=theme, fallback="#a3e635")


PLACEHOLDER_EXAMPLES_EN = [
    "Find K562-related records and summarize count",
    "List today's takeout events",
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
    status_message = Signal(str, int) # msg, timeout

    def __init__(self, bridge, yaml_path_getter, plan_store=None, manage_boxes_request_handler=None):
        super().__init__()
        self.bridge = bridge
        self.yaml_path_getter = yaml_path_getter
        self._plan_store = plan_store
        self._manage_boxes_request_handler = manage_boxes_request_handler
        
        self.ai_history = []
        self.ai_operation_events = []
        self.ai_run_inflight = False
        self.ai_stop_requested = False
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
        self.ai_collapsible_blocks = []

        self.setup_ui()
        self.refresh_placeholder()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)

        # Controls (hidden, values managed via Settings)
        self.ai_provider = QLineEdit()
        self.ai_model = QLineEdit()
        self.ai_steps = QSpinBox()
        self.ai_steps.setRange(1, 20)
        self.ai_thinking_enabled = QCheckBox()
        self.ai_custom_prompt = ""
        provider_cfg = PROVIDER_DEFAULTS.get(DEFAULT_PROVIDER, {})
        self.ai_provider.setText(DEFAULT_PROVIDER)
        self.ai_model.setText(str(provider_cfg.get("model") or "").strip())

        # Chat area (takes most space)
        self.ai_chat = QTextEdit()
        self.ai_chat.setObjectName("aiChatArea")
        self.ai_chat.setReadOnly(True)
        self.ai_chat.setAcceptRichText(True)
        self.ai_chat.setPlaceholderText(tr("ai.chatPlaceholder"))
        self.ai_chat.document().setDefaultStyleSheet(
            "p { margin-top: 2px; margin-bottom: 2px; }"
        )
        self.ai_chat.viewport().installEventFilter(self)
        self.ai_chat.viewport().setCursor(Qt.ArrowCursor)
        layout.addWidget(self.ai_chat, 1)

        # Bottom dock: prompt input + controls
        dock = QWidget()
        dock.setObjectName("aiPromptDock")
        dock_layout = QVBoxLayout(dock)
        dock_layout.setContentsMargins(0, 6, 0, 0)
        dock_layout.setSpacing(4)

        # Input container (rounded, subtle background)
        input_container = QWidget()
        input_container.setObjectName("aiInputContainer")
        ic_layout = QVBoxLayout(input_container)
        ic_layout.setContentsMargins(0, 4, 0, 0)
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

        self.ai_model_id_label = QLabel("")
        self.ai_model_id_label.setObjectName("aiModelIdLabel")
        self.ai_model_id_label.setProperty("role", "mutedInline")
        action_bar.addWidget(self.ai_model_id_label)

        self.ai_model_switch_btn = QPushButton("^")
        self.ai_model_switch_btn.setObjectName("aiModelSwitchBtn")
        self.ai_model_switch_btn.setFixedSize(18, 18)
        self.ai_model_switch_btn.setProperty("variant", "ghost")
        self.ai_model_switch_btn.setToolTip(tr("settings.aiModel"))
        self.ai_model_switch_btn.clicked.connect(self._open_model_switch_menu)
        action_bar.addWidget(self.ai_model_switch_btn)

        action_bar.addStretch()

        ai_clear_btn = QPushButton(tr("ai.clear"))
        ai_clear_btn.setIcon(get_icon(Icons.X))
        ai_clear_btn.setIconSize(QSize(16, 16))
        ai_clear_btn.setMinimumWidth(60)
        ai_clear_btn.setProperty("variant", "ghost")
        ai_clear_btn.clicked.connect(self.on_clear)
        action_bar.addWidget(ai_clear_btn)

        self.ai_run_btn = QPushButton(tr("ai.runAgent"))
        self.ai_run_btn.setIcon(get_icon(Icons.PLAY, color="#ffffff"))  # White icon for primary variant
        self.ai_run_btn.setIconSize(QSize(16, 16))
        self.ai_run_btn.setProperty("variant", "primary")
        self.ai_run_btn.setMinimumWidth(60)
        self.ai_run_btn.clicked.connect(self._on_run_stop_toggle)
        action_bar.addWidget(self.ai_run_btn)

        ic_layout.addLayout(action_bar)
        dock_layout.addWidget(input_container)

        layout.addWidget(dock)
        self.ai_provider.textChanged.connect(self._refresh_model_badge)
        self.ai_model.textChanged.connect(self._refresh_model_badge)
        self._refresh_model_badge()

    def _iter_model_switch_options(self):
        options = []
        seen = set()

        current_provider = self.ai_provider.text().strip() or DEFAULT_PROVIDER
        current_model = self.ai_model.text().strip()
        if current_model:
            key = (current_provider, current_model)
            seen.add(key)
            options.append({
                "provider": current_provider,
                "model": current_model,
            })

        for provider_id, provider_cfg in PROVIDER_DEFAULTS.items():
            cfg = provider_cfg if isinstance(provider_cfg, dict) else {}
            candidates = []
            for raw_model in cfg.get("models") or []:
                model_id = str(raw_model or "").strip()
                if model_id:
                    candidates.append(model_id)
            default_model = str(cfg.get("model") or "").strip()
            if default_model:
                candidates.append(default_model)

            for model_id in candidates:
                key = (provider_id, model_id)
                if key in seen:
                    continue
                seen.add(key)
                options.append({
                    "provider": provider_id,
                    "model": model_id,
                })
        return options

    def _refresh_model_badge(self):
        model_id = self.ai_model.text().strip() or "-"
        provider_id = self.ai_provider.text().strip() or DEFAULT_PROVIDER
        self.ai_model_id_label.setText(model_id)
        self.ai_model_id_label.setToolTip(f"{provider_id}:{model_id}")
        self.ai_model_switch_btn.setEnabled((not self.ai_run_inflight) and bool(self._iter_model_switch_options()))

    def _open_model_switch_menu(self):
        if self.ai_run_inflight:
            return
        options = self._iter_model_switch_options()
        if not options:
            return

        current_provider = self.ai_provider.text().strip() or DEFAULT_PROVIDER
        current_model = self.ai_model.text().strip()

        menu = QMenu(self)
        single_select_group = QActionGroup(self)
        single_select_group.setExclusive(True)
        action_to_option = {}
        for option in options:
            provider_id = str(option.get("provider") or "").strip()
            model_id = str(option.get("model") or "").strip()
            text = f"{model_id} ({provider_id})"
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setActionGroup(single_select_group)
            action.setChecked(provider_id == current_provider and model_id == current_model)
            action_to_option[action] = option

        chosen = menu.exec(self.ai_model_switch_btn.mapToGlobal(self.ai_model_switch_btn.rect().bottomLeft()))
        selected = action_to_option.get(chosen)
        if not selected:
            return

        self.ai_provider.setText(str(selected.get("provider") or "").strip())
        self.ai_model.setText(str(selected.get("model") or "").strip())

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
            if self._handle_chat_anchor_click(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_chat_anchor_click(self, event):
        if not isinstance(event, QMouseEvent):
            return False
        anchor = self.ai_chat.anchorAt(event.position().toPoint())
        if not anchor:
            return False
        if anchor == "toggle_thought":
            self._toggle_current_thought_collapsed()
        elif anchor.startswith("toggle_details_"):
            self._toggle_collapsible_block(anchor)
        else:
            return False
        return True

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
            self._shift_block_ranges(
                self.ai_message_blocks,
                after_end=end,
                delta=delta,
                exclude=block,
            )
            self._move_chat_cursor_to_end()
            return True
        except Exception:
            return False

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

    def on_clear(self):
        self.ai_chat.clear()
        self.ai_history = []
        self.ai_message_blocks = []
        self.ai_collapsible_blocks = []
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

    @staticmethod
    def _escape_html_text(value):
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _shift_block_ranges(self, blocks, *, after_end, delta, exclude=None):
        if not delta:
            return
        for other in blocks or []:
            if other is exclude or not isinstance(other, dict):
                continue
            other_start = other.get("start")
            other_end = other.get("end")
            if other_start is not None and other_start > after_end:
                other["start"] = other_start + delta
            if other_end is not None and other_end > after_end:
                other["end"] = other_end + delta

    def _append_chat_markdown_block(self, role, text, *, is_dark=None):
        if is_dark is None:
            is_dark = _is_dark_mode(self)
        header_html = self._build_header_html(role, is_dark=is_dark)
        body_html = _md_to_html(str(text or ""), is_dark)
        self._move_chat_cursor_to_end()
        self.ai_chat.append(header_html)
        self.ai_chat.append(body_html)

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
        if compact:
            header_html = self._build_header_html(role, compact=True, is_dark=is_dark)
            self._move_chat_cursor_to_end()
            # Compact: single line, inline formatting only (no block elements)
            body = str(text or "")
            body = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', body)
            body = re.sub(r'`([^`]+)`', r'\1', body)
            self.ai_chat.append(header_html + body)
        else:
            self._append_chat_markdown_block(role, text, is_dark=is_dark)

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

    _on_run_stop_toggle = _ai_runtime._on_run_stop_toggle
    on_run_ai_agent = _ai_runtime.on_run_ai_agent
    start_worker = _ai_runtime.start_worker
    _handle_question_event = _ai_runtime._handle_question_event
    _handle_manage_boxes_confirm = _ai_runtime._handle_manage_boxes_confirm
    _handle_max_steps_ask = _ai_runtime._handle_max_steps_ask
    _show_question_dialog = _ai_runtime._show_question_dialog
    on_stop_ai_agent = _ai_runtime.on_stop_ai_agent
    set_busy = _ai_runtime.set_busy
    on_progress = _ai_runtime.on_progress
    _extract_progress_observation = _ai_runtime._extract_progress_observation
    _handle_progress_tool_end = _ai_runtime._handle_progress_tool_end
    _handle_progress_tool_start = _ai_runtime._handle_progress_tool_start
    _handle_progress_chunk = _ai_runtime._handle_progress_chunk
    _handle_progress_step_end = _ai_runtime._handle_progress_step_end
    _handle_progress_error = staticmethod(_ai_runtime._handle_progress_error)
    _handle_progress_stream_end = staticmethod(_ai_runtime._handle_progress_stream_end)
    _handle_progress_max_steps = staticmethod(_ai_runtime._handle_progress_max_steps)
    on_finished = _ai_runtime.on_finished
    on_thread_finished = _ai_runtime.on_thread_finished

    _format_blocked_item = staticmethod(_ai_notice._format_blocked_item)
    _blocked_items_summary = _ai_notice._blocked_items_summary
    _single_line_text = staticmethod(_ai_notice._single_line_text)
    _trf = staticmethod(_ai_notice._trf)
    _format_notice_operation = _ai_notice._format_notice_operation
    _extract_notice_operation_lines = _ai_notice._extract_notice_operation_lines
    _format_system_notice_details = _ai_notice._format_system_notice_details
    _normalize_notice_lines_for_compare = _ai_notice._normalize_notice_lines_for_compare
    _should_hide_notice_details_line = _ai_notice._should_hide_notice_details_line
    _extract_notice_meta_lines = _ai_notice._extract_notice_meta_lines

    def _append_history(self, role, text):
        self.ai_history.append({"role": role, "content": text})
        if len(self.ai_history) > 20:
            self.ai_history = self.ai_history[-20:]

    def _render_system_notice(self, notice):
        """Render one normalized notice to chat with expandable raw payload."""
        summary_text = str(notice.get("text") or notice.get("code") or "System notice")
        # Keep system notice details fully collapsed by default; show only summary sentence.
        self._append_chat_with_collapsible(
            "System",
            summary_text,
            notice,
            collapsed_preview_lines=0,
        )

    def on_operation_event(self, event):
        """Receive operation events and normalize them to one notice shape."""
        raw_event = event if isinstance(event, dict) else {"message": str(event)}
        notice = coerce_system_notice(raw_event)
        if notice is None:
            notice = build_system_notice(
                code="event.raw",
                text=str(raw_event.get("message") or "System event"),
                level="info",
                source=str(raw_event.get("source") or "operations"),
                data={"legacy_event": raw_event},
            )
            if raw_event.get("timestamp"):
                notice["timestamp"] = raw_event.get("timestamp")

        self.ai_operation_events.append(notice)
        if len(self.ai_operation_events) > 20:
            self.ai_operation_events = self.ai_operation_events[-20:]

        self._render_system_notice(notice)

    _format_event_details = _ai_event_details._format_event_details
    _append_event_type_details = _ai_event_details._append_event_type_details
    _append_plan_count_lines = _ai_event_details._append_plan_count_lines
    _append_box_layout_lines = _ai_event_details._append_box_layout_lines
    _append_plan_execution_lines = _ai_event_details._append_plan_execution_lines
    _append_plan_execution_report = _ai_event_details._append_plan_execution_report
    _append_plan_execution_rollback = _ai_event_details._append_plan_execution_rollback
    _build_event_fallback_lines = staticmethod(_ai_event_details._build_event_fallback_lines)

    def _append_chat_with_collapsible(self, role, summary, details_json, collapsed_preview_lines=3):
        is_dark = _is_dark_mode(self)
        self._append_chat_markdown_block(role, summary, is_dark=is_dark)

        # Format details as human-readable text instead of raw JSON
        details_text = self._format_event_details(details_json)
        block_id = f"toggle_details_{len(self.ai_collapsible_blocks)}"
        collapsed_html = self._render_collapsible_details(
            block_id,
            details_text,
            collapsed=True,
            is_dark=is_dark,
            preview_lines=collapsed_preview_lines,
        )

        self._move_chat_cursor_to_end()
        if not hasattr(self.ai_chat, "textCursor"):
            self.ai_chat.append(collapsed_html)
            self.ai_chat.append("")
            return
        cursor = self.ai_chat.textCursor()
        start = cursor.position()
        cursor.insertHtml(collapsed_html)
        end = cursor.position()

        self.ai_collapsible_blocks.append({
            "block_id": block_id,
            "start": start,
            "end": end,
            "content": details_text,
            "collapsed": True,
            "preview_lines": max(0, int(collapsed_preview_lines or 0)),
        })
        self.ai_chat.append("")

    def _render_collapsible_details(self, block_id, content, collapsed=True, is_dark=True, preview_lines=3):
        """Render details as a collapsible code block with configurable collapsed preview."""
        mode = "dark" if is_dark else "light"
        bg = resolve_theme_token("chat-panel-bg", mode=mode, fallback="#1f1f1f")
        border = resolve_theme_token("chat-panel-border", mode=mode, fallback="rgba(255,255,255,0.08)")
        text_color = resolve_theme_token("chat-code-text", mode=mode, fallback="#c8c8c8")
        link_color = resolve_theme_token("chat-link", mode=mode, fallback="#38bdf8")

        escaped = self._escape_html_text(content)

        if collapsed:
            lines = content.split('\n')
            preview_limit = max(0, int(preview_lines or 0))
            preview_lines = lines[:preview_limit] if preview_limit > 0 else []
            preview = '\n'.join(preview_lines)
            preview_escaped = self._escape_html_text(preview)
            has_more = len(lines) > preview_limit

            if has_more:
                if preview:
                    # Keep preview in a framed block when preview lines are requested.
                    html = (
                        f'<table style="margin: 4px 0; border: 1px solid {border}; border-radius: 4px; '
                        f'background: {bg}; padding: 0; width: 100%; border-collapse: collapse;">'
                        f'<tr><td style="padding: 6px 8px; font-family: {MONO_FONT_CSS_FAMILY}; font-size: {FONT_SIZE_SM}px; '
                        f'color: {text_color}; white-space: pre-wrap;">'
                        f'<a href="{block_id}" style="color: {link_color}; font-size: {FONT_SIZE_XS}px; '
                        f'text-decoration: none;">&#9660; Expand ({len(lines)} lines)</a>'
                        f'<br/>{preview_escaped}'
                        f'</td></tr></table>'
                    )
                else:
                    # With zero preview lines, use inline link to avoid occupying an extra row.
                    html = (
                        f'<a href="{block_id}" style="color: {link_color}; font-size: {FONT_SIZE_XS}px; '
                        f'text-decoration: none;">&#9660; Expand ({len(lines)} lines)</a>'
                    )
            else:
                # No expand link needed if no content to show
                html = (
                    f'<div style="margin: 4px 0; border: 1px solid {border}; border-radius: 4px; '
                    f'background: {bg}; padding: 6px 8px; font-family: {MONO_FONT_CSS_FAMILY}; font-size: {FONT_SIZE_SM}px; '
                    f'color: {text_color}; white-space: pre-wrap; overflow: hidden;">'
                )
                if preview:
                    html += f'{preview_escaped}'
                html += '</div>'
        else:
            preview_limit = max(0, int(preview_lines or 0))
            if preview_limit <= 0:
                # Keep toggle link at the same anchor position as collapsed state.
                html = (
                    f'<a href="{block_id}" style="color: {link_color}; font-size: {FONT_SIZE_XS}px; '
                    f'text-decoration: none;">&#9650; Collapse</a>'
                    f'<div style="margin: 4px 0 0 0; border: 1px solid {border}; border-radius: 4px; '
                    f'background: {bg}; padding: 6px 8px; font-family: {MONO_FONT_CSS_FAMILY}; font-size: {FONT_SIZE_SM}px; '
                    f'color: {text_color}; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">'
                    f'{escaped}</div>'
                )
            else:
                # Use table structure to completely isolate link from content
                html = (
                    f'<table style="margin: 4px 0; border: 1px solid {border}; border-radius: 4px; '
                    f'background: {bg}; padding: 0; width: 100%; border-collapse: collapse;">'
                    f'<tr><td style="padding: 6px 8px; border-bottom: 1px solid {border};">'
                    f'<a href="{block_id}" style="color: {link_color}; font-size: {FONT_SIZE_XS}px; '
                    f'text-decoration: none;">&#9650; Collapse</a></td></tr>'
                    f'<tr><td style="padding: 6px 8px; font-family: {MONO_FONT_CSS_FAMILY}; font-size: {FONT_SIZE_SM}px; '
                    f'color: {text_color}; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">'
                    f'{escaped}</td></tr>'
                    f'</table>'
                )
        return html

    def _toggle_collapsible_block(self, block_id):
        """Toggle a collapsible details block between collapsed and expanded."""
        block = None
        for b in self.ai_collapsible_blocks:
            if b["block_id"] == block_id:
                block = b
                break
        if block is None:
            return

        block["collapsed"] = not block["collapsed"]
        is_dark = _is_dark_mode(self)
        new_html = self._render_collapsible_details(
            block_id,
            block["content"],
            collapsed=block["collapsed"],
            is_dark=is_dark,
            preview_lines=block.get("preview_lines", 3),
        )

        start = block["start"]
        end = block["end"]
        try:
            cursor = self.ai_chat.textCursor()
            cursor.setPosition(int(start))
            cursor.setPosition(int(end), QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertHtml(new_html)
            new_end = cursor.position()
            delta = new_end - end
            block["end"] = new_end
            self._shift_block_ranges(
                self.ai_collapsible_blocks,
                after_end=end,
                delta=delta,
                exclude=block,
            )
            self._shift_block_ranges(
                self.ai_message_blocks,
                after_end=end,
                delta=delta,
            )
        except Exception:
            pass

    def _load_audit(self, trace_id, run_result):
        pass


