"""Unit tests for shared GUI dialog helpers."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

    from app_gui.ui.dialogs.common import create_message_box

    PYSIDE_AVAILABLE = True
except Exception:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 required")
class DialogCommonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_message_box_does_not_expand_icon_label_to_text_width(self):
        box = create_message_box(
            None,
            title="Info",
            text="This is a long enough body to trigger wrapping rules.",
            icon=QMessageBox.Information,
        )

        icon_label = None
        text_label = None
        for label in box.findChildren(QLabel):
            pixmap = label.pixmap()
            if pixmap is not None and not pixmap.isNull():
                icon_label = label
            elif str(label.text() or "").strip():
                text_label = label

        self.assertIsNotNone(icon_label)
        self.assertIsNotNone(text_label)
        self.assertLess(icon_label.minimumWidth(), 100)
        self.assertGreaterEqual(text_label.minimumWidth(), 100)


if __name__ == "__main__":
    unittest.main()
