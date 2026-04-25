from __future__ import annotations

import os
import threading

from PySide6.QtCore import Q_ARG, QMetaObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app_gui.application.feedback_reporter import (
    FEEDBACK_ENDPOINT_URL,
    FEEDBACK_TIMEOUT_SECONDS,
    post_feedback,
)
from app_gui.i18n import tr
from app_gui.ui.icons import Icons, get_icon

QQ_GROUP_ID = "471436975"
SUPPORT_EMAIL = "fym22@mails.tsinghua.edu.cn"


class ClickableImageLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


def _feedback_qr_path(dialog) -> str:
    return os.path.join(dialog._root_dir, "app_gui", "assets", "qq-group-qrcode.png")


def build_feedback_group(dialog, *, plain_text_edit_cls) -> QGroupBox:
    feedback_group = QGroupBox(tr("settings.feedbackSupport"))
    layout = QVBoxLayout(feedback_group)
    layout.setSpacing(8)

    intro = QLabel(tr("settings.feedbackSupportHint"))
    intro.setProperty("role", "hint")
    intro.setWordWrap(True)
    layout.addWidget(intro)

    contact_row = QHBoxLayout()
    contact_row.setSpacing(14)

    contact_lines = QVBoxLayout()
    contact_lines.setContentsMargins(0, 0, 0, 0)
    contact_lines.setSpacing(4)

    email_row = QHBoxLayout()
    email_row.setContentsMargins(0, 0, 0, 0)
    email_row.setSpacing(4)
    email_label = QLabel(f"{tr('settings.feedbackEmail')}: {SUPPORT_EMAIL}")
    email_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    email_row.addWidget(email_label, 0, Qt.AlignVCenter)
    dialog.feedback_email_copy_btn = _build_inline_copy_button(
        tooltip=tr("settings.feedbackCopyEmailTooltip"),
        object_name="feedbackEmailCopyButton",
    )
    dialog.feedback_email_copy_btn.clicked.connect(dialog._copy_feedback_email)
    email_row.addWidget(dialog.feedback_email_copy_btn, 0, Qt.AlignVCenter)
    email_row.addStretch(1)
    contact_lines.addLayout(email_row)

    qq_row = QHBoxLayout()
    qq_row.setContentsMargins(0, 0, 0, 0)
    qq_row.setSpacing(4)
    qq_label = QLabel(f"{tr('settings.feedbackQQGroup')}: {QQ_GROUP_ID}")
    qq_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    qq_row.addWidget(qq_label, 0, Qt.AlignVCenter)
    dialog.feedback_qq_copy_btn = _build_inline_copy_button(
        tooltip=tr("settings.feedbackCopyQQTooltip"),
        object_name="feedbackQqCopyButton",
    )
    dialog.feedback_qq_copy_btn.clicked.connect(dialog._copy_feedback_qq_group)
    qq_row.addWidget(dialog.feedback_qq_copy_btn, 0, Qt.AlignVCenter)
    qq_row.addStretch(1)
    contact_lines.addLayout(qq_row)

    contact_row.addLayout(contact_lines, 1)

    qr_path = _feedback_qr_path(dialog)
    if os.path.isfile(qr_path):
        dialog.feedback_qr_path = qr_path
        pixmap = QPixmap(qr_path)
        qr_label = ClickableImageLabel()
        qr_label.setObjectName("settingsFeedbackQr")
        qr_label.setToolTip(tr("settings.feedbackQrTooltip"))
        qr_label.setCursor(Qt.PointingHandCursor)
        scaled = pixmap.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        qr_label.setPixmap(scaled)
        qr_label.setFixedSize(scaled.size())
        qr_label.clicked.connect(dialog._show_feedback_qr_popup)
        contact_row.addWidget(qr_label, 0, Qt.AlignTop)

    layout.addLayout(contact_row)

    dialog.feedback_edit = plain_text_edit_cls()
    dialog.feedback_edit.setPlaceholderText(tr("settings.feedbackPlaceholder"))
    dialog.feedback_edit.setFixedHeight(76)
    layout.addWidget(dialog.feedback_edit)

    submit_row = QHBoxLayout()
    submit_row.setContentsMargins(0, 0, 0, 0)
    dialog.feedback_status_label = QLabel("")
    dialog.feedback_status_label.setProperty("role", "hint")
    dialog.feedback_status_label.setWordWrap(True)
    submit_row.addWidget(dialog.feedback_status_label, 1)

    dialog.feedback_submit_btn = QPushButton(tr("settings.feedbackSubmit"))
    dialog.feedback_submit_btn.clicked.connect(dialog._submit_feedback)
    submit_row.addWidget(dialog.feedback_submit_btn)
    layout.addLayout(submit_row)

    dialog._feedback_endpoint = FEEDBACK_ENDPOINT_URL
    return feedback_group


