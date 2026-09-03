"""Chat view collaborators extracted from :class:`AIPanel`.

Each class here owns one cohesive "chat view helper" responsibility that used
to live as private methods on ``AIPanel``:

- :class:`ChatViewAnchorController` — scroll position / view anchor / auto
  follow state and the floating "new messages" button.
- :class:`StreamThoughtTicker` — the streaming "thinking" elapsed timer.
- :class:`ChatDocumentEditor` — low-level QTextDocument cursor and HTML
  insertion helpers for the chat area.
- :class:`CollapsibleBlocksController` — collapsible detail blocks rendered
  inside the chat.
- :class:`RunButtonAttentionFlasher` — the run button "attention" flash used
  when migration mode is entered.

The panel keeps ownership of all observable state (``ai_*`` attributes and
widgets) so external contracts (tests, ``ai_panel_runtime``) are unchanged;
the collaborators operate on that state through the ``panel`` reference and
are held by composition on the panel instance.
"""

import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette, QTextBlockFormat, QTextCharFormat, QTextCursor

from app_gui.i18n import tr
from app_gui.ui.theme import (
    FONT_SIZE_SM,
    FONT_SIZE_XS,
    MONO_FONT_CSS_FAMILY,
    resolve_theme_token,
)


def is_dark_mode(widget):
    try:
        palette = widget.palette()
        bg_color = palette.color(QPalette.Window)
        return bg_color.lightness() < 128
    except Exception:
        return True


