"""Integration tests for ActivityIndicator in the AI panel."""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class ActivityIndicatorIntegrationTests(GuiPanelsBaseCase):
    """Verify activity indicator state transitions via AI panel lifecycle."""

    def test_indicator_not_active_on_init(self):
        panel = self._new_ai_panel()
        indicator = panel._activity_indicator
        self.assertFalse(indicator.is_active())

    def test_set_busy_true_activates_indicator(self):
        panel = self._new_ai_panel()
        panel.set_busy(True)
        indicator = panel._activity_indicator
        self.assertTrue(indicator.is_active())

    def test_set_busy_false_deactivates_indicator(self):
        panel = self._new_ai_panel()
        panel.set_busy(True)
        panel.set_busy(False)
        indicator = panel._activity_indicator
        self.assertFalse(indicator.is_active())

    def test_tool_start_updates_indicator_tool_name(self):
        panel = self._new_ai_panel()
        panel.set_busy(True)

        panel.on_progress({"event": "run_start", "trace_id": "trace-test"})
        panel.on_progress({
            "event": "tool_start",
            "trace_id": "trace-test",
            "data": {"name": "search_records"},
        })

        indicator = panel._activity_indicator
        self.assertEqual(indicator._tool_name, "search_records")

    def test_chunk_clears_tool_name_from_indicator(self):
        panel = self._new_ai_panel()
        panel.ai_stream_render_interval_sec = 0.0
        panel.set_busy(True)

        panel.on_progress({"event": "run_start", "trace_id": "trace-test2"})
        panel.on_progress({
            "event": "tool_start",
            "trace_id": "trace-test2",
            "data": {"name": "generate_stats"},
        })
        panel.on_progress({
            "event": "chunk",
            "trace_id": "trace-test2",
            "data": "Hello",
            "meta": {"channel": "answer"},
        })

        indicator = panel._activity_indicator
        self.assertEqual(indicator._tool_name, "")

    def test_elapsed_increases_after_start(self):
        panel = self._new_ai_panel()
        panel.set_busy(True)
        indicator = panel._activity_indicator
        self.assertGreaterEqual(indicator.elapsed_seconds(), 0.0)
        self.assertLess(indicator.elapsed_seconds(), 2.0)

    def test_indicator_start_stop_lifecycle(self):
        panel = self._new_ai_panel()
        indicator = panel._activity_indicator
        indicator.start("Working...")
        self.assertTrue(indicator.is_active())
        indicator.stop()
        self.assertFalse(indicator.is_active())

    def test_set_tool_name_stores_name(self):
        panel = self._new_ai_panel()
        indicator = panel._activity_indicator
        indicator.start()
        indicator.set_tool_name("rollback")
        self.assertEqual(indicator._tool_name, "rollback")

    def test_set_tool_name_empty_resets(self):
        panel = self._new_ai_panel()
        indicator = panel._activity_indicator
        indicator.start()
        indicator.set_tool_name("search_records")
        indicator.set_tool_name("")
        self.assertEqual(indicator._tool_name, "")
