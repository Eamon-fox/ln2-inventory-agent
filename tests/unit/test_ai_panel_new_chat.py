"""
Module: test_ai_panel_new_chat
Layer: unit
Covers: app_gui/ui/ai_panel.py — on_new_chat context reset logic

Verify that on_new_chat resets both UI display state and agent context
(ai_history, ai_operation_events).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app_gui.ui.ai_panel import AIPanel

    PYSIDE_AVAILABLE = True
except Exception:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 required")
class TestOnNewChatContextReset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _make_panel(self):
        return AIPanel(bridge=object(), yaml_path_getter=lambda: "/tmp/fake.yaml")

    def test_resets_ai_history(self):
        panel = self._make_panel()
        panel.ai_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # Bypass confirmation dialog by having empty state appear non-empty
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            panel.on_new_chat()
        self.assertEqual(panel.ai_history, [])

    def test_resets_ai_operation_events(self):
        panel = self._make_panel()
        panel.ai_operation_events = [{"type": "plan_staged", "data": {}}]
        panel.ai_history = [{"role": "user", "content": "x"}]
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            panel.on_new_chat()
        self.assertEqual(panel.ai_operation_events, [])

    def test_resets_streaming_state(self):
        panel = self._make_panel()
        panel.ai_history = [{"role": "user", "content": "x"}]
        panel.ai_streaming_active = True
        panel.ai_stream_buffer = "partial content"
        panel.ai_active_trace_id = "trace-123"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            panel.on_new_chat()
        self.assertFalse(panel.ai_streaming_active)
        self.assertEqual(panel.ai_stream_buffer, "")
        self.assertIsNone(panel.ai_active_trace_id)

    def test_confirmation_declined_keeps_state(self):
        panel = self._make_panel()
        panel.ai_history = [
            {"role": "user", "content": "hello"},
        ]
        original_history = list(panel.ai_history)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            panel.on_new_chat()
        self.assertEqual(panel.ai_history, original_history)

    def test_skips_confirmation_when_empty(self):
        panel = self._make_panel()
        panel.ai_history = []
        panel.ai_chat.clear()
        # Should not show dialog, just execute
        with patch.object(QMessageBox, "question") as mock_q:
            panel.on_new_chat()
            mock_q.assert_not_called()
        self.assertEqual(panel.ai_history, [])


if __name__ == "__main__":
    unittest.main()
