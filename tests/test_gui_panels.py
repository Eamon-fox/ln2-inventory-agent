import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    from app_gui.ui.ai_panel import AIPanel
    from app_gui.ui.overview_panel import OverviewPanel
    from app_gui.ui.operations_panel import OperationsPanel

    PYSIDE_AVAILABLE = True
except Exception:
    QDate = None
    QApplication = None
    AIPanel = None
    OverviewPanel = None
    OperationsPanel = None
    PYSIDE_AVAILABLE = False


class _FakeChatNoMarkdown:
    def __init__(self):
        self.calls = []

    def append(self, text):
        self.calls.append(("append", text))

    def insertPlainText(self, text):
        self.calls.append(("insertPlainText", text))


class _FakeChatWithMarkdown:
    def __init__(self):
        self.calls = []

    def append(self, text):
        self.calls.append(("append", text))

    def insertMarkdown(self, text):
        self.calls.append(("insertMarkdown", text))


class _FakeOperationsBridge:
    def __init__(self):
        self.last_add_payload = None
        self.last_query_filters = None
        self.last_empty_box = None
        self.last_record_payload = None
        self.last_batch_payload = None
        self.add_response = {"ok": True, "result": {"new_id": 99}}
        self.query_response = {
            "ok": True,
            "result": {
                "records": [
                    {
                        "id": 5,
                        "parent_cell_line": "K562",
                        "short_name": "K562_clone12",
                        "box": 2,
                        "positions": [10],
                        "frozen_at": "2026-02-10",
                        "plasmid_id": "P-001",
                        "note": "demo",
                    }
                ],
                "count": 1,
            },
        }
        self.empty_response = {
            "ok": True,
            "result": {
                "boxes": [
                    {
                        "box": "2",
                        "empty_count": 80,
                        "total_slots": 81,
                        "empty_positions": [1, 2, 3],
                    }
                ]
            },
        }

    def add_entry(self, yaml_path, **payload):
        self.last_add_payload = {"yaml_path": yaml_path, **payload}
        return self.add_response

    def query_inventory(self, yaml_path, **filters):
        self.last_query_filters = {"yaml_path": yaml_path, **filters}
        return self.query_response

    def list_empty_positions(self, yaml_path, box=None):
        self.last_empty_box = box
        return self.empty_response

    def record_thaw(self, yaml_path, **payload):
        self.last_record_payload = {"yaml_path": yaml_path, **payload}
        return {"ok": True, "preview": payload, "result": {"record_id": payload.get("record_id")}}

    def batch_thaw(self, yaml_path, **payload):
        self.last_batch_payload = {"yaml_path": yaml_path, **payload}
        entries = payload.get("entries") or []
        record_ids = []
        for entry in entries:
            if isinstance(entry, (list, tuple)) and entry:
                record_ids.append(entry[0])
        return {
            "ok": True,
            "preview": {"count": len(entries), "operations": []},
            "result": {"count": len(entries), "record_ids": record_ids},
        }


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class GuiPanelRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_operations_panel(self):
        return OperationsPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def _new_ai_panel(self):
        return AIPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def _new_overview_panel(self):
        return OverviewPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/inventory.yaml")

    @staticmethod
    def _make_table_item(text):
        from PySide6.QtWidgets import QTableWidgetItem

        return QTableWidgetItem(text)

    def test_operations_panel_refreshes_stale_default_dates(self):
        panel = self._new_operations_panel()
        today = QDate.currentDate()
        yesterday = today.addDays(-1)

        panel._default_date_anchor = yesterday
        panel.a_date.setDate(yesterday)
        panel.t_date.setDate(yesterday)
        panel.b_date.setDate(yesterday)

        panel.set_mode("add")

        self.assertEqual(today, panel.a_date.date())
        self.assertEqual(today, panel.t_date.date())
        self.assertEqual(today, panel.b_date.date())

    def test_operations_panel_does_not_override_user_selected_date(self):
        panel = self._new_operations_panel()
        today = QDate.currentDate()
        yesterday = today.addDays(-1)
        custom_date = today.addDays(-3)

        panel._default_date_anchor = yesterday
        panel.a_date.setDate(custom_date)
        panel.t_date.setDate(yesterday)
        panel.b_date.setDate(yesterday)

        panel._ensure_today_defaults()

        self.assertEqual(custom_date, panel.a_date.date())
        self.assertEqual(today, panel.t_date.date())
        self.assertEqual(today, panel.b_date.date())

    def test_operations_panel_cache_normalizes_string_keys(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                "1": {
                    "id": 1,
                    "parent_cell_line": "K562",
                    "short_name": "k562-a",
                    "box": 1,
                    "positions": [1],
                    "frozen_at": "2026-02-10",
                }
            }
        )

        record = panel._lookup_record(1)
        self.assertIsInstance(record, dict)
        self.assertEqual(1, int(record.get("id")))

    def test_operations_panel_add_entry_parses_positions_text(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        panel._confirm_execute = lambda *_args, **_kwargs: True

        panel.a_parent.setText("K562")
        panel.a_short.setText("K562_clone12")
        panel.a_box.setValue(1)
        panel.a_positions.setText("30-32,35")

        panel.on_add_entry()

        self.assertIsNotNone(bridge.last_add_payload)
        self.assertEqual([30, 31, 32, 35], bridge.last_add_payload.get("positions"))

    def test_operations_panel_add_entry_rejects_invalid_positions_text(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        messages = []
        panel.status_message.connect(lambda msg, timeout, level: messages.append((msg, timeout, level)))

        panel.a_positions.setText("33x")
        panel.on_add_entry()

        self.assertIsNone(bridge.last_add_payload)
        self.assertTrue(messages)
        self.assertIn("位置格式错误", messages[-1][0])

    def test_operations_panel_uses_execute_only_buttons(self):
        panel = self._new_operations_panel()

        self.assertEqual("Execute Add Entry", panel.a_apply_btn.text())
        self.assertEqual("Execute Single Operation", panel.t_apply_btn.text())
        self.assertEqual("Execute Batch Operation", panel.b_apply_btn.text())

        self.assertFalse(hasattr(panel, "a_dry_run"))
        self.assertFalse(hasattr(panel, "t_dry_run"))
        self.assertFalse(hasattr(panel, "b_dry_run"))

    def test_operations_panel_action_dropdown_supports_move(self):
        panel = self._new_operations_panel()

        single_actions = [panel.t_action.itemText(i) for i in range(panel.t_action.count())]
        batch_actions = [panel.b_action.itemText(i) for i in range(panel.b_action.count())]

        self.assertIn("Move", single_actions)
        self.assertIn("Move", batch_actions)

    def test_operations_panel_move_enables_to_position_and_batch_columns(self):
        panel = self._new_operations_panel()

        panel.t_action.setCurrentText("Takeout")
        self.assertFalse(panel.t_to_position.isEnabled())

        panel.t_action.setCurrentText("Move")
        self.assertTrue(panel.t_to_position.isEnabled())

        panel.b_action.setCurrentText("Move")
        self.assertEqual(3, panel.b_table.columnCount())
        self.assertEqual("To", panel.b_table.horizontalHeaderItem(2).text())

    def test_operations_panel_single_move_passes_to_position(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        panel._confirm_execute = lambda *_args, **_kwargs: True

        panel.t_action.setCurrentText("Move")
        panel.t_id.setValue(11)
        panel.t_position.setValue(5)
        panel.t_to_position.setValue(8)
        panel.on_record_thaw()

        self.assertIsNotNone(bridge.last_record_payload)
        self.assertEqual(8, bridge.last_record_payload.get("to_position"))

    def test_operations_panel_batch_move_table_collects_triples(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge
        panel._confirm_execute = lambda *_args, **_kwargs: True

        panel.b_action.setCurrentText("Move")
        panel.b_table.setRowCount(1)
        panel.b_table.setItem(0, 0, panel._make_table_item("12"))
        panel.b_table.setItem(0, 1, panel._make_table_item("23"))
        panel.b_table.setItem(0, 2, panel._make_table_item("31"))

        panel.on_batch_thaw()

        self.assertEqual([(12, 23, 31)], bridge.last_batch_payload.get("entries"))

    def test_operations_panel_emits_completion_on_success_without_dry_run_gate(self):
        panel = self._new_operations_panel()
        emitted = []
        panel.operation_completed.connect(lambda success: emitted.append(bool(success)))

        panel._handle_response({"ok": True, "result": {"dry_run": True}}, "Single Operation")

        self.assertEqual([True], emitted)

    def test_operations_panel_prefill_context_shows_autofill_status(self):
        panel = self._new_operations_panel()
        panel.update_records_cache(
            {
                5: {
                    "id": 5,
                    "parent_cell_line": "K562",
                    "short_name": "K562_RTCB_dTAG_clone12",
                    "box": 1,
                    "positions": [30, 31],
                    "frozen_at": "2026-02-10",
                }
            }
        )

        panel.set_prefill({"box": 1, "position": 30, "record_id": 5})

        self.assertEqual("Record loaded - form auto-filled.", panel.t_ctx_status.text())
        self.assertEqual("Box 1:30", panel.t_ctx_source.text())

    def test_operations_panel_batch_section_collapsed_by_default(self):
        panel = self._new_operations_panel()

        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual("Show Batch Operation", panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(True)
        self.assertFalse(panel.t_batch_group.isHidden())
        self.assertEqual("Hide Batch Operation", panel.t_batch_toggle_btn.text())

        panel.t_batch_toggle_btn.setChecked(False)
        self.assertTrue(panel.t_batch_group.isHidden())
        self.assertEqual("Show Batch Operation", panel.t_batch_toggle_btn.text())

    def test_operations_panel_query_uses_backend_filter_names(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        panel.q_cell.setText("K562")
        panel.q_short.setText("clone12")
        panel.q_plasmid.setText("EGFP")
        panel.q_plasmid_id.setText("P-001")
        panel.q_box.setValue(2)
        panel.q_position.setValue(10)

        panel.on_query_records()

        self.assertEqual(
            {
                "yaml_path": "/tmp/inventory.yaml",
                "cell": "K562",
                "short": "clone12",
                "plasmid": "EGFP",
                "plasmid_id": "P-001",
                "box": 2,
                "position": 10,
            },
            bridge.last_query_filters,
        )
        self.assertEqual(1, panel.query_table.rowCount())
        self.assertEqual("5", panel.query_table.item(0, 0).text())

    def test_operations_panel_list_empty_reads_boxes_payload(self):
        panel = self._new_operations_panel()
        bridge = _FakeOperationsBridge()
        panel.bridge = bridge

        panel.q_box.setValue(2)
        panel.on_list_empty()

        self.assertEqual(2, bridge.last_empty_box)
        self.assertEqual(1, panel.query_table.rowCount())
        self.assertEqual("2", panel.query_table.item(0, 0).text())

    def test_overview_double_click_sets_selected_border_and_emits_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        record = {
            "id": 5,
            "parent_cell_line": "K562",
            "short_name": "K562_RTCB_dTAG_clone12",
            "box": 1,
            "positions": [1],
            "frozen_at": "2026-02-10",
        }
        panel.overview_pos_map = {(1, 1): record}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record)

        emitted = []
        panel.request_prefill.connect(lambda payload: emitted.append(payload))

        panel.on_cell_double_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1, "record_id": 5}], emitted)
        self.assertIn("#16a34a", button.styleSheet())

    def test_overview_double_click_empty_slot_sets_selected_border_and_emits_add_prefill(self):
        panel = self._new_overview_panel()
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])

        panel.overview_pos_map = {}
        button = panel.overview_cells[(1, 1)]
        panel._paint_cell(button, 1, 1, record=None)

        emitted = []
        panel.request_add_prefill.connect(lambda payload: emitted.append(payload))

        panel.on_cell_double_clicked(1, 1)

        self.assertEqual((1, 1), panel.overview_selected_key)
        self.assertEqual([{"box": 1, "position": 1}], emitted)
        self.assertIn("#16a34a", button.styleSheet())

    def test_ai_panel_append_chat_falls_back_when_insert_markdown_missing(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel._append_chat("You", "hello")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("insertPlainText", call_names)

    def test_ai_panel_defaults_model_to_deepseek_chat(self):
        panel = self._new_ai_panel()

        self.assertEqual("deepseek-chat", panel.ai_model.text())

    def test_ai_panel_append_chat_prefers_insert_markdown_when_available(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatWithMarkdown()

        panel._append_chat("Agent", "**bold**")

        call_names = [name for name, _value in panel.ai_chat.calls]
        self.assertIn("insertMarkdown", call_names)

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

    def test_ai_panel_shows_tool_progress_in_chat(self):
        panel = self._new_ai_panel()
        panel.ai_chat = _FakeChatNoMarkdown()

        panel.on_progress({"event": "run_start", "trace_id": "trace-tool"})
        panel.on_progress(
            {
                "event": "tool_start",
                "trace_id": "trace-tool",
                "data": {"name": "query_thaw_events"},
            }
        )
        panel.on_progress(
            {
                "event": "tool_end",
                "trace_id": "trace-tool",
                "step": 1,
                "data": {"name": "query_thaw_events"},
                "observation": {"ok": True},
            }
        )

        text_calls = [value for name, value in panel.ai_chat.calls if name == "insertPlainText"]
        merged = "\n".join(text_calls)
        self.assertIn("Running `query_thaw_events`...", merged)
        self.assertIn("finished: **OK**", merged)

    def test_ai_panel_rewrites_streamed_markdown_on_finish(self):
        panel = self._new_ai_panel()

        panel.on_progress({"event": "run_start", "trace_id": "trace-md"})
        panel.on_progress({"event": "chunk", "trace_id": "trace-md", "data": "**bold**"})
        panel.on_finished({"ok": True, "result": {"final": "**bold**", "trace_id": "trace-md"}})

        rendered_text = panel.ai_chat.toPlainText()
        self.assertIn("bold", rendered_text)
        self.assertNotIn("**bold**", rendered_text)

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


if __name__ == "__main__":
    unittest.main()
