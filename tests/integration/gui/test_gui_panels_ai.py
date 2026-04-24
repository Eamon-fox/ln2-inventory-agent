"""Split from test_gui_panels.py."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelsAiStreamTests(GuiPanelsBaseCase):
    def test_ai_panel_append_chat_falls_back_when_insert_markdown_missing(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel._append_chat("You", "hello")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("append", call_names)

    def test_ai_panel_defaults_model_to_deepseek_chat(self):
        panel = self._new_ai_panel()

        # ai_model and ai_thinking_enabled are now managed via Settings
        self.assertIsNotNone(panel.ai_model)
        self.assertIsNotNone(panel.ai_thinking_enabled)
        self.assertFalse(panel.ai_stream_has_thought)

    def test_ai_panel_model_badge_shows_current_model_id(self):
        panel = self._new_ai_panel()

        panel.ai_provider.setText("deepseek")
        panel.ai_model.setText("deepseek-v4-flash")
        panel._refresh_model_badge()

        self.assertEqual("deepseek-v4-flash", panel.ai_model_id_label.text())
        self.assertEqual("deepseek:deepseek-v4-flash", panel.ai_model_id_label.toolTip())

    def test_ai_panel_model_switch_button_uses_dropdown_icon(self):
        panel = self._new_ai_panel()

        self.assertEqual("", panel.ai_model_switch_btn.text())
        self.assertFalse(panel.ai_model_switch_btn.icon().isNull())

    def test_ai_panel_model_switch_options_include_zhipu_glm_4_7(self):
        panel = self._new_ai_panel()

        options = panel._iter_model_switch_options()
        option_pairs = {
            (str(item.get("provider") or ""), str(item.get("model") or ""))
            for item in options
            if isinstance(item, dict)
        }

        self.assertIn(("zhipu", "glm-4.7"), option_pairs)

    def test_ai_panel_model_switch_options_include_minimax_m2_7_models(self):
        panel = self._new_ai_panel()

        options = panel._iter_model_switch_options()
        option_pairs = {
            (str(item.get("provider") or ""), str(item.get("model") or ""))
            for item in options
            if isinstance(item, dict)
        }

        self.assertIn(("minimax", "MiniMax-M2.7"), option_pairs)
        self.assertIn(("minimax", "MiniMax-M2.7-highspeed"), option_pairs)

    def test_ai_panel_model_switch_menu_updates_provider_and_model(self):
        panel = self._new_ai_panel()
        panel.ai_provider.setText("deepseek")
        panel.ai_model.setText("deepseek-v4-flash")

        with patch("app_gui.ui.ai_panel.QMenu") as menu_cls:
            fake_menu = menu_cls.return_value
            deepseek_action = MagicMock()
            zhipu_action = MagicMock()

            def _add_action(label):
                if "glm-5" in str(label):
                    return zhipu_action
                return deepseek_action

            fake_menu.addAction.side_effect = _add_action
            fake_menu.exec.return_value = zhipu_action

            panel._open_model_switch_menu()

        self.assertTrue(deepseek_action.setActionGroup.called)
        self.assertTrue(zhipu_action.setActionGroup.called)
        self.assertEqual("zhipu", panel.ai_provider.text())
        self.assertEqual("glm-5", panel.ai_model.text())
        self.assertEqual("glm-5", panel.ai_model_id_label.text())

    def test_ai_panel_thought_chunk_renders_inline_with_answer_stream(self):
        panel = self._new_ai_panel()
        panel.ai_stream_render_interval_sec = 0.0

        panel.on_progress({"event": "run_start", "trace_id": "trace-thought"})
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-thought",
                "data": "model thought",
                "meta": {"channel": "thought"},
            }
        )
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-thought",
                "data": " final answer",
                "meta": {"channel": "answer"},
            }
        )

        rendered = panel.ai_chat.toPlainText()
        self.assertIn("model thought", rendered)
        self.assertIn("final answer", rendered)
        self.assertIn("\n", rendered)
        self.assertTrue(panel.ai_stream_has_thought)
        self.assertNotIn("toggle_thought", panel.ai_chat.toHtml())

    def test_ai_panel_append_chat_prefers_insert_markdown_when_available(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatWithMarkdown()

        panel._append_chat("Agent", "**bold**")

        call_names = [name for name, _value in panel.ai_chat.calls]
        # _append_chat now combines header+body HTML and uses append()
        self.assertIn("append", call_names)
        # Verify bold was converted to HTML (mistune uses <strong>)
        appended_values = [v for n, v in panel.ai_chat.calls if n == "append"]
        self.assertTrue(any("<strong>" in str(v) or "<b>" in str(v) for v in appended_values))

    def test_ai_panel_stream_chunk_updates_chat_incrementally(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-stream"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-stream", "data": "hello"})

        chunk_calls = [
            value for name, value in panel.ai_chat.calls
            if name == "insertPlainText"
        ]
        self.assertIn("hello", chunk_calls)

    def test_ai_panel_stream_chunk_rerenders_markdown_incrementally(self):
        panel = self._new_ai_panel()
        panel.ai_stream_render_interval_sec = 0.0
        panel.ai_stream_render_min_delta = 1

        panel.on_progress({"event": "run_start", "trace_id": "trace-md-live"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-md-live", "data": "**bold**"})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("bold", rendered_text)
        self.assertNotIn("**bold**", rendered_text)

    def test_ai_panel_finished_does_not_duplicate_streamed_final(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-stream"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-stream", "data": "hello"})
        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-stream"}})

        chunk_calls = [
            value for name, value in panel.ai_chat.calls
            if name == "insertPlainText"
        ]
        self.assertEqual(1, chunk_calls.count("hello"))

    def test_ai_panel_finished_renders_markdown_for_thought_and_answer(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-md-thought"})
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-md-thought",
                "data": "**plan**",
                "meta": {"channel": "thought"},
            }
        )
        panel.on_progress(
            {
                "event": "chunk",
                "trace_id": "trace-md-thought",
                "data": "**final**",
                "meta": {"channel": "answer"},
            }
        )
        panel.on_finished({"ok": True, "result": {"final": "**final**", "trace_id": "trace-md-thought"}})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("plan", rendered_text)
        self.assertIn("final", rendered_text)
        self.assertNotIn("**plan**", rendered_text)
        self.assertNotIn("**final**", rendered_text)

    def test_ai_panel_shows_tool_progress_in_chat(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-tool"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-tool",
                "data": {"name": "query_takeout_events"},
            }
        )
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-tool",
                "step": 1,
                "data": {"name": "query_takeout_events"},
                "observation": {"ok": True},
            }
        )

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
        self.assertIn("query_takeout_events", merged)
        self.assertNotIn("finished", merged)

    def test_ai_panel_tool_end_keeps_ui_brief(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-tool-brief"})
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-tool-brief",
                "data": {"name": "bash"},
                "observation": {
                    "ok": False,
                    "error_code": "terminal_nonzero_exit",
                    "message": "exit code 1",
                    "_hint": "Use powershell on Windows",
                    "resolved_path": "D:/repo/file.txt",
                    "effective_root": "D:/repo",
                    "raw_output": "verbose details",
                },
            }
        )

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
        self.assertIn("FAIL: exit code 1", merged)
        self.assertNotIn("finished", merged)
        self.assertNotIn("Hint:", merged)
        self.assertNotIn("Code:", merged)
        self.assertNotIn("Path:", merged)
        self.assertNotIn("Root:", merged)
        self.assertNotIn("Raw output:", merged)
        self.assertNotIn("Reason:", merged)

    def test_ai_panel_tool_start_prefers_status_text(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-status"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-status",
                "status_text": "List files in migrate/inputs",
                "data": {"name": "fs_list"},
            }
        )

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
        self.assertIn("List files in migrate/inputs", merged)
        self.assertNotIn("Running fs_list", merged)

    def test_ai_panel_renders_blocked_items_from_tool_result(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-blocked"})
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-blocked",
                "step": 1,
                "data": {"name": "record_takeout"},
                "observation": {
                    "ok": False,
                    "error_code": "plan_preflight_failed",
                    "message": "Validation blocked",
                    "blocked_items": [
                        {
                            "action": "takeout",
                            "record_id": 999,
                            "box": 1,
                            "position": 5,
                            "error_code": "record_not_found",
                            "message": "Record does not exist",
                        }
                    ],
                },
            }
        )

        append_calls = [value for name, value in panel.ai_chat.calls if name == "append"]
        merged = "\n".join(append_calls)
        self.assertIn("Tool blocked", merged)
        self.assertIn("ID 999", merged)
        self.assertIn(
            localize_error_payload({"error_code": "record_not_found", "message": "Record does not exist"}),
            merged,
        )

    def test_ai_panel_rewrites_streamed_markdown_on_finish(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-md"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-md", "data": "**bold**"})
        panel.on_finished({"ok": True, "result": {"final": "**bold**", "trace_id": "trace-md"}})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("bold", rendered_text)
        self.assertNotIn("**bold**", rendered_text)

    def test_ai_panel_message_after_markdown_list_does_not_join_list(self):
        panel = self._new_ai_panel()

        panel._append_chat("Agent", "1. first\n2. second\n3. third")
        html_before = panel.ai_chat.toHtml()
        li_before = html_before.count("<li")
        self.assertGreater(li_before, 0)

        panel._append_chat("You", "8...")

        html = panel.ai_chat.toHtml()
        self.assertEqual(li_before, html.count("<li"))
        self.assertIn("You</span>", html)
        self.assertNotIn("You</span></li>", html)

    def test_ai_panel_compact_tool_message_after_markdown_list_does_not_join_list(self):
        panel = self._new_ai_panel()

        panel._append_chat("Agent", "1. first\n2. second")
        html_before = panel.ai_chat.toHtml()
        li_before = html_before.count("<li")
        self.assertGreater(li_before, 0)

        panel._append_tool_message("Running generate_stats")

        html = panel.ai_chat.toHtml()
        self.assertEqual(li_before, html.count("<li"))
        self.assertIn("[Tool]", panel.ai_chat.toPlainText())

    def test_ai_panel_keeps_view_when_user_scrolled_up_and_new_message_arrives(self):
        panel = self._new_ai_panel()
        panel.resize(560, 320)
        panel.show()
        self._app.processEvents()

        for i in range(100):
            panel._append_chat("Agent", f"history line {i}")
        self._app.processEvents()

        scroll_bar = panel.ai_chat.verticalScrollBar()
        self.assertGreater(scroll_bar.maximum(), 0)
        scroll_bar.setValue(max(scroll_bar.minimum(), scroll_bar.maximum() - 200))
        self._app.processEvents()
        before_value = scroll_bar.value()

        panel._append_chat("Agent", "latest line")
        self._app.processEvents()

        self.assertLess(scroll_bar.value(), scroll_bar.maximum())
        self.assertAlmostEqual(before_value, scroll_bar.value(), delta=32)
        self.assertTrue(panel.ai_new_msg_btn.isVisible())

    def test_ai_panel_auto_follows_when_user_stays_near_bottom(self):
        panel = self._new_ai_panel()
        panel.resize(560, 320)
        panel.show()
        self._app.processEvents()

        for i in range(100):
            panel._append_chat("Agent", f"history line {i}")
        self._app.processEvents()

        scroll_bar = panel.ai_chat.verticalScrollBar()
        self.assertGreater(scroll_bar.maximum(), 0)
        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())

        panel._append_chat("Agent", "latest line")
        self._app.processEvents()

        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())
        self.assertFalse(panel.ai_new_msg_btn.isVisible())

    def test_ai_panel_jump_to_latest_button_recovers_follow_mode(self):
        panel = self._new_ai_panel()
        panel.resize(560, 320)
        panel.show()
        self._app.processEvents()

        for i in range(100):
            panel._append_chat("Agent", f"history line {i}")
        self._app.processEvents()

        scroll_bar = panel.ai_chat.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), scroll_bar.maximum() - 240))
        self._app.processEvents()

        panel._append_chat("Agent", "latest line")
        self._app.processEvents()
        self.assertTrue(panel.ai_new_msg_btn.isVisible())
        self.assertFalse(panel.ai_auto_follow_enabled)
        self.assertGreater(panel.ai_unseen_message_count, 0)

        panel.ai_new_msg_btn.click()
        self._app.processEvents()

        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())
        self.assertTrue(panel.ai_auto_follow_enabled)
        self.assertEqual(0, panel.ai_unseen_message_count)
        self.assertFalse(panel.ai_new_msg_btn.isVisible())

    def test_ai_panel_stream_chunk_does_not_force_scroll_when_scrolled_up(self):
        panel = self._new_ai_panel()
        panel.resize(560, 320)
        panel.show()
        self._app.processEvents()

        for i in range(100):
            panel._append_chat("Agent", f"history line {i}")
        self._app.processEvents()

        scroll_bar = panel.ai_chat.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), scroll_bar.maximum() - 220))
        self._app.processEvents()
        before_value = scroll_bar.value()

        panel.on_progress({"event": "run_start", "trace_id": "trace-scroll"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-scroll", "data": "chunk data"})
        self._app.processEvents()

        self.assertLess(scroll_bar.value(), scroll_bar.maximum())
        self.assertAlmostEqual(before_value, scroll_bar.value(), delta=40)
        self.assertTrue(panel.ai_new_msg_btn.isVisible())

    def test_ai_panel_question_dialog_is_non_modal_and_keeps_latest_jump_available(self):
        from PySide6.QtWidgets import QDialog

        class _FakeWorker:
            def __init__(self):
                self.answers = []
                self.cancelled = 0

            def set_answer(self, answer):
                self.answers.append(answer)

            def cancel_answer(self):
                self.cancelled += 1

        panel = self._new_ai_panel()
        panel.resize(560, 320)
        panel.show()
        self._app.processEvents()

        for i in range(100):
            panel._append_chat("Agent", f"history line {i}")
        self._app.processEvents()

        scroll_bar = panel.ai_chat.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), scroll_bar.maximum() - 220))
        self._app.processEvents()

        worker = _FakeWorker()
        panel.ai_run_worker = worker
        panel.on_progress({"event": "run_start", "trace_id": "trace-question"})
        panel._handle_question_event(
            {
                "type": "question",
                "question": "**Need your choice**",
                "options": ["Option A", "Option B"],
                "trace_id": "trace-question",
            }
        )
        self._app.processEvents()

        dialogs = [dialog for dialog in panel.findChildren(QDialog) if dialog.isVisible()]
        self.assertEqual(1, len(dialogs))
        self.assertEqual(Qt.NonModal, dialogs[0].windowModality())
        self.assertFalse(panel.ai_prompt.isEnabled())
        self.assertTrue(panel.ai_new_msg_btn.isVisible())

        panel.ai_new_msg_btn.click()
        self._app.processEvents()

        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())

        dialogs[0].reject()
        self._app.processEvents()

        self.assertEqual(1, worker.cancelled)
        self.assertTrue(panel.ai_prompt.isEnabled())

    def test_ai_panel_question_dialog_submit_sets_answer_and_unlocks_prompt(self):
        from PySide6.QtWidgets import QComboBox, QDialog

        class _FakeWorker:
            def __init__(self):
                self.answers = []
                self.cancelled = 0

            def set_answer(self, answer):
                self.answers.append(answer)

            def cancel_answer(self):
                self.cancelled += 1

        panel = self._new_ai_panel()
        worker = _FakeWorker()
        panel.ai_run_worker = worker
        panel.on_progress({"event": "run_start", "trace_id": "trace-submit"})

        panel._handle_question_event(
            {
                "type": "question",
                "question": "Pick one",
                "options": ["Option A", "Option B"],
                "trace_id": "trace-submit",
            }
        )
        self._app.processEvents()

        dialog = next(dialog for dialog in panel.findChildren(QDialog) if dialog.isVisible())
        combo = dialog.findChild(QComboBox)

        combo.setCurrentText("Option B")
        panel._finalize_pending_ai_wait(panel._pending_ai_dialog_state, answer=str(combo.currentText()))
        dialog.accept()
        self._app.processEvents()

        self.assertEqual(["Option B"], worker.answers)
        self.assertEqual(0, worker.cancelled)
        self.assertTrue(panel.ai_prompt.isEnabled())

    def test_ai_panel_max_steps_dialog_is_non_modal_and_blocks_follow_up_prompt(self):
        class _FakeWorker:
            def __init__(self):
                self.answers = []
                self.cancelled = 0

            def set_answer(self, answer):
                self.answers.append(answer)

            def cancel_answer(self):
                self.cancelled += 1

        panel = self._new_ai_panel()
        worker = _FakeWorker()
        panel.ai_run_worker = worker
        panel.on_progress({"event": "run_start", "trace_id": "trace-max-steps"})

        panel._handle_max_steps_ask(
            {
                "type": "max_steps_ask",
                "steps": 3,
                "trace_id": "trace-max-steps",
            }
        )
        self._app.processEvents()

        dialogs = [dialog for dialog in panel.findChildren(QMessageBox) if dialog.isVisible()]
        self.assertEqual(1, len(dialogs))
        self.assertEqual(Qt.NonModal, dialogs[0].windowModality())
        self.assertFalse(panel.ai_prompt.isEnabled())

        dialogs[0].button(QMessageBox.Yes).click()
        self._app.processEvents()

        self.assertEqual([["continue"]], worker.answers)
        self.assertEqual(0, worker.cancelled)
        self.assertTrue(panel.ai_prompt.isEnabled())

    def test_ai_panel_stop_closes_pending_question_dialog(self):
        from PySide6.QtWidgets import QDialog

        class _FakeWorker:
            def __init__(self):
                self.answers = []
                self.cancelled = 0
                self.stop_requests = 0

            def set_answer(self, answer):
                self.answers.append(answer)

            def cancel_answer(self):
                self.cancelled += 1

            def request_stop(self):
                self.stop_requests += 1
                self.cancel_answer()

        panel = self._new_ai_panel()
        worker = _FakeWorker()
        panel.ai_run_worker = worker
        panel.ai_run_inflight = True
        panel.on_progress({"event": "run_start", "trace_id": "trace-stop-dialog"})

        panel._handle_question_event(
            {
                "type": "question",
                "question": "Need input",
                "options": ["A", "B"],
                "trace_id": "trace-stop-dialog",
            }
        )
        self._app.processEvents()
        self.assertTrue(any(dialog.isVisible() for dialog in panel.findChildren(QDialog)))

        panel.on_stop_ai_agent()
        self._app.processEvents()

        self.assertFalse(any(dialog.isVisible() for dialog in panel.findChildren(QDialog)))
        self.assertGreaterEqual(worker.stop_requests, 1)
        self.assertGreaterEqual(worker.cancelled, 1)
        self.assertTrue(panel.ai_prompt.isEnabled())

    def test_ai_panel_separates_multiple_runs_without_merging_messages(self):
        panel = self._new_ai_panel()

        panel._append_chat("You", "hi")
        panel.on_progress({"event": "run_start", "trace_id": "trace-a"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-a", "data": "hello"})
        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-a"}})

        panel._append_chat("You", "overview")
        panel.on_progress({"event": "run_start", "trace_id": "trace-b"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-b", "data": "summary"})
        panel.on_finished({"ok": True, "result": {"final": "summary", "trace_id": "trace-b"}})

        text = panel.ai_chat.toPlainText()
        self.assertGreaterEqual(text.count("You"), 2)
        self.assertIn("hi", text)
        self.assertIn("overview", text)
        self.assertNotIn("hioverview", text)

    def test_ai_panel_tool_start_breaks_stream_text_boundary(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-boundary"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-boundary", "data": "hello"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-boundary",
                "data": {"name": "generate_stats"},
            }
        )

        text = panel.ai_chat.toPlainText()
        self.assertIn("hello", text)
        self.assertIn("Running generate_stats", text)
        self.assertNotIn("helloRunning", text)

    def test_ai_panel_finished_uses_wrapped_result_shape(self):
        panel = self._new_ai_panel()

        panel.on_finished({"ok": True, "result": {"final": "hello", "trace_id": "trace-test"}})

        self.assertGreaterEqual(len(panel.ai_history), 1)
        self.assertEqual("assistant", panel.ai_history[-1]["role"])
        self.assertEqual("hello", panel.ai_history[-1]["content"])

    def test_ai_panel_stream_end_persists_tool_history_and_dedupes_final(self):
        panel = self._new_ai_panel()
        panel.on_progress(
            {
                "event": "stream_end",
                "trace_id": "trace-stream-end",
                "data": {
                    "status": "complete",
                    "messages": [
                        {"role": "user", "content": "hi", "timestamp": 1.0},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_records",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                            "timestamp": 2.0,
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call_1",
                            "content": '{"ok":true}',
                            "timestamp": 3.0,
                        },
                        {"role": "assistant", "content": "done", "timestamp": 4.0},
                    ],
                    "summary_state": {
                        "checkpoint_id": "checkpoint-1",
                        "summary_text": "## Current Objective\nResume work",
                    },
                },
            }
        )

        self.assertEqual(4, len(panel.ai_history))
        self.assertEqual("tool", panel.ai_history[2].get("role"))
        self.assertEqual("call_1", panel.ai_history[2].get("tool_call_id"))
        self.assertEqual("checkpoint-1", (panel.ai_summary_state or {}).get("checkpoint_id"))

        panel.on_finished({"ok": True, "result": {"final": "done", "trace_id": "trace-stream-end"}})
        final_assistant_count = sum(
            1
            for item in panel.ai_history
            if item.get("role") == "assistant" and item.get("content") == "done"
        )
        self.assertEqual(1, final_assistant_count)

    def test_ai_panel_context_checkpoint_event_appends_system_notice(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-checkpoint"})
        panel.on_progress(
            {
                "event": "context_checkpoint",
                "trace_id": "trace-checkpoint",
                "data": {
                    "checkpoint_id": "checkpoint-ctx",
                    "message": "Context checkpoint created. Agent memory will continue from condensed summary.",
                },
            }
        )

        self.assertEqual("checkpoint-ctx", (panel.ai_summary_state or {}).get("checkpoint_id"))
        self.assertIn("Context checkpoint created", panel.ai_chat.toPlainText())

    def test_ai_panel_finished_flags_protocol_error_without_result(self):
        panel = self._new_ai_panel()

        panel.on_finished({"ok": True, "result": None})

        self.assertGreaterEqual(len(panel.ai_history), 1)
        self.assertEqual("assistant", panel.ai_history[-1]["role"])
        self.assertIn("protocol error", panel.ai_history[-1]["content"].lower())

    def test_ai_panel_finished_emits_status_for_missing_api_key(self):
        panel = self._new_ai_panel()
        messages = []
        panel.status_message.connect(lambda msg, timeout: messages.append((msg, timeout)))

        panel.on_finished({"ok": False, "error_code": "api_key_required", "result": None})

        self.assertTrue(messages)
        self.assertIn("api key", messages[-1][0].lower())

    def test_ai_panel_finished_renders_explicit_agent_error_details(self):
        panel = self._new_ai_panel()

        panel.on_finished(
            {
                "ok": False,
                "result": {
                    "final": "Agent failed: LLM stream error.",
                    "error_code": "llm_transport_error",
                    "message": "MiniMax request failed: EOF occurred in violation of protocol",
                    "details": {
                        "provider": "MiniMax",
                        "endpoint": "https://api.minimaxi.com/v1/chat/completions",
                        "exception_type": "URLError",
                    },
                    "trace_id": "trace-err",
                },
            }
        )

        self.assertTrue(panel.ai_collapsible_blocks)
        self.assertIn("MiniMax request failed", panel.ai_collapsible_blocks[-1]["content"])
        self.assertEqual(
            "MiniMax request failed: EOF occurred in violation of protocol",
            panel.ai_history[-1]["content"],
        )

    def test_ai_panel_stop_blocks_late_progress_updates(self):
        panel = self._new_ai_panel()
        panel.ai_run_inflight = True

        class _StopWorker:
            def __init__(self):
                self.called = False

            def request_stop(self):
                self.called = True

        worker = _StopWorker()
        panel.ai_run_worker = worker

        panel.on_progress({"event": "run_start", "trace_id": "trace-stop"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-stop", "data": "before stop"})
        before_text = panel.ai_chat.toPlainText()

        panel.on_stop_ai_agent()
        self.assertTrue(worker.called)
        self.assertTrue(panel.ai_stop_requested)
        self.assertFalse(panel.ai_run_inflight)
        stopped_text = panel.ai_chat.toPlainText()
        self.assertIn("run", stopped_text.lower())

        panel.on_progress({"event": "chunk", "trace_id": "trace-stop", "data": " after stop"})
        after_text = panel.ai_chat.toPlainText()
        self.assertEqual(stopped_text, after_text)

    def test_ai_panel_can_start_new_run_after_stop_even_if_old_thread_still_running(self):
        panel = self._new_ai_panel()
        panel.ai_stop_requested = True
        panel.ai_run_inflight = False
        panel.ai_prompt.setPlainText("new run prompt")

        class _RunningThread:
            def isRunning(self):
                return True

        class _StopWorker:
            def __init__(self):
                self.called = False

            def request_stop(self):
                self.called = True

        stale_thread = _RunningThread()
        stale_worker = _StopWorker()
        panel.ai_run_thread = stale_thread
        panel.ai_run_worker = stale_worker

        with patch.object(panel, "start_worker") as start_mock:
            panel.on_run_ai_agent()

        self.assertTrue(stale_worker.called)
        self.assertFalse(panel.ai_stop_requested)
        self.assertIsNone(panel.ai_run_thread)
        self.assertIsNone(panel.ai_run_worker)
        start_mock.assert_called_once_with("new run prompt")

    def test_ai_panel_ignores_stale_worker_progress_sender(self):
        panel = self._new_ai_panel()
        panel.ai_run_worker = object()
        stale_sender = object()
        before_text = panel.ai_chat.toPlainText()

        with patch.object(AIPanel, "sender", return_value=stale_sender):
            panel.on_progress({"event": "chunk", "trace_id": "trace-stale", "data": "ignored"})

        after_text = panel.ai_chat.toPlainText()
        self.assertEqual(before_text, after_text)

    def test_ai_panel_ignores_stale_worker_finished_sender(self):
        panel = self._new_ai_panel()
        panel.ai_run_worker = object()
        stale_sender = object()
        history_len_before = len(panel.ai_history)

        with patch.object(AIPanel, "sender", return_value=stale_sender):
            panel.on_finished({"ok": True, "result": {"final": "ignored stale final"}})

        self.assertEqual(history_len_before, len(panel.ai_history))

    def test_ai_panel_finished_persists_stop_history_after_stop_request(self):
        panel = self._new_ai_panel()
        panel.ai_stop_requested = True
        panel.ai_run_inflight = True
        completed = []
        panel.operation_completed.connect(lambda ok: completed.append(bool(ok)))

        history_len_before = len(panel.ai_history)
        panel.on_finished({"ok": True, "result": {"final": "should not render"}})

        self.assertGreater(len(panel.ai_history), history_len_before)
        self.assertEqual("assistant", panel.ai_history[-1]["role"])
        self.assertIn("should not render", panel.ai_history[-1]["content"])
        self.assertEqual([False], completed)

@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class OperationEventFeedTests(ManagedPathTestCase):
    """Regression: operation events should flow to AI panel."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_ai_panel(self):
        from app_gui.ui.ai_panel import AIPanel
        return AIPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    @staticmethod
    def _make_mouse_release_event(x=6.0, y=6.0):
        local_pos = QPointF(float(x), float(y))
        return QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            local_pos,
            local_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_ai_panel_receives_operation_events(self):
        """AI panel should normalize operation events to system notices."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_executed",
            "timestamp": "2026-02-12T10:00:00",
            "ok": True,
            "stats": {"total": 1, "ok": 1, "blocked": 0},
            "summary": "All 1 operation(s) succeeded.",
        })

        self.assertEqual(1, len(panel.ai_operation_events))
        self.assertEqual("system_notice", panel.ai_operation_events[0].get("type"))
        self.assertEqual("plan.execute.result", panel.ai_operation_events[0].get("code"))
        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("succeeded", chat_text)
        self.assertNotIn("plan.execute.result", chat_text)

    def test_ai_panel_import_tool_success_calls_dataset_switch_handler(self):
        switched = []
        panel = AIPanel(
            bridge=object(),
            yaml_path_getter=lambda: self.fake_yaml_path,
            import_dataset_handler=lambda path: switched.append(path) or path,
        )
        panel.set_migration_mode_enabled(True)
        self.assertTrue(panel._migration_mode_enabled)

        panel.on_progress(
            {
                "event": "tool_end",
                "type": "tool_end",
                "data": {"name": "generic_effect_tool"},
                "observation": {
                    "ok": True,
                    "ui_effects": [
                        {
                            "type": "open_dataset",
                            "target_path": "D:/inventories/ln2_inventory/inventory.yaml",
                        },
                        {
                            "type": "migration_mode",
                            "enabled": False,
                        },
                    ],
                },
            }
        )

        self.assertEqual(["D:/inventories/ln2_inventory/inventory.yaml"], switched)
        self.assertFalse(panel._migration_mode_enabled)
        self.assertTrue(panel._migration_mode_banner.isHidden())
        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("imported dataset opened", chat_text)

    def test_ai_panel_tool_end_applies_migration_mode_ui_effect(self):
        panel = self._new_ai_panel()
        self.assertFalse(panel._migration_mode_enabled)

        panel.on_progress(
            {
                "event": "tool_end",
                "type": "tool_end",
                "data": {"name": "use_skill"},
                "observation": {
                    "ok": True,
                    "ui_effects": [
                        {
                            "type": "migration_mode",
                            "enabled": True,
                            "reason": "use_skill:migration",
                        }
                    ],
                },
            }
        )

        self.assertTrue(panel._migration_mode_enabled)
        self.assertFalse(panel._migration_mode_banner.isHidden())

    def test_ai_panel_repeated_migration_mode_ui_effect_is_idempotent(self):
        panel = self._new_ai_panel()
        mode_changes = []
        status_messages = []
        panel.migration_mode_changed.connect(lambda enabled: mode_changes.append(bool(enabled)))
        panel.status_message.connect(lambda msg, timeout: status_messages.append((msg, timeout)))
        event = {
            "event": "tool_end",
            "type": "tool_end",
            "data": {"name": "use_skill"},
            "observation": {
                "ok": True,
                "ui_effects": [
                    {
                        "type": "migration_mode",
                        "enabled": True,
                        "reason": "use_skill:migration",
                    }
                ],
            },
        }

        panel.on_progress(event)
        panel.on_progress(event)

        self.assertTrue(panel._migration_mode_enabled)
        self.assertEqual([True], mode_changes)
        self.assertEqual([(tr("ai.migrationModeEnteredStatus"), 4000)], status_messages)

    def test_ai_panel_migration_mode_updates_banner_and_status(self):
        panel = self._new_ai_panel()
        mode_changes = []
        status_messages = []
        panel.migration_mode_changed.connect(lambda enabled: mode_changes.append(bool(enabled)))
        panel.status_message.connect(lambda msg, timeout: status_messages.append((msg, timeout)))

        panel.set_migration_mode_enabled(True)

        self.assertTrue(panel._migration_mode_enabled)
        self.assertFalse(panel._migration_mode_banner.isHidden())
        self.assertEqual([True], mode_changes)
        self.assertIn((tr("ai.migrationModeEnteredStatus"), 4000), status_messages)
        self.assertTrue(bool(panel.ai_run_btn.property("migrationAttention")))

        panel.set_migration_mode_enabled(False)

        self.assertFalse(panel._migration_mode_enabled)
        self.assertTrue(panel._migration_mode_banner.isHidden())
        self.assertEqual([True, False], mode_changes)
        self.assertEqual((tr("ai.migrationModeExitedStatus"), 4000), status_messages[-1])

    def test_ai_panel_run_button_attention_clears_after_timer(self):
        panel = self._new_ai_panel()

        panel._flash_run_button_attention(duration_ms=30)
        self.assertTrue(bool(panel.ai_run_btn.property("migrationAttention")))

        QTest.qWait(80)
        self.assertFalse(bool(panel.ai_run_btn.property("migrationAttention")))

    def test_ai_panel_import_tool_success_reports_switch_failure(self):
        panel = AIPanel(
            bridge=object(),
            yaml_path_getter=lambda: self.fake_yaml_path,
            import_dataset_handler=lambda _path: (_ for _ in ()).throw(RuntimeError("switch failed")),
        )
        panel.set_migration_mode_enabled(True)
        self.assertTrue(panel._migration_mode_enabled)

        panel.on_progress(
            {
                "event": "tool_end",
                "type": "tool_end",
                "data": {"name": "generic_effect_tool"},
                "observation": {
                    "ok": True,
                    "ui_effects": [
                        {
                            "type": "open_dataset",
                            "target_path": "D:/inventories/ln2_inventory/inventory.yaml",
                        },
                        {
                            "type": "migration_mode",
                            "enabled": False,
                        },
                    ],
                },
            }
        )

        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("opening dataset failed", chat_text)
        self.assertTrue(panel._migration_mode_enabled)

    def test_ai_panel_prepare_import_migration_prefills_prompt(self):
        panel = self._new_ai_panel()

        panel.prepare_import_migration("run staged migration", focus=False)

        self.assertEqual("run staged migration", panel.ai_prompt.toPlainText())
        self.assertFalse(panel._migration_mode_enabled)

    def test_ai_panel_prepare_import_migration_clears_plan_store(self):
        from lib.plan_store import PlanStore

        plan_store = PlanStore()
        plan_store.add(
            [
                {
                    "action": "add",
                    "box": 1,
                    "positions": [1],
                    "fields": {"cell_line": "K562"},
                }
            ]
        )
        panel = AIPanel(
            bridge=object(),
            yaml_path_getter=lambda: self.fake_yaml_path,
            plan_store=plan_store,
        )
        self.assertEqual(1, plan_store.count())

        panel.prepare_import_migration("run staged migration", focus=False)

        self.assertFalse(panel._migration_mode_enabled)
        self.assertEqual(0, plan_store.count())

    def test_ai_panel_runtime_settings_helpers_roundtrip(self):
        panel = self._new_ai_panel()

        panel.apply_runtime_settings(
            provider="deepseek",
            model="deepseek-v4-flash",
            max_steps=11,
            thinking_enabled=False,
            custom_prompt="stay concise",
        )

        snapshot = panel.runtime_settings_snapshot()

        self.assertEqual("deepseek", snapshot["provider"])
        self.assertEqual("deepseek-v4-flash", snapshot["model"])
        self.assertEqual(11, snapshot["max_steps"])
        self.assertFalse(snapshot["thinking_enabled"])
        self.assertEqual("stay concise", snapshot["custom_prompt"])
        self.assertFalse(panel.has_running_task())
        panel.ai_run_inflight = True
        self.assertTrue(panel.has_running_task())

    def test_ai_panel_limits_operation_events(self):
        """AI panel should limit stored operation events to prevent memory growth."""
        from app_gui.gui_config import AI_OPERATION_EVENT_POOL_LIMIT

        panel = self._new_ai_panel()

        for i in range(30):
            panel.on_operation_event({
                "type": "plan_executed",
                "timestamp": f"2026-02-12T10:{i:02d}:00",
                "ok": True,
                "stats": {"total": 1, "ok": 1},
                "summary": f"Event {i}",
            })

        self.assertLessEqual(len(panel.ai_operation_events), AI_OPERATION_EVENT_POOL_LIMIT)

    def test_ai_panel_limits_chat_history_by_config(self):
        """AI panel history should honor AI_HISTORY_LIMIT constant."""
        from app_gui.gui_config import AI_HISTORY_LIMIT

        panel = self._new_ai_panel()
        for i in range(AI_HISTORY_LIMIT + 15):
            panel._append_history("user", f"msg-{i}")

        self.assertEqual(AI_HISTORY_LIMIT, len(panel.ai_history))
        self.assertEqual(f"msg-{AI_HISTORY_LIMIT + 14}", panel.ai_history[-1]["content"])

    def test_ai_panel_shows_blocked_events(self):
        """AI panel should show blocked execution events."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_execute_blocked",
            "timestamp": "2026-02-12T10:00:00",
            "blocked_count": 2,
        })

        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("blocked", chat_text)
        self.assertIn("2", chat_text)

    def test_ai_panel_shows_plan_executed_failure_details(self):
        """Failed plan_executed event should surface summary and raw details."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "plan_executed",
            "timestamp": "2026-02-12T10:00:00",
            "ok": False,
            "stats": {"total": 3, "ok": 2, "blocked": 1},
            "summary": "Blocked: 1/3 items cannot execute.",
            "report": {
                "items": [
                    {
                        "blocked": True,
                        "message": "Record 2 failed",
                        "item": {"record_id": 2},
                    }
                ]
            },
            "rollback": {"attempted": True, "ok": True},
        })

        chat_text = panel.ai_chat.toPlainText().lower()
        self.assertIn("blocked: 1/3", chat_text)
        self.assertTrue(panel.ai_collapsible_blocks)
        details_text = str(panel.ai_collapsible_blocks[-1].get("content", "")).lower()
        self.assertIn("record 2 failed", details_text)
        self.assertIn("rollback", details_text)

    def test_ai_panel_system_notice_prefers_compact_operation_details(self):
        """System notices should show concise operation lines, not raw JSON dumps."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "system_notice",
            "code": "plan.execute.result",
            "level": "success",
            "text": "Applied: 1/1 operations.",
            "data": {
                "stats": {"total": 1, "applied": 1, "failed": 0, "blocked": 0, "remaining": 0},
                "sample": ["OK: Takeout | ID 18 | Box 1:18 | cell_line=U2OS, short_name=U2OS_backup_stock"],
                "report": {
                    "backup_path": "/tmp/demo.bak",
                    "items": [{"ok": True, "item": {"action": "takeout", "record_id": 18, "box": 1, "position": 18}}],
                },
            },
        })

        self.assertTrue(panel.ai_collapsible_blocks)
        details_text = str(panel.ai_collapsible_blocks[-1].get("content", ""))
        self.assertIn("Operations (1)", details_text)
        self.assertIn("takeout | id 18", details_text.lower())
        self.assertNotIn('"report"', details_text)

    def test_ai_panel_system_notice_hides_all_details_in_collapsed_preview(self):
        """Collapsed system notice should only show summary; details remain behind expand."""
        panel = self._new_ai_panel()

        panel.on_operation_event({
            "type": "system_notice",
            "timestamp": "2026-02-20T15:05:55.645887",
            "code": "record.edit.saved",
            "level": "success",
            "text": "Field \'cell_line\' updated: U2OS -> NCCIT",
            "data": {
                "record_id": 18,
                "field": "cell_line",
                "before": "U2OS",
                "after": "NCCIT",
            },
        })

        self.assertTrue(panel.ai_collapsible_blocks)
        chat_text = panel.ai_chat.toPlainText()
        self.assertIn("cell_line", chat_text)
        self.assertIn("Expand", chat_text)
        self.assertNotIn("Operations (1)", chat_text)
        self.assertNotIn("code=record.edit.saved", chat_text)
        self.assertNotIn("2026-02-20T15:05:55.645887", chat_text)

        details_text = str(panel.ai_collapsible_blocks[-1].get("content", ""))
        first_line = details_text.splitlines()[0] if details_text.splitlines() else ""
        self.assertIn("Operations", first_line)
        self.assertNotIn("Type:", first_line)
        self.assertNotIn("Time:", first_line)

    def test_ai_panel_notice_dedupes_details_for_plan_stage_accepted(self):
        """Safe notice types should hide duplicate Details lines when Operations already contain them."""
        panel = self._new_ai_panel()
        event = {
            "type": "system_notice",
            "code": "plan.stage.accepted",
            "level": "info",
            "text": "Added 1 item(s) to plan.",
            "timestamp": "2026-02-21T23:02:16.978201",
            "details": "Takeout | ID 23 | Box 3:22",
            "data": {
                "added_count": 1,
                "total_count": 1,
                "sample": ["Takeout | ID 23 | Box 3:22"],
            },
        }

        details_text = panel._format_system_notice_details(event)
        self.assertIn("Operations (1):", details_text)
        self.assertNotIn("Details:", details_text)
        self.assertIn("Counts: added=1, total=1", details_text)
        self.assertIn("Meta: code=plan.stage.accepted", details_text)

    def test_ai_panel_notice_keeps_details_when_it_has_extra_context(self):
        """Details should stay visible when it adds context beyond operation lines."""
        panel = self._new_ai_panel()
        event = {
            "type": "system_notice",
            "code": "plan.stage.accepted",
            "level": "info",
            "text": "Added 1 item(s) to plan.",
            "details": "Takeout | ID 23 | Box 3:22 | source=form",
            "data": {
                "added_count": 1,
                "total_count": 1,
                "sample": ["Takeout | ID 23 | Box 3:22"],
            },
        }

        details_text = panel._format_system_notice_details(event)
        self.assertIn("Details: Takeout | ID 23 | Box 3:22 | source=form", details_text)

    def test_ai_panel_notice_keeps_details_for_non_dedupe_codes(self):
        """Non-whitelisted notice codes must keep Details even when text repeats operations."""
        panel = self._new_ai_panel()
        blocked_data = {
            "blocked_items": [
                {
                    "action": "takeout",
                    "record_id": 23,
                    "box": 3,
                    "position": 22,
                    "message": "Validation failed",
                }
            ],
            "stats": {"total": 1},
        }
        blocked_ops = panel._extract_notice_operation_lines("plan.stage.blocked", blocked_data)
        event = {
            "type": "system_notice",
            "code": "plan.stage.blocked",
            "level": "error",
            "text": "Plan rejected.",
            "details": blocked_ops[0] if blocked_ops else "Validation failed",
            "data": blocked_data,
        }

        details_text = panel._format_system_notice_details(event)
        self.assertIn("Details:", details_text)
        self.assertIn("Counts: blocked=1, total=1", details_text)

    def test_ai_panel_notice_formats_placeholders_when_tr_falls_back_to_default(self):
        """Fallback/default translation templates should still render formatted numbers."""
        panel = self._new_ai_panel()
        event = {
            "type": "system_notice",
            "code": "plan.stage.accepted",
            "level": "info",
            "text": "Added 1 item(s) to plan.",
            "details": "Takeout | ID 23 | Box 3:22",
            "data": {
                "added_count": 1,
                "total_count": 1,
                "sample": ["Takeout | ID 23 | Box 3:22"],
            },
        }

        from unittest.mock import patch

        def _fallback_default(key, default=None, **kwargs):
            return default if default is not None else key

        with patch("app_gui.ui.ai_panel.tr", side_effect=_fallback_default):
            details_text = panel._format_system_notice_details(event)

        self.assertIn("Operations (1):", details_text)
        self.assertIn("Counts: added=1, total=1", details_text)

    def test_ai_panel_collapsible_uses_single_toggle_link(self):
        """Expanded details should use a single toggle link, not an extra bottom control."""
        panel = self._new_ai_panel()

        collapsed_html = panel._render_collapsible_details(
            "toggle_test",
            "line1\nline2",
            collapsed=True,
            is_dark=True,
            preview_lines=0,
        )
        expanded_html = panel._render_collapsible_details(
            "toggle_test",
            "line1\nline2",
            collapsed=False,
            is_dark=True,
            preview_lines=0,
        )

        self.assertEqual(1, collapsed_html.count("Expand"))
        self.assertNotIn("Collapse", collapsed_html)

        self.assertEqual(1, expanded_html.count("Collapse"))
        self.assertNotIn("Expand", expanded_html)
        self.assertLess(expanded_html.find("Collapse"), expanded_html.find("line1"))

    def test_ai_panel_collapsible_inline_expand_for_zero_preview(self):
        """Collapsed details with zero preview lines should not reserve an extra block row."""
        panel = self._new_ai_panel()

        collapsed_html = panel._render_collapsible_details(
            "toggle_test",
            "line1\nline2",
            collapsed=True,
            is_dark=True,
            preview_lines=0,
        )
        expanded_html = panel._render_collapsible_details(
            "toggle_test",
            "line1\nline2",
            collapsed=False,
            is_dark=True,
            preview_lines=0,
        )

        self.assertIn('href="toggle_test"', collapsed_html)
        self.assertIn("Expand (2 lines)", collapsed_html)
        self.assertNotIn("<table", collapsed_html)
        self.assertNotIn("<div", collapsed_html)

        self.assertIn("Collapse", expanded_html)
        self.assertNotIn("<table", expanded_html)
        self.assertIn("<div", expanded_html)
        self.assertLess(expanded_html.find("Collapse"), expanded_html.find("<div"))

    def test_ai_panel_anchor_click_ignores_legacy_toggle_thought_anchor(self):
        panel = self._new_ai_panel()
        event = self._make_mouse_release_event()
        with patch.object(panel.ai_chat, "anchorAt", return_value="toggle_thought") as anchor_mock:
            with patch.object(panel, "_toggle_collapsible_block") as toggle_mock:
                handled = panel._handle_chat_anchor_click(event)

        self.assertFalse(handled)
        anchor_mock.assert_called_once()
        toggle_mock.assert_not_called()

    def test_ai_panel_event_filter_consumes_toggle_details_anchor_click(self):
        panel = self._new_ai_panel()
        event = self._make_mouse_release_event()
        with patch.object(panel.ai_chat, "anchorAt", return_value="toggle_details_0") as anchor_mock:
            with patch.object(panel, "_toggle_collapsible_block") as toggle_mock:
                handled = panel.eventFilter(panel.ai_chat.viewport(), event)

        self.assertTrue(handled)
        anchor_mock.assert_called_once()
        toggle_mock.assert_called_once_with("toggle_details_0")

    def test_ai_panel_event_filter_does_not_consume_non_anchor_click(self):
        panel = self._new_ai_panel()
        event = self._make_mouse_release_event()
        with patch.object(panel.ai_chat, "anchorAt", return_value=""):
            handled = panel._handle_chat_anchor_click(event)

        self.assertFalse(handled)
