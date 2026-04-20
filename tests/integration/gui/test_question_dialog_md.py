"""
Module: test_question_dialog_md
Layer: integration/gui
Covers: app_gui/ui/ai_panel_runtime._show_question_dialog

Verify that the non-modal agent question dialog renders markdown as rich text.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from app_gui.ui.ai_panel import AIPanel

    PYSIDE_AVAILABLE = True
except Exception:
    PYSIDE_AVAILABLE = False
    Qt = None
    QApplication = None
    QLabel = None
    AIPanel = None

from tests.managed_paths import ManagedPathTestCase


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required for GUI panel tests")
class TestQuestionDialogMarkdown(ManagedPathTestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_ai_panel(self):
        return AIPanel(bridge=object(), yaml_path_getter=lambda: self.fake_yaml_path)

    def test_question_label_uses_rich_text_format(self):
        """The question label should use RichText format so HTML is rendered."""
        panel = self._new_ai_panel()
        options = ["Option A", "Option B", "\u5176\u4ed6\uff1a\u8bf7\u8f93\u5165"]

        md_question = "**Bold question** with `code`"
        dialog = panel._show_question_dialog(md_question, options)
        self._app.processEvents()
        self.assertEqual(Qt.NonModal, dialog.windowModality())
        dialog.reject()
        self._app.processEvents()

    def test_question_label_contains_rendered_html(self):
        """Markdown syntax should be converted to HTML tags in the label."""
        panel = self._new_ai_panel()
        options = ["Yes", "No", "\u5176\u4ed6\uff1a\u8bf7\u8f93\u5165"]

        md_question = "# Title\n\n- item **one**\n- item *two*"
        dialog = panel._show_question_dialog(md_question, options)
        self._app.processEvents()

        rich_labels = [
            label.text()
            for label in dialog.findChildren(QLabel)
            if label.textFormat() == Qt.RichText
        ]

        self.assertTrue(len(rich_labels) > 0, "No RichText label found in dialog")
        html = rich_labels[0]
        self.assertIn("<strong>one</strong>", html)
        self.assertIn("<em>two</em>", html)
        dialog.reject()
        self._app.processEvents()

    def test_question_dialog_uses_readable_min_width_and_wrapping_label(self):
        panel = self._new_ai_panel()
        options = ["Yes", "No", "\u5176\u4ed6\uff1a\u8bf7\u8f93\u5165"]

        dialog = panel._show_question_dialog("A very long question " * 8, options)
        self._app.processEvents()

        rich_labels = [
            label
            for label in dialog.findChildren(QLabel)
            if label.textFormat() == Qt.RichText
        ]
        self.assertGreaterEqual(dialog.minimumWidth(), 560)
        self.assertTrue(rich_labels)
        self.assertTrue(rich_labels[0].wordWrap())

        dialog.reject()
        self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
