from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from app_gui.application.open_api.contracts import LOCAL_OPEN_API_DEFAULT_PORT
from app_gui.application.open_api.skill_template import render_local_api_skill_template
from app_gui.i18n import get_language, tr
from app_gui.ui.dialogs.settings_dialog_info import info_label


def build_local_api_group(dialog, *, spin_box_cls, plain_text_edit_cls) -> QGroupBox:
    local_api_group = QGroupBox(tr("settings.localApi"))
    local_api_layout = QFormLayout(local_api_group)

    open_api_cfg = dialog._config.get("open_api", {})
    dialog.open_api_enabled = dialog._checkbox_cls()
    dialog.open_api_enabled.setChecked(bool(open_api_cfg.get("enabled", False)))
    local_api_layout.addRow(
        info_label(tr("settings.localApiEnabled"), tr("settings.localApiHint")),
        dialog.open_api_enabled,
    )

    dialog.open_api_port = spin_box_cls()
    dialog.open_api_port.setRange(1024, 65535)
    try:
        open_api_port = int(open_api_cfg.get("port", LOCAL_OPEN_API_DEFAULT_PORT))
    except Exception:
        open_api_port = LOCAL_OPEN_API_DEFAULT_PORT
    if open_api_port <= 0:
        open_api_port = LOCAL_OPEN_API_DEFAULT_PORT
    dialog.open_api_port.setValue(open_api_port)
    local_api_layout.addRow(tr("settings.localApiPort"), dialog.open_api_port)

    local_api_skill_row = QWidget()
    local_api_skill_row_layout = QHBoxLayout(local_api_skill_row)
    local_api_skill_row_layout.setContentsMargins(0, 0, 0, 0)
    local_api_skill_row_layout.setSpacing(8)

    dialog.local_api_skill_template_edit = plain_text_edit_cls()
    dialog.local_api_skill_template_edit.setObjectName("localApiSkillTemplateEdit")
    dialog.local_api_skill_template_edit.setReadOnly(True)
    dialog.local_api_skill_template_edit.setMinimumHeight(120)
    dialog.local_api_skill_template_edit.setMaximumHeight(160)
    dialog.local_api_skill_template_edit.setFocusPolicy(Qt.WheelFocus)
    dialog.local_api_skill_template_edit.verticalScrollBar().setSingleStep(18)
    dialog.local_api_skill_template_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
    local_api_skill_row_layout.addWidget(dialog.local_api_skill_template_edit, 1)

    dialog.local_api_skill_copy_btn = QPushButton(tr("settings.localApiSkillCopy"))
    dialog.local_api_skill_copy_btn.setObjectName("localApiSkillCopyButton")
    dialog.local_api_skill_copy_btn.clicked.connect(dialog._copy_local_api_skill_template)
    local_api_skill_row_layout.addWidget(dialog.local_api_skill_copy_btn, 0, Qt.AlignTop)

    local_api_layout.addRow(
        info_label(tr("settings.localApiSkillTemplate"), tr("settings.localApiSkillTemplateHint")),
        local_api_skill_row,
    )
    return local_api_group


def current_template_language(dialog) -> str:
    combo = getattr(dialog, "lang_combo", None)
    if combo is not None:
        selected = str(combo.currentData() or "").strip()
        if selected:
            return selected
    configured = str(dialog._config.get("language") or "").strip()
    if configured:
        return configured
    return str(get_language() or "en").strip() or "en"


def resolve_local_api_skill_template_text(dialog, language: str) -> tuple[str, bool]:
    assets_root = os.path.join(dialog._root_dir, "app_gui", "assets")
    normalized = str(language or "").strip() or "en"
    candidates = []
    if normalized:
        candidates.append(normalized)
    if "en" not in candidates:
        candidates.append("en")

    for candidate in candidates:
        path = os.path.join(assets_root, f"local_api_skill_template.{candidate}.md")
        text = dialog._read_bundled_text_file(path)
        if text:
            return render_local_api_skill_template(text, language=normalized), True
    return tr("settings.localApiSkillTemplateUnavailable"), False


@Slot()
@Slot(int)
def refresh_local_api_skill_template(dialog, *_args) -> None:
    text, available = resolve_local_api_skill_template_text(dialog, current_template_language(dialog))
    dialog.local_api_skill_template_edit.setPlainText(text)
    dialog.local_api_skill_copy_btn.setEnabled(bool(available))
    reset_local_api_skill_copy_button_text(dialog)


@Slot()
def reset_local_api_skill_copy_button_text(dialog) -> None:
    dialog.local_api_skill_copy_btn.setText(tr("settings.localApiSkillCopy"))


@Slot()
def copy_local_api_skill_template(dialog) -> None:
    if not dialog.local_api_skill_copy_btn.isEnabled():
        return
    QApplication.clipboard().setText(dialog.local_api_skill_template_edit.toPlainText())
    dialog.local_api_skill_copy_btn.setText(tr("settings.localApiSkillCopied"))
    QTimer.singleShot(
        int(dialog._local_api_skill_copy_reset_ms),
        lambda: reset_local_api_skill_copy_button_text(dialog),
    )
