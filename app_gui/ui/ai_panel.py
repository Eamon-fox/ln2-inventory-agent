from datetime import datetime
from contextlib import suppress
import time
import re
import random
from PySide6.QtCore import Qt, Signal, QEvent, QSize, QTimer
from PySide6.QtGui import QTextCursor, QTextBlockFormat, QPalette, QMouseEvent, QActionGroup
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QMenu,
    QTextEdit, QSpinBox, QCheckBox
)
from app_gui.application.ai_provider_catalog import (
    AI_PROVIDER_DEFAULTS,
    DEFAULT_AI_PROVIDER,
    normalize_ai_provider,
)
from app_gui.gui_config import AI_HISTORY_LIMIT, AI_OPERATION_EVENT_POOL_LIMIT, MAX_AGENT_STEPS
from app_gui.ui.theme import FONT_SIZE_XS, FONT_SIZE_SM, MONO_FONT_CSS_FAMILY, resolve_theme_token
from app_gui.ui.icons import get_icon, Icons
from app_gui.system_notice import build_system_notice, coerce_system_notice
from app_gui.i18n import tr
from app_gui.ui import ai_panel_notice as _ai_notice
from app_gui.ui import ai_panel_event_details as _ai_event_details
from app_gui.ui import ai_panel_runtime as _ai_runtime
from app_gui.ui.activity_indicator import ActivityIndicator


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


from app_gui.ui.utils import md_to_html


def _md_to_html(text, is_dark=True):
    """Convert markdown text to HTML for QTextEdit.append()."""
    return md_to_html(text)

