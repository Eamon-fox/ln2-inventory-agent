"""Help dialog for support, feedback, and product information."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from app_gui.i18n import tr
from app_gui.ui.dialogs import settings_dialog_about_section as _about_section
from app_gui.ui.dialogs import settings_dialog_feedback_section as _feedback_section
from app_gui.version import (
    APP_RELEASE_URL,
    APP_VERSION,
    UPDATE_CHECK_URL,
    is_version_newer,
    resolve_platform_release_info,
)

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


class _NoWheelPlainTextEdit(QPlainTextEdit):
    """Scroll parent unless this editor is actively focused."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class HelpDialog(QDialog):
    """Compact help surface split out from Settings."""

    def __init__(
        self,
        parent=None,
        *,
        app_version=APP_VERSION,
        app_release_url=APP_RELEASE_URL,
        github_api_latest=UPDATE_CHECK_URL,
        root_dir=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("help.title"))
        self.setMinimumWidth(620)
        self.setMinimumHeight(560)
        self._app_version = str(app_version or APP_VERSION)
        self._app_release_url = str(app_release_url or APP_RELEASE_URL)
        self._github_api_latest = str(github_api_latest or UPDATE_CHECK_URL)
        self._root_dir = root_dir or ROOT
        self._is_version_newer = is_version_newer
        self._resolve_platform_release_info = resolve_platform_release_info

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        content_layout.addWidget(
            _feedback_section.build_feedback_group(
                self,
                plain_text_edit_cls=_NoWheelPlainTextEdit,
            )
        )
        content_layout.addWidget(_about_section.build_about_group(self))
        content_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn = buttons.button(QDialogButtonBox.Close)
        if close_btn is not None:
            close_btn.setText(tr("common.close"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_check_update(self):
        _about_section.start_check_update(self)

    @Slot(str, str, str)
    def _on_check_update_result(self, latest_tag, info, download_url):
        _about_section.handle_check_update_result(self, latest_tag, info, download_url)

    def _copy_feedback_qq_group(self):
        _feedback_section.copy_feedback_qq_group(self)

    def _copy_feedback_email(self):
        _feedback_section.copy_feedback_email(self)

    def _show_feedback_qr_popup(self):
        _feedback_section.show_feedback_qr_popup(self)

    def _submit_feedback(self):
        _feedback_section.submit_feedback(self)

    @Slot(str, str)
    def _on_feedback_submission_result(self, status, detail):
        _feedback_section.handle_feedback_submission_result(self, status, detail)


__all__ = ["HelpDialog"]