def _build_inline_copy_button(*, tooltip: str, object_name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName(object_name)
    button.setIcon(get_icon(Icons.COPY, size=14))
    button.setIconSize(QSize(14, 14))
    button.setFixedSize(22, 22)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


def _flash_copied_state(button: QPushButton | None) -> None:
    if button is None:
        return
    tooltip = button.toolTip()
    button.setIcon(get_icon(Icons.CHECK, size=14))
    button.setToolTip(tr("settings.feedbackCopiedTooltip"))

    def _reset() -> None:
        button.setIcon(get_icon(Icons.COPY, size=14))
        button.setToolTip(tooltip)

    QTimer.singleShot(1200, _reset)


def copy_feedback_email(dialog) -> None:
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(SUPPORT_EMAIL)
    _flash_copied_state(getattr(dialog, "feedback_email_copy_btn", None))
    if hasattr(dialog, "feedback_status_label"):
        dialog.feedback_status_label.setText(tr("settings.feedbackEmailCopied"))


def copy_feedback_qq_group(dialog) -> None:
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(QQ_GROUP_ID)
    _flash_copied_state(getattr(dialog, "feedback_qq_copy_btn", None))
    if hasattr(dialog, "feedback_status_label"):
        dialog.feedback_status_label.setText(tr("settings.feedbackQQCopied"))


def show_feedback_qr_popup(dialog) -> None:
    qr_path = getattr(dialog, "feedback_qr_path", "")
    if not qr_path or not os.path.isfile(qr_path):
        return

    popup = QDialog(dialog)
    popup.setWindowTitle(tr("settings.feedbackQrTitle"))
    popup_layout = QVBoxLayout(popup)
    qr_label = QLabel()
    pixmap = QPixmap(qr_path)
    scaled = pixmap.scaled(360, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    qr_label.setPixmap(scaled)
    qr_label.setAlignment(Qt.AlignCenter)
    popup_layout.addWidget(qr_label)
    group_label = QLabel(f"{tr('settings.feedbackQQGroup')}: {QQ_GROUP_ID}")
    group_label.setAlignment(Qt.AlignCenter)
    popup_layout.addWidget(group_label)
    popup.exec()


def submit_feedback(dialog) -> None:
    message = dialog.feedback_edit.toPlainText().strip()
    if not message:
        dialog.feedback_status_label.setText(tr("settings.feedbackEmpty"))
        return

    dialog.feedback_submit_btn.setEnabled(False)
    dialog.feedback_submit_btn.setText(tr("settings.feedbackSending"))
    dialog.feedback_status_label.setText("")
    endpoint = getattr(dialog, "_feedback_endpoint", FEEDBACK_ENDPOINT_URL)
    app_version = getattr(dialog, "_app_version", "")
    language = ""
    if hasattr(dialog, "lang_combo"):
        language = dialog.lang_combo.currentData() or ""

    def _worker() -> None:
        result = post_feedback(
            message,
            endpoint=endpoint,
            timeout=FEEDBACK_TIMEOUT_SECONDS,
            app_version=app_version,
            language=language,
        )
        status = "ok" if result.get("ok") else "error"
        detail = str(result.get("error_code") or "")
        QMetaObject.invokeMethod(
            dialog,
            "_on_feedback_submission_result",
            Qt.QueuedConnection,
            Q_ARG(str, status),
            Q_ARG(str, detail),
        )

    threading.Thread(target=_worker, name="snowfox-feedback-submit", daemon=True).start()


def handle_feedback_submission_result(dialog, status: str, detail: str) -> None:
    dialog.feedback_submit_btn.setEnabled(True)
    dialog.feedback_submit_btn.setText(tr("settings.feedbackSubmit"))
    if status == "ok":
        dialog.feedback_edit.clear()
        dialog.feedback_status_label.setText(tr("settings.feedbackSuccess"))
        return
    if detail:
        dialog.feedback_status_label.setText(tr("settings.feedbackFailedWithError", error=detail))
    else:
        dialog.feedback_status_label.setText(tr("settings.feedbackFailed"))
