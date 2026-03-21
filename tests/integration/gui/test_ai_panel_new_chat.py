"""
Module: test_ai_panel_new_chat
Layer: integration/gui
Covers: app_gui/ui/ai_panel.py — New Chat button integration

Verify the New Chat button clears both UI display and agent context,
and shows a confirmation dialog when history is non-empty.
"""

from tests.integration.gui._gui_panels_shared import *  # noqa: F401,F403
from unittest.mock import patch


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class TestNewChatButtonIntegration(GuiPanelsBaseCase):

    def test_new_chat_clears_display_and_context(self):
        """New Chat should clear both the chat widget and agent context."""
        panel = self._new_ai_panel()

        # Simulate some conversation state
        panel._append_chat("You", "What is in box 1?")
        panel._append_history("user", "What is in box 1?")
        panel._append_chat("Agent", "Box 1 has 5 samples.")
        panel._append_history("assistant", "Box 1 has 5 samples.")
        panel.ai_operation_events = [{"type": "plan_staged", "data": {}}]
        panel.ai_summary_state = {"checkpoint_id": "checkpoint-1", "summary_text": "summary"}

        self.assertTrue(len(panel.ai_history) > 0)
        self.assertTrue(len(panel.ai_operation_events) > 0)
        self.assertTrue(len(panel.ai_chat.toPlainText().strip()) > 0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            panel.on_new_chat()

        # Both UI and context should be cleared
        self.assertEqual(panel.ai_history, [])
        self.assertEqual(panel.ai_operation_events, [])
        self.assertIsNone(panel.ai_summary_state)
        self.assertEqual(panel.ai_chat.toPlainText().strip(), "")

    def test_new_chat_cancelled_preserves_state(self):
        """Declining the confirmation should preserve all state."""
        panel = self._new_ai_panel()

        panel._append_chat("You", "hello")
        panel._append_history("user", "hello")
        original_history = list(panel.ai_history)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            panel.on_new_chat()

        self.assertEqual(panel.ai_history, original_history)
        self.assertIn("hello", panel.ai_chat.toPlainText())

    def test_new_chat_no_confirm_when_empty(self):
        """No confirmation dialog when chat is already empty."""
        panel = self._new_ai_panel()

        with patch.object(QMessageBox, "question") as mock_q:
            panel.on_new_chat()
            mock_q.assert_not_called()

    def test_new_chat_button_exists_with_correct_label(self):
        """The new chat button should exist with the correct i18n label."""
        panel = self._new_ai_panel()

        # Find the button by its connected slot
        from PySide6.QtWidgets import QPushButton

        new_chat_btn = None
        for child in panel.findChildren(QPushButton):
            if child.text() == tr("ai.newChat"):
                new_chat_btn = child
                break

        self.assertIsNotNone(new_chat_btn, "New Chat button should exist")