class AIPanel(QWidget):
    operation_completed = Signal(bool)
    status_message = Signal(str, int) # msg, timeout
    migration_mode_changed = Signal(bool)

    def __init__(
        self,
        bridge,
        yaml_path_getter,
        plan_store=None,
        manage_boxes_request_handler=None,
        import_dataset_handler=None,
        agent_session=None,
    ):
        super().__init__()
        self.bridge = bridge
        self.agent_session = agent_session
        self.yaml_path_getter = yaml_path_getter
        self._plan_store = plan_store
        self._manage_boxes_request_handler = manage_boxes_request_handler
        self._import_dataset_handler = import_dataset_handler
        self._migration_mode_enabled = False
        
        self.ai_history = []
        self.ai_summary_state = None
        self._prompt_history = []      # past user prompts (oldest first)
        self._prompt_history_index = -1  # -1 = not browsing
        self._prompt_history_stash = ""  # stash current input while browsing
        self.ai_operation_events = []
        self.ai_run_inflight = False
        self.ai_stop_requested = False
        self.ai_run_thread = None
        self.ai_run_worker = None
        self.ai_active_trace_id = None
        self._history_snapshot_from_stream_end = False
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
        self.ai_collapsible_blocks = []
        self.ai_auto_follow_enabled = True
        self.ai_unseen_message_count = 0
        self.ai_scroll_bottom_threshold_px = 24
        self.ai_programmatic_scroll_lock = False
        self.ai_chat_write_in_progress = False
        self._run_btn_attention_timer = None
        self._run_btn_attention_toggles_remaining = 0
        self._floating_dialog_refs = []
        self._pending_ai_dialog_state = None

        self.setup_ui()
        self.refresh_placeholder()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)

        self._migration_mode_banner = QLabel(tr("ai.migrationModeBanner"))
        self._migration_mode_banner.setObjectName("aiMigrationModeBanner")
        self._migration_mode_banner.setWordWrap(True)
        self._migration_mode_banner.setVisible(False)
        layout.addWidget(self._migration_mode_banner)

        # Controls (hidden, values managed via Settings)
        self.ai_provider = QLineEdit()
        self.ai_model = QLineEdit()
        self.ai_steps = QSpinBox()
        self.ai_steps.setRange(1, MAX_AGENT_STEPS)
        self.ai_thinking_enabled = QCheckBox()
        self.ai_custom_prompt = ""
        provider_cfg = AI_PROVIDER_DEFAULTS.get(DEFAULT_AI_PROVIDER, {})
        self.ai_provider.setText(DEFAULT_AI_PROVIDER)
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

        self.ai_new_msg_btn = QPushButton(self.ai_chat.viewport())
        self.ai_new_msg_btn.setObjectName("aiNewMessagesButton")
        self.ai_new_msg_btn.setProperty("variant", "ghost")
        self.ai_new_msg_btn.setIcon(get_icon(Icons.CHEVRON_DOWN))
        self.ai_new_msg_btn.setVisible(False)
        self.ai_new_msg_btn.clicked.connect(self._jump_to_chat_bottom)

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

        status_row = QWidget()
        status_row.setObjectName("aiStatusRow")
        status_row_layout = QHBoxLayout(status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(4)

        self.ai_model_id_label = QLabel("")
        self.ai_model_id_label.setObjectName("aiModelIdLabel")
        self.ai_model_id_label.setProperty("role", "mutedInline")
        self.ai_model_id_label.setMinimumWidth(0)
        status_row_layout.addWidget(self.ai_model_id_label)

        self.ai_model_switch_btn = QPushButton()
        self.ai_model_switch_btn.setIcon(get_icon(Icons.CHEVRON_DOWN))
        self.ai_model_switch_btn.setIconSize(QSize(14, 14))
        self.ai_model_switch_btn.setObjectName("aiModelSwitchBtn")
        self.ai_model_switch_btn.setFixedSize(18, 18)
        self.ai_model_switch_btn.setProperty("variant", "ghost")
        self.ai_model_switch_btn.setToolTip(tr("settings.aiModel"))
        self.ai_model_switch_btn.clicked.connect(self._open_model_switch_menu)
        status_row_layout.addWidget(self.ai_model_switch_btn)

        self._activity_indicator = ActivityIndicator(parent=status_row, compact=True)
        status_row_layout.addWidget(self._activity_indicator, 1)

        action_bar.addWidget(status_row, 1)

        ai_new_chat_btn = QPushButton(tr("ai.newChat"))
        ai_new_chat_btn.setIcon(get_icon(Icons.X))
        ai_new_chat_btn.setIconSize(QSize(16, 16))
        ai_new_chat_btn.setMinimumWidth(60)
        ai_new_chat_btn.setProperty("variant", "ghost")
        ai_new_chat_btn.clicked.connect(self.on_new_chat)
        action_bar.addWidget(ai_new_chat_btn)

        self.ai_run_btn = QPushButton(tr("ai.runAgent"))
        self.ai_run_btn.setObjectName("aiRunActionBtn")
        self.ai_run_btn.setIcon(get_icon(Icons.PLAY, color="#ffffff"))  # White icon for primary variant
        self.ai_run_btn.setIconSize(QSize(16, 16))
        self.ai_run_btn.setProperty("variant", "primary")
        self.ai_run_btn.setProperty("migrationAttention", False)
        self.ai_run_btn.setMinimumWidth(60)
        self.ai_run_btn.clicked.connect(self._on_run_stop_toggle)
        action_bar.addWidget(self.ai_run_btn)

        ic_layout.addLayout(action_bar)
        dock_layout.addWidget(input_container)

        layout.addWidget(dock)
        self.ai_provider.textChanged.connect(self._refresh_model_badge)
        self.ai_model.textChanged.connect(self._refresh_model_badge)
        self._refresh_model_badge()
        self._refresh_new_message_button()
        self._reposition_new_message_button()
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is not None:
            scroll_bar.valueChanged.connect(self._on_chat_scroll_value_changed)
            scroll_bar.rangeChanged.connect(self._on_chat_scroll_range_changed)

    def _iter_model_switch_options(self):
        options = []
        seen = set()

        current_provider = normalize_ai_provider(self.ai_provider.text().strip())
        current_model = self.ai_model.text().strip()
        if current_model:
            key = (current_provider, current_model)
            seen.add(key)
            options.append({
                "provider": current_provider,
                "model": current_model,
            })

        for provider_id, provider_cfg in AI_PROVIDER_DEFAULTS.items():
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
        provider_id = normalize_ai_provider(self.ai_provider.text().strip())
        self.ai_model_id_label.setText(model_id)
        self.ai_model_id_label.setToolTip(f"{provider_id}:{model_id}")
        self.ai_model_switch_btn.setEnabled((not self.ai_run_inflight) and bool(self._iter_model_switch_options()))

    def _open_model_switch_menu(self):
        if self.ai_run_inflight:
            return
        options = self._iter_model_switch_options()
        if not options:
            return

        current_provider = normalize_ai_provider(self.ai_provider.text().strip())
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

        # Prefer showing the model list above the trigger button.
        popup_pos = self.ai_model_switch_btn.mapToGlobal(self.ai_model_switch_btn.rect().topLeft())
        try:
            menu_height = int(menu.sizeHint().height())
        except Exception:
            menu_height = 0
        if menu_height > 0:
            popup_pos.setY(popup_pos.y() - menu_height)
        screen = self.ai_model_switch_btn.screen()
        if screen is not None and popup_pos.y() < screen.availableGeometry().top():
            popup_pos = self.ai_model_switch_btn.mapToGlobal(self.ai_model_switch_btn.rect().bottomLeft())
        chosen = menu.exec(popup_pos)
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
            event.type() == QEvent.KeyPress
            and obj is self.ai_prompt
            and event.key() in (Qt.Key_Up, Qt.Key_Down)
            and not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier))
            and self._prompt_history
        ):
            if self._browse_prompt_history(event.key() == Qt.Key_Up):
                return True
        if (
            event.type() == QEvent.MouseButtonRelease
            and obj is self.ai_chat.viewport()
        ):
            if self._handle_chat_anchor_click(event):
                return True
        if event.type() == QEvent.Resize and obj is self.ai_chat.viewport():
            self._reposition_new_message_button()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_new_message_button()

    def _handle_chat_anchor_click(self, event):
        if not isinstance(event, QMouseEvent):
            return False
        anchor = self.ai_chat.anchorAt(event.position().toPoint())
        if not anchor:
            return False
        if anchor.startswith("toggle_details_"):
            self._toggle_collapsible_block(anchor)
        else:
            return False
        return True

    def refresh_placeholder(self):
        """Refresh placeholder with a random example (called once on init)."""
        if self.ai_prompt.toPlainText().strip():
            return
        from app_gui.i18n import get_language
        lang = get_language()
        pool = PLACEHOLDER_EXAMPLES_ZH if lang.startswith("zh") else PLACEHOLDER_EXAMPLES_EN
        self.ai_prompt.setPlaceholderText(random.choice(pool))

    def _browse_prompt_history(self, going_up):
        """Recall previous/next user prompt with Up/Down keys.

        Returns True if the event was consumed."""
        # Only intercept when the input is single-line (no newlines) or empty.
        current_text = self.ai_prompt.toPlainText()
        if "\n" in current_text.strip():
            return False

        history = self._prompt_history
        if not history:
            return False

        if self._prompt_history_index == -1:
            # First press — stash current input
            self._prompt_history_stash = current_text

        if going_up:
            if self._prompt_history_index == -1:
                new_index = len(history) - 1
            elif self._prompt_history_index > 0:
                new_index = self._prompt_history_index - 1
            else:
                return True  # already at oldest
        else:
            if self._prompt_history_index == -1:
                return False  # not browsing, let default behavior
            new_index = self._prompt_history_index + 1
            if new_index >= len(history):
                # Restore stashed input
                self._prompt_history_index = -1
                self.ai_prompt.setPlainText(self._prompt_history_stash)
                cursor = self.ai_prompt.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.ai_prompt.setTextCursor(cursor)
                return True

        self._prompt_history_index = new_index
        self.ai_prompt.setPlainText(history[new_index])
        cursor = self.ai_prompt.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.ai_prompt.setTextCursor(cursor)
        return True

    def prepare_import_migration(self, prompt_text, *, focus=True):
        text = str(prompt_text or "").strip()
        if not text:
            return
        clear_fn = getattr(self._plan_store, "clear", None)
        if callable(clear_fn):
            with suppress(Exception):
                clear_fn()
        self.ai_prompt.setPlainText(text)
        if focus:
            self.ai_prompt.setFocus(Qt.OtherFocusReason)
            cursor = self.ai_prompt.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.ai_prompt.setTextCursor(cursor)

    def apply_runtime_settings(
        self,
        *,
        provider,
        model,
        max_steps,
        thinking_enabled,
        custom_prompt="",
    ):
        normalized_provider = normalize_ai_provider(provider)
        provider_cfg = AI_PROVIDER_DEFAULTS[normalized_provider]
        self.ai_provider.setText(normalized_provider)
        self.ai_model.setText(str(model or "").strip() or provider_cfg["model"])
        try:
            steps_value = int(max_steps)
        except Exception:
            steps_value = self.ai_steps.value() or 1
        steps_value = max(1, min(MAX_AGENT_STEPS, steps_value))
        self.ai_steps.setValue(steps_value)
        self.ai_thinking_enabled.setChecked(bool(thinking_enabled))
        self.ai_custom_prompt = str(custom_prompt or "")

    def runtime_settings_snapshot(self):
        provider = normalize_ai_provider(self.ai_provider.text().strip())
        provider_cfg = AI_PROVIDER_DEFAULTS[provider]
        return {
            "provider": provider,
            "model": self.ai_model.text().strip() or provider_cfg["model"],
            "max_steps": self.ai_steps.value(),
            "thinking_enabled": self.ai_thinking_enabled.isChecked(),
            "custom_prompt": self.ai_custom_prompt,
        }

    def has_running_task(self):
        return bool(self.ai_run_inflight)

    def _set_migration_mode_banner(self, visible):
        banner = getattr(self, "_migration_mode_banner", None)
        if banner is None:
            return
        banner.setVisible(bool(visible))

    def _set_run_button_attention(self, enabled):
        run_btn = getattr(self, "ai_run_btn", None)
        if run_btn is None:
            return
        target = bool(enabled)
        if bool(run_btn.property("migrationAttention")) == target:
            return
        run_btn.setProperty("migrationAttention", target)
        run_btn.style().unpolish(run_btn)
        run_btn.style().polish(run_btn)

    def _clear_run_button_attention(self):
        timer = getattr(self, "_run_btn_attention_timer", None)
        if timer is not None:
            timer.stop()
        clear_timer = getattr(self, "_run_btn_attention_clear_timer", None)
        if clear_timer is not None:
            clear_timer.stop()
        self._run_btn_attention_toggles_remaining = 0
        self._set_run_button_attention(False)

    def _tick_run_button_attention(self):
        run_btn = getattr(self, "ai_run_btn", None)
        timer = getattr(self, "_run_btn_attention_timer", None)
        if run_btn is None or timer is None:
            return

        remaining = int(getattr(self, "_run_btn_attention_toggles_remaining", 0) or 0)
        if remaining <= 0:
            self._clear_run_button_attention()
            return

        self._set_run_button_attention(not bool(run_btn.property("migrationAttention")))
        self._run_btn_attention_toggles_remaining = remaining - 1
        if self._run_btn_attention_toggles_remaining <= 0:
            self._clear_run_button_attention()

    def _flash_run_button_attention(self, duration_ms=1200, flashes=2):
        run_btn = getattr(self, "ai_run_btn", None)
        if run_btn is None:
            return

        self._set_run_button_attention(True)
        total_flashes = max(1, int(flashes or 0))
        total_toggles = max(1, total_flashes * 2 - 1)
        interval_ms = max(1, int(duration_ms or 0) // total_toggles)
        self._run_btn_attention_toggles_remaining = total_toggles

        timer = getattr(self, "_run_btn_attention_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(False)
            timer.timeout.connect(self._tick_run_button_attention)
            self._run_btn_attention_timer = timer
        timer.start(interval_ms)

        # Failsafe: always clear attention state by the requested duration.
        clear_timer = getattr(self, "_run_btn_attention_clear_timer", None)
        if clear_timer is None:
            clear_timer = QTimer(self)
            clear_timer.setSingleShot(True)
            clear_timer.timeout.connect(self._clear_run_button_attention)
            self._run_btn_attention_clear_timer = clear_timer
        clear_timer.start(max(interval_ms, int(duration_ms or 0)))

    def set_migration_mode_enabled(self, enabled):
        target = bool(enabled)
        if self._migration_mode_enabled == target:
            return
        self._migration_mode_enabled = target
        self._set_migration_mode_banner(target)
        if target:
            self._flash_run_button_attention(duration_ms=1200, flashes=2)
            clear_fn = getattr(self._plan_store, "clear", None)
            if callable(clear_fn):
                with suppress(Exception):
                    clear_fn()
            self.migration_mode_changed.emit(True)
            self.status_message.emit(tr("ai.migrationModeEnteredStatus"), 4000)
            return
        self.migration_mode_changed.emit(False)
        self.status_message.emit(tr("ai.migrationModeExitedStatus"), 4000)

    def _reset_stream_thought_state(self):
        self.ai_stream_has_thought = False
        self.ai_stream_thought_buffer = ""

    def on_new_chat(self):
        from PySide6.QtWidgets import QMessageBox

        if self.ai_history or self.ai_chat.toPlainText().strip():
            reply = QMessageBox.question(
                self,
                tr("ai.newChat"),
                tr("ai.newChatConfirm"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.ai_chat.clear()
        self.ai_history = []
        self.ai_summary_state = None
        self.ai_operation_events = []
        self.ai_collapsible_blocks = []
        self.ai_active_trace_id = None
        self._history_snapshot_from_stream_end = False
        self.ai_streaming_active = False
        self.ai_stream_buffer = ""
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0
        self.ai_auto_follow_enabled = True
        self.ai_unseen_message_count = 0
        self._reset_stream_thought_state()
        self._refresh_new_message_button()
        self.status_message.emit(tr("ai.newChatDone"), 2000)

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
        self._ensure_chat_block_context()
        is_dark = _is_dark_mode(self)
        self._move_chat_cursor_to_end()
        html = self._build_header_html(role, compact=compact, is_dark=is_dark)
        self.ai_chat.append(html)

    def _chat_scrollbar(self):
        if self.ai_chat is None:
            return None
        getter = getattr(self.ai_chat, "verticalScrollBar", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _is_near_bottom(self, threshold_px=None):
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is None:
            return True
        threshold = self.ai_scroll_bottom_threshold_px if threshold_px is None else threshold_px
        try:
            delta = int(scroll_bar.maximum()) - int(scroll_bar.value())
        except Exception:
            return True
        return delta <= int(max(0, threshold))

    def _capture_view_anchor(self):
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is None:
            return None
        try:
            return {
                "value": int(scroll_bar.value()),
                "maximum": int(scroll_bar.maximum()),
                "near_bottom": self._is_near_bottom(),
            }
        except Exception:
            return None

    def _set_scroll_value(self, value):
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is None:
            return
        self.ai_programmatic_scroll_lock = True
        try:
            scroll_bar.setValue(int(value))
        except Exception:
            pass
        finally:
            self.ai_programmatic_scroll_lock = False

    def _scroll_chat_to_bottom(self):
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is None:
            return
        try:
            self._set_scroll_value(scroll_bar.maximum())
        except Exception:
            return

    def _update_follow_state_from_scroll(self):
        self.ai_auto_follow_enabled = self._is_near_bottom()
        if self.ai_auto_follow_enabled:
            self.ai_unseen_message_count = 0

    def _refresh_new_message_button(self):
        btn = getattr(self, "ai_new_msg_btn", None)
        if btn is None:
            return
        count = max(0, int(self.ai_unseen_message_count or 0))
        visible = bool(count > 0 and not self.ai_auto_follow_enabled)
        if count > 0:
            label = tr("ai.newMessages").format(count=count)
            jump = tr("ai.jumpToLatest")
            btn.setText(f"{label} · {jump}")
            btn.adjustSize()
            self._reposition_new_message_button()
        btn.setVisible(visible)

    def _reposition_new_message_button(self):
        btn = getattr(self, "ai_new_msg_btn", None)
        if btn is None:
            return
        chat = getattr(self, "ai_chat", None)
        if chat is None:
            return
        viewport_getter = getattr(chat, "viewport", None)
        if not callable(viewport_getter):
            return
        viewport = viewport_getter()
        if viewport is None:
            return
        try:
            btn.adjustSize()
            width = max(int(btn.width()), int(btn.sizeHint().width()))
            height = max(int(btn.height()), int(btn.sizeHint().height()))
            margin = 10
            x = max(margin, int(viewport.width()) - width - margin)
            y = max(margin, int(viewport.height()) - height - margin)
            btn.move(x, y)
            btn.raise_()
        except Exception:
            return

    def _mark_unseen_message(self):
        self.ai_unseen_message_count = int(self.ai_unseen_message_count or 0) + 1
        self._refresh_new_message_button()

    def _jump_to_chat_bottom(self):
        self.ai_auto_follow_enabled = True
        self.ai_unseen_message_count = 0
        self._scroll_chat_to_bottom()
        self._refresh_new_message_button()

    def _on_chat_scroll_value_changed(self, _value):
        if self.ai_programmatic_scroll_lock or self.ai_chat_write_in_progress:
            return
        self._update_follow_state_from_scroll()
        self._refresh_new_message_button()

    def _on_chat_scroll_range_changed(self, _minimum, _maximum):
        if self.ai_chat_write_in_progress:
            return
        self._refresh_new_message_button()

    def _restore_view_anchor(self, anchor, *, marks_new=False, force_follow=False):
        scroll_bar = self._chat_scrollbar()
        if scroll_bar is None:
            return
        should_follow = bool(force_follow)
        if not should_follow:
            if isinstance(anchor, dict):
                should_follow = bool(anchor.get("near_bottom"))
            else:
                should_follow = self.ai_auto_follow_enabled and self._is_near_bottom()

        if should_follow:
            self.ai_auto_follow_enabled = True
            self.ai_unseen_message_count = 0
            self._scroll_chat_to_bottom()
        else:
            if isinstance(anchor, dict):
                self._set_scroll_value(anchor.get("value", 0))
            self._update_follow_state_from_scroll()
            if marks_new and not self.ai_auto_follow_enabled:
                self._mark_unseen_message()
        self._refresh_new_message_button()

    def _run_chat_write(self, writer, *, marks_new=False, force_follow=False):
        anchor = self._capture_view_anchor()
        previous_lock = bool(self.ai_chat_write_in_progress)
        self.ai_chat_write_in_progress = True
        try:
            return writer()
        finally:
            self.ai_chat_write_in_progress = previous_lock
            self._restore_view_anchor(anchor, marks_new=marks_new, force_follow=force_follow)

    def _move_chat_cursor_to_end(self):
        if not hasattr(self.ai_chat, "textCursor") or not hasattr(self.ai_chat, "setTextCursor"):
            return
        cursor = self.ai_chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.ai_chat.setTextCursor(cursor)

    def _document_end_position(self):
        if hasattr(self.ai_chat, "document"):
            try:
                return max(0, int(self.ai_chat.document().characterCount()) - 1)
            except Exception:
                pass
        if hasattr(self.ai_chat, "textCursor"):
            try:
                return int(self.ai_chat.textCursor().position())
            except Exception:
                return 0
        return 0

    def _ensure_chat_block_context(self):
        """Break out of list blocks so the next message starts as a plain paragraph."""
        if not hasattr(self.ai_chat, "textCursor") or not hasattr(self.ai_chat, "setTextCursor"):
            return
        try:
            cursor = self.ai_chat.textCursor()
            cursor.movePosition(QTextCursor.End)

            in_list = False
            if hasattr(cursor, "currentList"):
                in_list = cursor.currentList() is not None
            if not in_list:
                in_list = cursor.blockFormat().objectIndex() != -1
            if not in_list:
                self.ai_chat.setTextCursor(cursor)
                return

            block_format = QTextBlockFormat()
            block_format.setObjectIndex(-1)
            cursor.insertBlock(block_format)
            self.ai_chat.setTextCursor(cursor)
        except Exception:
            return

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
        def _writer():
            self._ensure_chat_block_context()
            _is_dark = is_dark if is_dark is not None else _is_dark_mode(self)
            header_html = self._build_header_html(role, is_dark=_is_dark)
            body_html = _md_to_html(str(text or ""), _is_dark)
            self._move_chat_cursor_to_end()
            self.ai_chat.append(header_html)
            self.ai_chat.append(body_html)

        self._run_chat_write(_writer, marks_new=True)

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
            def _writer():
                self._ensure_chat_block_context()
                header_html = self._build_header_html(role, compact=True, is_dark=is_dark)
                self._move_chat_cursor_to_end()
                # Compact: single line, inline formatting only (no block elements)
                body = str(text or "")
                body = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', body)
                body = re.sub(r'`([^`]+)`', r'\1', body)
                self.ai_chat.append(header_html + body)

            self._run_chat_write(_writer, marks_new=True)
            return

        self._append_chat_markdown_block(role, text, is_dark=is_dark)

    def _begin_stream_chat(self, role="Agent"):
        if self.ai_streaming_active:
            return
        self.ai_streaming_active = True
        self.ai_stream_buffer = ""
        self.ai_stream_thought_buffer = ""
        self.ai_stream_has_thought = False
        self.ai_stream_start_pos = None
        self.ai_last_stream_block = None
        self.ai_stream_last_render_ts = 0.0
        self.ai_stream_last_render_len = 0

        def _writer():
            self._append_chat_header(role)
            self.ai_chat.append("")
            self._move_chat_cursor_to_end()
            if hasattr(self.ai_chat, "textCursor"):
                self.ai_stream_start_pos = self.ai_chat.textCursor().position()

        self._run_chat_write(_writer, marks_new=True)

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

        def _writer():
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

            self.ai_chat.append("")

        self._run_chat_write(_writer, marks_new=False)
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

        success = {"ok": False}

        def _writer():
            try:
                cursor = self.ai_chat.textCursor()
                cursor.setPosition(int(start))
                cursor.setPosition(int(end), QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                self._insert_markdown_with_cursor(cursor, str(html_text or ""))
                block["end"] = cursor.position()
                success["ok"] = True
            except Exception:
                success["ok"] = False

        self._run_chat_write(_writer, marks_new=False)
        return bool(success["ok"])

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

        end_pos = self._document_end_position()
        block = {
            "start": self.ai_stream_start_pos,
            "end": end_pos,
            "text": self.ai_stream_buffer,
        }

        is_dark = _is_dark_mode(self)
        answer_html = _md_to_html(str(self.ai_stream_buffer or ""), is_dark)

        combined_html = ""
        muted_color = _get_role_color("muted", is_dark)
        if self.ai_stream_has_thought and self.ai_stream_thought_buffer:
            thought_html = _md_to_html(str(self.ai_stream_thought_buffer or ""), is_dark)
            combined_html += f'<div style="color: {muted_color};">{thought_html}</div>'
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

        new_end = block.get("end", end_pos)
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

        success = {"ok": False}

        def _writer():
            try:
                cursor = self.ai_chat.textCursor()
                cursor.setPosition(int(start))
                cursor.setPosition(int(end), QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                is_dark = _is_dark_mode(self)
                highlighted = _md_to_html(str(markdown_text or ""), is_dark)
                self._insert_markdown_with_cursor(cursor, highlighted)
                block["end"] = cursor.position()
                success["ok"] = True
            except Exception:
                success["ok"] = False

        self._run_chat_write(_writer, marks_new=False)
        return bool(success["ok"])

    _on_run_stop_toggle = _ai_runtime._on_run_stop_toggle
    on_run_ai_agent = _ai_runtime.on_run_ai_agent
    start_worker = _ai_runtime.start_worker
    _show_nonblocking_ai_dialog = _ai_runtime._show_nonblocking_ai_dialog
    _set_waiting_for_user_reply = _ai_runtime._set_waiting_for_user_reply
    _begin_pending_ai_wait = _ai_runtime._begin_pending_ai_wait
    _pending_ai_wait_matches = _ai_runtime._pending_ai_wait_matches
    _finalize_pending_ai_wait = _ai_runtime._finalize_pending_ai_wait
    _dismiss_pending_ai_wait = _ai_runtime._dismiss_pending_ai_wait
    _handle_pending_ai_dialog_closed = _ai_runtime._handle_pending_ai_dialog_closed
    _handle_question_event = _ai_runtime._handle_question_event
    _handle_manage_boxes_confirm = _ai_runtime._handle_manage_boxes_confirm
    _handle_max_steps_ask = _ai_runtime._handle_max_steps_ask
    _show_question_dialog = _ai_runtime._show_question_dialog
    on_stop_ai_agent = _ai_runtime.on_stop_ai_agent
    set_busy = _ai_runtime.set_busy
    on_progress = _ai_runtime.on_progress
    _extract_progress_observation = _ai_runtime._extract_progress_observation
    _handle_progress_context_checkpoint = _ai_runtime._handle_progress_context_checkpoint
    _handle_progress_tool_end = _ai_runtime._handle_progress_tool_end
    _handle_progress_tool_start = _ai_runtime._handle_progress_tool_start
    _handle_progress_chunk = _ai_runtime._handle_progress_chunk
    _handle_progress_step_end = _ai_runtime._handle_progress_step_end
    _handle_progress_error = staticmethod(_ai_runtime._handle_progress_error)
    _handle_progress_stream_end = _ai_runtime._handle_progress_stream_end
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
        if len(self.ai_history) > AI_HISTORY_LIMIT:
            self.ai_history = self.ai_history[-AI_HISTORY_LIMIT:]

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
                data={"raw_event": raw_event},
            )
            if raw_event.get("timestamp"):
                notice["timestamp"] = raw_event.get("timestamp")

        self.ai_operation_events.append(notice)
        if len(self.ai_operation_events) > AI_OPERATION_EVENT_POOL_LIMIT:
            self.ai_operation_events = self.ai_operation_events[-AI_OPERATION_EVENT_POOL_LIMIT:]

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

        def _writer():
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

        self._run_chat_write(_writer, marks_new=False)

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

        def _writer():
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
            except Exception:
                pass

        self._run_chat_write(_writer, marks_new=False)

    def _load_audit(self, trace_id, run_result):
        pass