class ChatViewAnchorController:
    """Scroll/view-anchor management for the chat area.

    Covers auto-follow detection, anchor capture/restore around document
    writes, and the floating "new messages" button.
    """

    def __init__(self, panel):
        self._panel = panel

    def scrollbar(self):
        chat = getattr(self._panel, "ai_chat", None)
        if chat is None:
            return None
        getter = getattr(chat, "verticalScrollBar", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def is_near_bottom(self, threshold_px=None):
        panel = self._panel
        scroll_bar = self.scrollbar()
        if scroll_bar is None:
            return True
        threshold = panel.ai_scroll_bottom_threshold_px if threshold_px is None else threshold_px
        try:
            delta = int(scroll_bar.maximum()) - int(scroll_bar.value())
        except Exception:
            return True
        return delta <= int(max(0, threshold))

    def capture_anchor(self):
        scroll_bar = self.scrollbar()
        if scroll_bar is None:
            return None
        try:
            return {
                "value": int(scroll_bar.value()),
                "maximum": int(scroll_bar.maximum()),
                "near_bottom": self.is_near_bottom(),
            }
        except Exception:
            return None

    def set_scroll_value(self, value):
        panel = self._panel
        scroll_bar = self.scrollbar()
        if scroll_bar is None:
            return
        panel.ai_programmatic_scroll_lock = True
        try:
            scroll_bar.setValue(int(value))
        except Exception:
            pass
        finally:
            panel.ai_programmatic_scroll_lock = False

    def scroll_to_bottom(self):
        scroll_bar = self.scrollbar()
        if scroll_bar is None:
            return
        try:
            self.set_scroll_value(scroll_bar.maximum())
        except Exception:
            return

    def update_follow_state_from_scroll(self):
        panel = self._panel
        panel.ai_auto_follow_enabled = self.is_near_bottom()
        if panel.ai_auto_follow_enabled:
            panel.ai_unseen_message_count = 0

    def refresh_new_message_button(self):
        panel = self._panel
        btn = getattr(panel, "ai_new_msg_btn", None)
        if btn is None:
            return
        count = max(0, int(panel.ai_unseen_message_count or 0))
        visible = bool(count > 0 and not panel.ai_auto_follow_enabled)
        if count > 0:
            label = tr("ai.newMessages").format(count=count)
            jump = tr("ai.jumpToLatest")
            btn.setText(f"{label} · {jump}")
            btn.adjustSize()
            self.reposition_new_message_button()
        btn.setVisible(visible)

    def reposition_new_message_button(self):
        panel = self._panel
        btn = getattr(panel, "ai_new_msg_btn", None)
        if btn is None:
            return
        chat = getattr(panel, "ai_chat", None)
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

    def mark_unseen_message(self):
        panel = self._panel
        panel.ai_unseen_message_count = int(panel.ai_unseen_message_count or 0) + 1
        self.refresh_new_message_button()

    def jump_to_bottom(self):
        panel = self._panel
        panel.ai_auto_follow_enabled = True
        panel.ai_unseen_message_count = 0
        self.scroll_to_bottom()
        self.refresh_new_message_button()

    def on_scroll_value_changed(self, _value):
        panel = self._panel
        if panel.ai_programmatic_scroll_lock or panel.ai_chat_write_in_progress:
            return
        self.update_follow_state_from_scroll()
        self.refresh_new_message_button()

    def on_scroll_range_changed(self, _minimum, _maximum):
        if self._panel.ai_chat_write_in_progress:
            return
        self.refresh_new_message_button()

    def restore_anchor(self, anchor, *, marks_new=False, force_follow=False):
        panel = self._panel
        scroll_bar = self.scrollbar()
        if scroll_bar is None:
            return
        should_follow = bool(force_follow)
        if not should_follow:
            if isinstance(anchor, dict):
                should_follow = bool(anchor.get("near_bottom"))
            else:
                should_follow = panel.ai_auto_follow_enabled and self.is_near_bottom()

        if should_follow:
            panel.ai_auto_follow_enabled = True
            panel.ai_unseen_message_count = 0
            self.scroll_to_bottom()
        else:
            if isinstance(anchor, dict):
                self.set_scroll_value(anchor.get("value", 0))
            self.update_follow_state_from_scroll()
            if marks_new and not panel.ai_auto_follow_enabled:
                self.mark_unseen_message()
        self.refresh_new_message_button()

    def run_chat_write(self, writer, *, marks_new=False, force_follow=False):
        panel = self._panel
        anchor = self.capture_anchor()
        previous_lock = bool(panel.ai_chat_write_in_progress)
        panel.ai_chat_write_in_progress = True
        try:
            return writer()
        finally:
            panel.ai_chat_write_in_progress = previous_lock
            self.restore_anchor(anchor, marks_new=marks_new, force_follow=force_follow)


class StreamThoughtTicker:
    """Elapsed-time ticker for the streaming "thinking" panel.

    Thought stream state (buffers/flags) stays on the panel; this class owns
    only the QTimer and the start/pause/reset lifecycle.
    """

    def __init__(self, panel):
        self._panel = panel
        self._timer = None

    def reset_state(self):
        panel = self._panel
        self.stop_timer()
        panel.ai_stream_has_thought = False
        panel.ai_stream_thought_buffer = ""
        panel.ai_stream_thought_active = False
        panel.ai_stream_thought_start_ts = None
        panel.ai_stream_thought_elapsed_sec = 0.0
        panel.ai_stream_waiting = False
        panel.ai_stream_thought_frozen = False

    def elapsed_text(self):
        panel = self._panel
        elapsed = float(panel.ai_stream_thought_elapsed_sec or 0.0)
        if panel.ai_stream_thought_active and panel.ai_stream_thought_start_ts is not None:
            elapsed += max(0.0, time.monotonic() - float(panel.ai_stream_thought_start_ts or 0.0))
        return f"{elapsed:.1f}s"

    def _ensure_timer(self):
        if self._timer is None:
            timer = QTimer(self._panel)
            timer.setSingleShot(False)
            timer.timeout.connect(self._on_tick)
            self._timer = timer
        return self._timer

    def start(self):
        panel = self._panel
        if panel.ai_stream_thought_active:
            return
        panel.ai_stream_thought_active = True
        panel.ai_stream_thought_start_ts = time.monotonic()
        self._ensure_timer().start(100)

    def pause(self):
        panel = self._panel
        if panel.ai_stream_thought_active and panel.ai_stream_thought_start_ts is not None:
            panel.ai_stream_thought_elapsed_sec += max(
                0.0, time.monotonic() - float(panel.ai_stream_thought_start_ts or 0.0)
            )
        panel.ai_stream_thought_active = False
        panel.ai_stream_thought_start_ts = None
        self.stop_timer()

    def stop_timer(self):
        if self._timer is not None:
            self._timer.stop()

    def _on_tick(self):
        panel = self._panel
        if not panel.ai_streaming_active or not panel.ai_stream_has_thought:
            self.stop_timer()
            return
        panel._rerender_stream_with_thought_markdown_in_place(force=True)


class ChatDocumentEditor:
    """Low-level cursor/format/HTML helpers for the chat QTextDocument."""

    def __init__(self, panel):
        self._panel = panel

    @property
    def _chat(self):
        return self._panel.ai_chat

    @staticmethod
    def clean_block_format():
        block_format = QTextBlockFormat()
        block_format.setObjectIndex(-1)
        return block_format

    @staticmethod
    def clean_char_format():
        return QTextCharFormat()

    def reset_cursor_format(self, cursor=None, *, reset_block=False):
        chat = self._chat
        if cursor is None and hasattr(chat, "textCursor"):
            cursor = chat.textCursor()
        if cursor is None:
            return cursor
        try:
            char_format = self.clean_char_format()
            cursor.setCharFormat(char_format)
            if reset_block:
                cursor.setBlockFormat(self.clean_block_format())
            if hasattr(chat, "setCurrentCharFormat"):
                chat.setCurrentCharFormat(char_format)
        except Exception:
            pass
        return cursor

    def move_cursor_to_end(self):
        chat = self._chat
        if not hasattr(chat, "textCursor") or not hasattr(chat, "setTextCursor"):
            return
        cursor = chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.reset_cursor_format(cursor)
        chat.setTextCursor(cursor)

    def append_html(self, html):
        chat = self._chat
        self.move_cursor_to_end()
        if hasattr(chat, "textCursor") and hasattr(chat, "setTextCursor"):
            cursor = chat.textCursor()
            self.reset_cursor_format(cursor, reset_block=True)
            cursor.insertHtml(str(html or ""))
            cursor.insertBlock(self.clean_block_format(), self.clean_char_format())
            self.reset_cursor_format(cursor, reset_block=True)
            chat.setTextCursor(cursor)
            return
        chat.append(str(html or ""))

    def end_position(self):
        chat = self._chat
        if hasattr(chat, "document"):
            try:
                return max(0, int(chat.document().characterCount()) - 1)
            except Exception:
                pass
        if hasattr(chat, "textCursor"):
            try:
                return int(chat.textCursor().position())
            except Exception:
                return 0
        return 0

    def ensure_block_context(self):
        """Break out of list blocks so the next message starts as a plain paragraph."""
        chat = self._chat
        if not hasattr(chat, "textCursor") or not hasattr(chat, "setTextCursor"):
            return
        try:
            cursor = chat.textCursor()
            cursor.movePosition(QTextCursor.End)

            in_list = False
            if hasattr(cursor, "currentList"):
                in_list = cursor.currentList() is not None
            if not in_list:
                in_list = cursor.blockFormat().objectIndex() != -1
            if not in_list:
                chat.setTextCursor(cursor)
                return

            block_format = QTextBlockFormat()
            block_format.setObjectIndex(-1)
            cursor.insertBlock(block_format)
            chat.setTextCursor(cursor)
        except Exception:
            return

    def insert_html_at_cursor(self, cursor, html_text):
        """Insert pre-rendered HTML at cursor position (used by streaming rerender)."""
        chat = self._chat
        html_text = str(html_text or "")
        if cursor is not None and hasattr(chat, "setTextCursor"):
            chat.setTextCursor(cursor)

        if hasattr(chat, "textCursor"):
            cursor = chat.textCursor()
            self.reset_cursor_format(cursor, reset_block=True)
            cursor.insertHtml(html_text)
            self.reset_cursor_format(cursor, reset_block=True)
            if hasattr(chat, "setTextCursor"):
                chat.setTextCursor(cursor)
            return

        chat.insertPlainText(html_text)

    def remove_after(self, start_pos):
        chat = self._chat
        if start_pos is None or not hasattr(chat, "textCursor"):
            return False
        try:
            cursor = chat.textCursor()
            cursor.setPosition(int(start_pos))
            cursor.setPosition(self.end_position(), QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            chat.setTextCursor(cursor)
            return True
        except Exception:
            return False

    @staticmethod
    def shift_block_ranges(blocks, *, after_end, delta, exclude=None):
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


class CollapsibleBlocksController:
    """Collapsible detail blocks appended to the chat document.

    The block registry (``panel.ai_collapsible_blocks``) stays on the panel;
    this class owns rendering and toggle behaviour.
    """

    def __init__(self, panel):
        self._panel = panel

    def append_chat_with_collapsible(self, role, summary, details_json, collapsed_preview_lines=3):
        panel = self._panel
        is_dark = is_dark_mode(panel)
        panel._append_chat_markdown_block(role, summary, is_dark=is_dark)

        # Format details as human-readable text instead of raw JSON
        details_text = panel._format_event_details(details_json)
        block_id = f"toggle_details_{len(panel.ai_collapsible_blocks)}"
        collapsed_html = self.render_details(
            block_id,
            details_text,
            collapsed=True,
            is_dark=is_dark,
            preview_lines=collapsed_preview_lines,
        )

        def _writer():
            panel._chat_doc.move_cursor_to_end()
            if not hasattr(panel.ai_chat, "textCursor"):
                panel.ai_chat.append(collapsed_html)
                panel.ai_chat.append("")
                return
            cursor = panel.ai_chat.textCursor()
            start = cursor.position()
            panel._chat_doc.reset_cursor_format(cursor, reset_block=True)
            cursor.insertHtml(collapsed_html)
            panel._chat_doc.reset_cursor_format(cursor, reset_block=True)
            end = cursor.position()

            panel.ai_collapsible_blocks.append({
                "block_id": block_id,
                "start": start,
                "end": end,
                "content": details_text,
                "collapsed": True,
                "preview_lines": max(0, int(collapsed_preview_lines or 0)),
            })
            panel.ai_chat.append("")

        panel._chat_view.run_chat_write(_writer, marks_new=False)

    def render_details(self, block_id, content, collapsed=True, is_dark=True, preview_lines=3):
        """Render details as a collapsible code block with configurable collapsed preview."""
        mode = "dark" if is_dark else "light"
        bg = resolve_theme_token("chat-panel-bg", mode=mode, fallback="#1f1f1f")
        border = resolve_theme_token("chat-panel-border", mode=mode, fallback="rgba(255,255,255,0.08)")
        text_color = resolve_theme_token("chat-code-text", mode=mode, fallback="#c8c8c8")
        link_color = resolve_theme_token("chat-link", mode=mode, fallback="#38bdf8")

        escaped = self._panel._escape_html_text(content)

        if collapsed:
            lines = content.split('\n')
            preview_limit = max(0, int(preview_lines or 0))
            preview_lines = lines[:preview_limit] if preview_limit > 0 else []
            preview = '\n'.join(preview_lines)
            preview_escaped = self._panel._escape_html_text(preview)
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

    def toggle(self, block_id):
        """Toggle a collapsible details block between collapsed and expanded."""
        panel = self._panel
        block = None
        for b in panel.ai_collapsible_blocks:
            if b["block_id"] == block_id:
                block = b
                break
        if block is None:
            return

        block["collapsed"] = not block["collapsed"]
        is_dark = is_dark_mode(panel)
        new_html = self.render_details(
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
                cursor = panel.ai_chat.textCursor()
                cursor.setPosition(int(start))
                cursor.setPosition(int(end), QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                panel._chat_doc.reset_cursor_format(cursor, reset_block=True)
                cursor.insertHtml(new_html)
                panel._chat_doc.reset_cursor_format(cursor, reset_block=True)
                new_end = cursor.position()
                delta = new_end - end
                block["end"] = new_end
                ChatDocumentEditor.shift_block_ranges(
                    panel.ai_collapsible_blocks,
                    after_end=end,
                    delta=delta,
                    exclude=block,
                )
            except Exception:
                pass

        panel._chat_view.run_chat_write(_writer, marks_new=False)


class RunButtonAttentionFlasher:
    """Run-button "attention" flash used when migration mode is entered."""

    def __init__(self, panel):
        self._panel = panel
        self._timer = None
        self._clear_timer = None
        self._toggles_remaining = 0

    def set_attention(self, enabled):
        run_btn = getattr(self._panel, "ai_run_btn", None)
        if run_btn is None:
            return
        target = bool(enabled)
        if bool(run_btn.property("migrationAttention")) == target:
            return
        run_btn.setProperty("migrationAttention", target)
        run_btn.style().unpolish(run_btn)
        run_btn.style().polish(run_btn)

    def clear(self):
        if self._timer is not None:
            self._timer.stop()
        if self._clear_timer is not None:
            self._clear_timer.stop()
        self._toggles_remaining = 0
        self.set_attention(False)

    def _on_tick(self):
        run_btn = getattr(self._panel, "ai_run_btn", None)
        if run_btn is None or self._timer is None:
            return

        remaining = int(self._toggles_remaining or 0)
        if remaining <= 0:
            self.clear()
            return

        self.set_attention(not bool(run_btn.property("migrationAttention")))
        self._toggles_remaining = remaining - 1
        if self._toggles_remaining <= 0:
            self.clear()

    def flash(self, duration_ms=1200, flashes=2):
        run_btn = getattr(self._panel, "ai_run_btn", None)
        if run_btn is None:
            return

        self.set_attention(True)
        total_flashes = max(1, int(flashes or 0))
        total_toggles = max(1, total_flashes * 2 - 1)
        interval_ms = max(1, int(duration_ms or 0) // total_toggles)
        self._toggles_remaining = total_toggles

        if self._timer is None:
            timer = QTimer(self._panel)
            timer.setSingleShot(False)
            timer.timeout.connect(self._on_tick)
            self._timer = timer
        self._timer.start(interval_ms)

        # Failsafe: always clear attention state by the requested duration.
        if self._clear_timer is None:
            clear_timer = QTimer(self._panel)
            clear_timer.setSingleShot(True)
            clear_timer.timeout.connect(self.clear)
            self._clear_timer = clear_timer
        self._clear_timer.start(max(interval_ms, int(duration_ms or 0)))
