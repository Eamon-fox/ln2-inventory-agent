from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_gui.i18n import tr
from app_gui.ui.dialogs.common import create_message_box, show_info_message, show_warning_message


def build_preferences_group(dialog, *, combo_box_cls) -> QGroupBox:
    from app_gui.i18n import SUPPORTED_LANGUAGES

    preferences_group = QGroupBox(tr("settings.preferences"))
    preferences_layout = QFormLayout(preferences_group)

    prefs_row = QWidget()
    row_layout = QHBoxLayout(prefs_row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(12)

    lang_label = QLabel(tr("settings.language"))
    lang_label.setProperty("role", "inlineFormLabel")
    row_layout.addWidget(lang_label)

    dialog.lang_combo = combo_box_cls()
    for code, name in SUPPORTED_LANGUAGES.items():
        dialog.lang_combo.addItem(name, code)
    current_lang = dialog._config.get("language", "en")
    idx = dialog.lang_combo.findData(current_lang)
    if idx >= 0:
        dialog.lang_combo.setCurrentIndex(idx)
    dialog.lang_combo.currentIndexChanged.connect(dialog._refresh_local_api_skill_template)
    row_layout.addWidget(dialog.lang_combo)

    theme_label = QLabel(tr("settings.theme"))
    theme_label.setProperty("role", "inlineFormLabel")
    row_layout.addWidget(theme_label)

    dialog.theme_combo = combo_box_cls()
    dialog.theme_combo.addItem(tr("settings.themeAuto"), "auto")
    dialog.theme_combo.addItem(tr("settings.themeDark"), "dark")
    dialog.theme_combo.addItem(tr("settings.themeLight"), "light")
    current_theme = dialog._config.get("theme", "dark")
    idx = dialog.theme_combo.findData(current_theme)
    if idx >= 0:
        dialog.theme_combo.setCurrentIndex(idx)
    row_layout.addWidget(dialog.theme_combo)

    scale_label = QLabel(tr("settings.uiScale"))
    scale_label.setProperty("role", "inlineFormLabel")
    row_layout.addWidget(scale_label)

    dialog.scale_combo = combo_box_cls()
    dialog.scale_combo.addItem("100%", 1.0)
    dialog.scale_combo.addItem("125%", 1.25)
    dialog.scale_combo.addItem("150%", 1.5)
    current_scale = dialog._config.get("ui_scale", 1.0)
    if current_scale > 1.5:
        current_scale = 1.5
    idx = dialog.scale_combo.findData(current_scale)
    if idx >= 0:
        dialog.scale_combo.setCurrentIndex(idx)
    row_layout.addWidget(dialog.scale_combo)

    row_layout.addStretch()
    preferences_layout.addRow(prefs_row)
    return preferences_group


def start_check_update(dialog) -> None:
    dialog._check_update_btn.setEnabled(False)
    dialog._check_update_btn.setText(tr("settings.checking"))

    import threading

    def _fetch():
        try:
            import json
            import urllib.request

            req = urllib.request.Request(
                dialog._github_api_latest,
                headers={"User-Agent": "SnowFox"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            latest_tag = str(data.get("version", "")).strip()
            body = str(data.get("release_notes", ""))[:200]
            release_info = dialog._resolve_platform_release_info(data)
            download_url = str(release_info.get("download_url", ""))
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG

            QMetaObject.invokeMethod(
                dialog,
                "_on_check_update_result",
                Qt.QueuedConnection,
                Q_ARG(str, latest_tag),
                Q_ARG(str, body),
                Q_ARG(str, download_url),
            )
        except Exception as exc:
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG

            QMetaObject.invokeMethod(
                dialog,
                "_on_check_update_result",
                Qt.QueuedConnection,
                Q_ARG(str, ""),
                Q_ARG(str, str(exc)),
                Q_ARG(str, ""),
            )

    threading.Thread(target=_fetch, daemon=True).start()


def handle_check_update_result(dialog, latest_tag, info, download_url) -> None:
    dialog._check_update_btn.setEnabled(True)
    dialog._check_update_btn.setText(tr("settings.checkUpdate"))
    if not latest_tag:
        from app_gui.i18n import t

        show_warning_message(
            dialog,
            title=tr("settings.checkUpdate"),
            text=t("settings.checkUpdateFailed", error=info),
        )
        return
    if dialog._is_version_newer(latest_tag, dialog._app_version):
        release_info = dialog._resolve_platform_release_info({"download_url": download_url})
        update_label = (
            tr("main.newReleaseUpdate")
            if bool(release_info.get("auto_update"))
            else tr("main.newReleaseDownload")
        )
        release_notes = str(info or "").strip()
        if not release_notes:
            release_notes = tr("main.releaseNotesDefault")

        box = create_message_box(
            dialog,
            title=tr("settings.checkUpdate"),
            text=tr("main.newReleaseHeadline", version=latest_tag),
            informative_text=tr("main.newReleaseBackupWarning"),
            detailed_text=release_notes,
            icon=QMessageBox.Information,
        )
        update_btn = box.addButton(update_label, QMessageBox.AcceptRole)
        box.addButton(tr("main.newReleaseLater"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == update_btn:
            main_window = dialog.parent()
            if hasattr(main_window, "_startup_flow"):
                dialog.close()
                main_window._startup_flow.start_automatic_update(latest_tag, info, download_url)
        return

    show_info_message(
        dialog,
        title=tr("settings.checkUpdate"),
        text=tr("settings.alreadyLatest"),
    )


def build_about_group(dialog) -> QGroupBox:
    about_group = QGroupBox(tr("settings.about"))
    about_layout = QVBoxLayout(about_group)
    about_label = QLabel(
        f'{tr("app.title")}  v{dialog._app_version}<br>'
        f'{tr("settings.aboutDesc")}<br><br>'
        f'{tr("settings.downloadPageLabel")}: <a href="{dialog._app_release_url}">'
        f'SnowFox</a>'
    )
    about_label.setOpenExternalLinks(True)
    about_label.setWordWrap(True)
    about_label.setObjectName("settingsAboutLabel")
    about_layout.addWidget(about_label)

    dialog._check_update_btn = QPushButton(tr("settings.checkUpdate"))
    dialog._check_update_btn.setMinimumWidth(140)
    dialog._check_update_btn.clicked.connect(dialog._on_check_update)
    about_layout.addWidget(dialog._check_update_btn)

    donate_path = os.path.join(dialog._root_dir, "app_gui", "assets", "donate.png")
    if os.path.isfile(donate_path):
        from PySide6.QtGui import QPixmap

        donate_vbox = QVBoxLayout()
        donate_vbox.setAlignment(Qt.AlignCenter)
        donate_text = QLabel(tr("settings.supportHint"))
        donate_text.setObjectName("settingsSupportLabel")
        donate_text.setAlignment(Qt.AlignCenter)
        donate_pixmap = QPixmap(donate_path)
        donate_img = QLabel()
        donate_scaled = donate_pixmap.scaledToWidth(380, Qt.SmoothTransformation)
        donate_img.setPixmap(donate_scaled)
        donate_img.setFixedSize(donate_scaled.size())
        donate_img.setAlignment(Qt.AlignCenter)
        donate_vbox.addWidget(donate_text, alignment=Qt.AlignCenter)
        donate_vbox.addWidget(donate_img, alignment=Qt.AlignCenter)
        about_layout.addLayout(donate_vbox)

    return about_group
