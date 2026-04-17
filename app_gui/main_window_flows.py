"""Extracted workflows for MainWindow to reduce UI-class bloat."""

from contextlib import suppress
import os
import subprocess
import sys
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app_gui.application import DatasetLifecycleUseCase
from app_gui.application.ai_provider_catalog import (
    default_ai_model,
    normalize_ai_provider,
)
from app_gui.application.manage_boxes_flow import ManageBoxesFlow as _ManageBoxesFlowImpl
from app_gui.gui_config import DEFAULT_MAX_STEPS, save_gui_config
from app_gui.i18n import t, tr
from app_gui.ui.dialogs.manage_boxes_dialog import ManageBoxesDialog
from app_gui.version import current_release_platform, resolve_platform_release_info
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.yaml_ops import load_yaml


def _submission_value(values, key, default=None):
    if isinstance(values, dict):
        return values.get(key, default)
    return getattr(values, key, default)


class StartupFlow:
    """Startup checks and update/import prompts extracted from MainWindow."""

    def __init__(
        self,
        window,
        *,
        app_version,
        release_url,
        github_api_latest,
        is_version_newer: Callable[[str, str], bool],
        show_nonblocking_dialog: Callable,
        start_import_journey: Callable,
    ):
        self._window = window
        self._app_version = str(app_version)
        self._release_url = str(release_url)
        self._github_api_latest = str(github_api_latest)
        self._is_version_newer = is_version_newer
        self._show_nonblocking_dialog = show_nonblocking_dialog
        self._start_import_journey = start_import_journey

    def _build_message_box(self, *, title, text, icon):
        box = QMessageBox(self._window)
        box.setWindowTitle(str(title or ""))
        box.setText(str(text or ""))
        box.setIcon(icon)
        return box

    def _show_status_box(self, title, text, icon):
        self._build_message_box(title=title, text=text, icon=icon).exec()

    def _persist_gui_config_once(self, key, value):
        window = self._window
        if window.gui_config.get(key) == value:
            return
        window.gui_config[key] = value
        save_gui_config(window.gui_config)

    def check_release_notice_once(self):
        """Fetch latest release info from OSS and notify if newer."""
        import threading

        window = self._window

        def _fetch_and_notify():
            try:
                import json
                import urllib.request
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG

                req = urllib.request.Request(
                    self._github_api_latest,
                    headers={"User-Agent": "SnowFox"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = str(data.get("version", "")).strip()
                if not latest_tag or not self._is_version_newer(latest_tag, self._app_version):
                    return
                last_notified = window.gui_config.get("last_notified_release", "0.0.0")
                if not self._is_version_newer(latest_tag, last_notified):
                    return
                body = str(data.get("release_notes", ""))
                release_info = resolve_platform_release_info(data)
                download_url = str(release_info.get("download_url", ""))
                QMetaObject.invokeMethod(
                    window,
                    "_show_update_dialog",
                    Qt.QueuedConnection,
                    Q_ARG(str, latest_tag),
                    Q_ARG(str, body),
                    Q_ARG(str, download_url),
                )
            except Exception as exc:
                print("[VersionCheck] %s" % exc)

        threading.Thread(target=_fetch_and_notify, daemon=True).start()

    def show_update_dialog(self, latest_tag, release_notes, download_url=""):
        """Show update notification dialog in main thread."""
        try:
            from PySide6.QtWidgets import (
                QHBoxLayout,
                QLabel,
                QPushButton,
                QTextBrowser,
                QVBoxLayout,
            )

            title = tr("main.newReleaseTitle")
            headline = t("main.newReleaseHeadline", version=latest_tag)
            notes_text = release_notes or tr("main.releaseNotesDefault")
            backup_warning = tr("main.newReleaseBackupWarning")

            dialog = QDialog(self._window)
            dialog.setWindowTitle(title)
            dialog.resize(560, 460)

            layout = QVBoxLayout(dialog)

            headline_label = QLabel(headline, dialog)
            headline_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            headline_label.setWordWrap(True)
            layout.addWidget(headline_label)

            notes_view = QTextBrowser(dialog)
            notes_view.setPlainText(notes_text)
            notes_view.setOpenExternalLinks(True)
            notes_view.setMinimumHeight(220)
            layout.addWidget(notes_view, 1)

            warning_label = QLabel(backup_warning, dialog)
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

            release_info = resolve_platform_release_info({"download_url": download_url})
            update_label = (
                tr("main.newReleaseUpdate")
                if bool(release_info.get("auto_update"))
                else tr("main.newReleaseDownload")
            )

            button_row = QHBoxLayout()
            button_row.addStretch(1)
            update_btn = QPushButton(update_label, dialog)
            copy_btn = QPushButton(tr("main.newReleaseCopy"), dialog)
            open_btn = QPushButton(tr("main.newReleaseOpen"), dialog)
            later_btn = QPushButton(tr("main.newReleaseLater"), dialog)
            update_btn.setDefault(True)
            update_btn.setAutoDefault(True)
            button_row.addWidget(update_btn)
            button_row.addWidget(copy_btn)
            button_row.addWidget(open_btn)
            button_row.addWidget(later_btn)
            layout.addLayout(button_row)

            def _mark_notified_once():
                self._persist_gui_config_once("last_notified_release", latest_tag)

            def _on_update():
                dialog.accept()
                self.start_automatic_update(latest_tag, release_notes, download_url)

            def _on_copy():
                try:
                    QApplication.clipboard().setText(self._release_url)
                except Exception as exc:
                    print("[VersionCheck] Copy to clipboard failed: %s" % exc)

            def _on_open():
                try:
                    from PySide6.QtCore import QUrl
                    from PySide6.QtGui import QDesktopServices

                    QDesktopServices.openUrl(QUrl(self._release_url))
                except Exception as exc:
                    print("[VersionCheck] Open URL failed: %s" % exc)

            update_btn.clicked.connect(_on_update)
            copy_btn.clicked.connect(_on_copy)
            open_btn.clicked.connect(_on_open)
            later_btn.clicked.connect(dialog.reject)
            dialog.finished.connect(lambda _result: _mark_notified_once())
            self._show_nonblocking_dialog(dialog)
        except Exception as exc:
            print("[VersionCheck] Dialog failed: %s" % exc)

    def _confirm_macos_update(self) -> bool:
        """Warn the user that the unsigned macOS update cannot auto-relaunch.

        Returns True when the user clicks Continue, False on Cancel.
        """
        box = self._build_message_box(
            title=tr("main.macosUpdatePreInstallTitle"),
            text=tr("main.macosUpdatePreInstallMessage"),
            icon=QMessageBox.Warning,
        )
        continue_btn = box.addButton(
            tr("main.macosUpdatePreInstallContinue"),
            QMessageBox.AcceptRole,
        )
        box.addButton(tr("common.cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(continue_btn)
        box.exec()
        return box.clickedButton() is continue_btn

    def start_automatic_update(self, latest_tag, release_notes, download_url=""):
        """Run automatic update with progress dialog."""
        release_info = resolve_platform_release_info({"download_url": download_url})
        package_url = str(release_info.get("download_url", "")).strip()
        target_url = package_url or self._release_url
        platform_key = str(release_info.get("platform_key") or current_release_platform())
        is_macos = platform_key == "macos"

        if not bool(release_info.get("auto_update")):
            try:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not target_url:
                    raise RuntimeError(tr("main.updateManualNoUrl"))
                QDesktopServices.openUrl(QUrl(target_url))
                if is_macos:
                    manual_message = tr("main.updateManualMessageMacos")
                else:
                    manual_message = t(
                        "main.updateManualMessage",
                        platform=str(release_info.get("platform_name", "")),
                    )
                self._show_status_box(
                    tr("main.updateManualTitle"),
                    manual_message,
                    QMessageBox.Information,
                )
            except Exception as exc:
                self._show_status_box(tr("main.updateFailed"), str(exc), QMessageBox.Warning)
            return

        if is_macos and not self._confirm_macos_update():
            return

        if not package_url:
            self._show_status_box(
                tr("main.updateFailed"),
                tr("main.updateManualNoUrl"),
                QMessageBox.Warning,
            )
            return

        from PySide6.QtCore import Qt, QObject, Signal
        from PySide6.QtWidgets import QApplication, QProgressDialog

        from app_gui.auto_updater import AutoUpdater

        window = self._window
        progress = QProgressDialog(window)
        progress.setWindowTitle(tr("main.updatingTitle"))
        progress.setLabelText("Initializing...")
        progress.setRange(0, 100)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.show()

        # Signal bridge: marshal callbacks from download thread → main thread
        class _UpdateBridge(QObject):
            sig_progress = Signal(int, str)
            sig_complete = Signal(bool, str)
            sig_error = Signal(str)

        bridge = _UpdateBridge(parent=window)

        def _on_progress(progress_value, message):
            progress.setValue(progress_value)
            progress.setLabelText(message)

        def _on_complete(success, message):
            progress.close()
            if success:
                if is_macos:
                    self._show_status_box(
                        tr("main.updateComplete"),
                        tr("main.macosUpdatePostInstallMessage"),
                        QMessageBox.Information,
                    )
                else:
                    self._show_status_box(
                        tr("main.updateComplete"), message, QMessageBox.Information
                    )
                app = QApplication.instance()
                QTimer.singleShot(300, app.quit)
            else:
                self._show_status_box(
                    tr("main.updateFailed"),
                    "Update failed: %s" % message,
                    QMessageBox.Warning,
                )

        def _on_error(error_message):
            progress.close()
            self._show_status_box(tr("main.updateFailed"), error_message, QMessageBox.Warning)

        bridge.sig_progress.connect(_on_progress)
        bridge.sig_complete.connect(_on_complete)
        bridge.sig_error.connect(_on_error)

        updater = AutoUpdater(
            latest_tag=latest_tag,
            release_notes=release_notes,
            download_url=package_url,
            on_progress=bridge.sig_progress.emit,
            on_complete=bridge.sig_complete.emit,
            on_error=bridge.sig_error.emit,
        )
        updater.start_update()

    def check_empty_inventory_onboarding(self):
        """Show onboarding actions when active inventory file is empty."""
        window = self._window
        if window.gui_config.get("import_onboarding_seen", False):
            return
        if not os.path.isfile(window.current_yaml_path):
            return

        data = load_yaml(window.current_yaml_path) or {}
        inventory = data.get("inventory") if isinstance(data, dict) else None
        if inventory and len(inventory) > 0:
            return

        msg_box = self._build_message_box(
            title=tr("main.importStartupTitle"),
            text=tr("main.importStartupMessage"),
            icon=QMessageBox.Information,
        )

        import_btn = msg_box.addButton(tr("main.importExistingDataTitle"), QMessageBox.ActionRole)
        import_btn.setToolTip(tr("main.importExistingDataHint"))
        new_btn = msg_box.addButton(tr("main.new"), QMessageBox.ActionRole)
        later_btn = msg_box.addButton(QMessageBox.Close)
        later_btn.setText(tr("main.newReleaseLater"))
        msg_box.setDefaultButton(import_btn)

        def _mark_onboarding_seen_once():
            self._persist_gui_config_once("import_onboarding_seen", True)

        def _handle_onboarding_action(clicked):
            _mark_onboarding_seen_once()
            if clicked == import_btn:
                self._start_import_journey(parent=window)
            elif clicked == new_btn:
                window.on_create_new_dataset()

        msg_box.buttonClicked.connect(_handle_onboarding_action)
        msg_box.finished.connect(lambda _result: _mark_onboarding_seen_once())
        self._show_nonblocking_dialog(msg_box)


class WindowStateFlow:
    """UI state wiring and persistence extracted from MainWindow."""

    def __init__(self, window):
        self._window = window

    def wire_plan_store(self):
        """Connect PlanStore.on_change to Operations/Overview refresh (thread-safe)."""
        from PySide6.QtCore import QMetaObject, Qt as QtConst

        window = self._window
        ops = window.operations_panel
        overview = getattr(window, "overview_panel", None)
        if overview is not None and hasattr(overview, "bind_plan_store"):
            with suppress(Exception):
                overview.bind_plan_store(window.plan_store)

        def _on_plan_changed():
            QMetaObject.invokeMethod(ops, "refresh_plan_store_view", QtConst.QueuedConnection)
            if overview is not None and hasattr(overview, "refresh_plan_store_view"):
                QMetaObject.invokeMethod(overview, "refresh_plan_store_view", QtConst.QueuedConnection)

        window.plan_store._on_change = _on_plan_changed

    def on_operation_completed(self, success):
        window = self._window
        if success:
            window.overview_panel.refresh()

    def update_dataset_label(self):
        window = self._window
        label = getattr(window, "dataset_label", None)
        if label is None:
            return
        current_path = str(window.current_yaml_path or "")
        label_text = current_path
        formatter = getattr(window, "_format_dataset_label_text", None)
        if callable(formatter):
            label_text = formatter(window.current_yaml_path)
        else:
            dataset_name = os.path.basename(os.path.dirname(current_path)) or os.path.basename(current_path) or "-"
            label_text = dataset_name
        label.setText(label_text)
        if hasattr(label, "setToolTip"):
            label.setToolTip(current_path)

    def update_stats_bar(self, stats):
        """Update the stats bar with overview statistics."""
        window = self._window
        if not isinstance(stats, dict):
            return
        total = stats.get("total", 0)
        occupied = stats.get("occupied", 0)
        empty = stats.get("empty", 0)
        rate = stats.get("rate", 0)
        text = (
            f"{tr('overview.totalRecords')}: {total}  |  "
            f"{tr('overview.occupied')}: {occupied}  |  "
            f"{tr('overview.empty')}: {empty}  |  "
            f"{tr('overview.occupancyRate')}: {rate:.1f}%"
        )
        window.stats_bar.setText(text)

    def update_hover_stats(self, hover_text):
        """Update the stats bar with hover information."""
        window = self._window
        if hover_text:
            window.stats_bar.setText(hover_text)
        else:
            window.stats_bar.setText("")

    def restore_ui_settings(self):
        window = self._window
        geometry = window.settings.value("ui/geometry")
        if geometry:
            window.restoreGeometry(geometry)

        ai_cfg = window.gui_config.get("ai", {})
        window.ai_panel.apply_runtime_settings(
            provider=ai_cfg.get("provider"),
            model=ai_cfg.get("model"),
            max_steps=ai_cfg.get("max_steps", DEFAULT_MAX_STEPS),
            thinking_enabled=ai_cfg.get("thinking_enabled", True),
            custom_prompt=ai_cfg.get("custom_prompt", ""),
        )

    def handle_close_event(self, event):
        window = self._window
        if window.ai_panel.has_running_task():
            QMessageBox.warning(
                window,
                tr("main.aiBusyTitle"),
                tr("main.aiBusyMessage"),
            )
            event.ignore()
            return False

        window.settings.setValue("ui/geometry", window.saveGeometry())

        window.gui_config["yaml_path"] = window.current_yaml_path
        window.gui_config["ai"] = window.ai_panel.runtime_settings_snapshot()
        local_api_state = getattr(window, "_current_local_open_api_config", None)
        if callable(local_api_state):
            window.gui_config["open_api"] = local_api_state()
        save_gui_config(window.gui_config)
        local_api_service = getattr(window, "_local_open_api_service", None)
        if local_api_service is not None and hasattr(local_api_service, "stop"):
            with suppress(Exception):
                local_api_service.stop()
        return True


class SettingsFlow:
    """Settings dialog side effects extracted from MainWindow."""

    def __init__(self, window, normalize_yaml_path: Callable[[str], str]):
        self._window = window
        self._normalize_yaml_path = normalize_yaml_path

    def apply_dialog_values(self, values):
        window = self._window
        window.gui_config["api_keys"] = _submission_value(values, "api_keys", {})

        new_lang = _submission_value(values, "language", "en")
        if new_lang != window.gui_config.get("language"):
            window.gui_config["language"] = new_lang
            self.ask_restart(tr("main.languageChangedRestart"))

        new_theme = _submission_value(values, "theme", "dark")
        if new_theme != window.gui_config.get("theme"):
            window.gui_config["theme"] = new_theme
            self.ask_restart(tr("main.themeChangedRestart"))

        new_scale = _submission_value(values, "ui_scale", 1.0)
        if new_scale != window.gui_config.get("ui_scale"):
            window.gui_config["ui_scale"] = new_scale
            QMessageBox.information(
                window,
                tr("common.info"),
                tr("main.scaleChangedManualRestart"),
            )

        window.gui_config["ai"] = {
            "provider": normalize_ai_provider(_submission_value(values, "ai_provider")),
            "model": _submission_value(
                values,
                "ai_model",
                default_ai_model(_submission_value(values, "ai_provider")),
            ),
            "max_steps": _submission_value(values, "ai_max_steps", DEFAULT_MAX_STEPS),
            "thinking_enabled": _submission_value(values, "ai_thinking_enabled", True),
            "custom_prompt": _submission_value(values, "ai_custom_prompt", ""),
        }
        window.gui_config["open_api"] = {
            "enabled": bool(_submission_value(values, "open_api_enabled", False)),
            "port": int(_submission_value(values, "open_api_port", 0) or 0),
        }
        window.agent_session.set_api_keys(window.gui_config["api_keys"])
        window.ai_panel.apply_runtime_settings(
            provider=window.gui_config["ai"]["provider"],
            model=window.gui_config["ai"]["model"],
            max_steps=window.gui_config["ai"]["max_steps"],
            thinking_enabled=window.gui_config["ai"]["thinking_enabled"],
            custom_prompt=window.gui_config["ai"].get("custom_prompt", ""),
        )
        apply_local_api = getattr(window, "_apply_local_open_api_settings", None)
        if callable(apply_local_api):
            apply_local_api(show_feedback=True)

    def finalize_after_settings(self):
        window = self._window
        if hasattr(window, "_state_flow"):
            window._state_flow.update_dataset_label()
        else:
            window._update_dataset_label()
        window.overview_panel.refresh()
        window.operations_panel.apply_meta_update()
        if not os.path.isfile(window.current_yaml_path):
            window.statusBar().showMessage(
                t("main.fileNotFound", path=window.current_yaml_path),
                6000,
            )
        window.gui_config["yaml_path"] = window.current_yaml_path
        save_gui_config(window.gui_config)

    def handle_data_changed(self, *, yaml_path=None, meta=None):
        window = self._window
        target_yaml = self._normalize_yaml_path(yaml_path or window.current_yaml_path)
        current_yaml = self._normalize_yaml_path(window.current_yaml_path)
        if target_yaml and current_yaml:
            try:
                if os.path.abspath(str(target_yaml)) != os.path.abspath(str(current_yaml)):
                    return
            except Exception:
                return

        window.operations_panel.apply_meta_update(meta if isinstance(meta, dict) else None)
        window.overview_panel.refresh()
        meta_payload = meta if isinstance(meta, dict) else {}
        if "custom_fields" in meta_payload:
            window._emit_system_notice(
                code="settings.custom_fields.updated",
                text=tr("operations.contextSuccess", context=tr("main.customFieldsTitle")),
                level="success",
                source="settings_dialog",
                timeout_ms=3000,
                data={
                    "yaml_path": target_yaml,
                    "custom_field_count": len(meta_payload.get("custom_fields") or []),
                },
            )

    def ask_restart(self, message):
        window = self._window
        box = QMessageBox(window)
        box.setWindowTitle(tr("common.info"))
        box.setText(message)
        btn_restart = box.addButton(tr("main.restartNow"), QMessageBox.AcceptRole)
        box.addButton(tr("main.restartLater"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == btn_restart:
            self.restart_app()

    def restart_app(self):
        window = self._window
        save_gui_config(window.gui_config)

        def delayed_restart():
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable] + sys.argv[1:])
            else:
                subprocess.Popen([sys.executable] + sys.argv)

        QTimer.singleShot(100, delayed_restart)
        QTimer.singleShot(150, QApplication.quit)


class DatasetFlow:
    """Dataset creation workflow extracted from MainWindow."""

    def __init__(self, window, *, dataset_lifecycle_use_case=None):
        self._window = window
        self._dataset_lifecycle = dataset_lifecycle_use_case or DatasetLifecycleUseCase()

    def create_dataset_file(self, *, target_path, box_layout, custom_fields_dialog_cls) -> Optional[str]:
        cf_dlg = custom_fields_dialog_cls(self._window)
        if cf_dlg.exec() != QDialog.Accepted:
            return None
        custom_fields = cf_dlg.get_custom_fields()
        display_key = cf_dlg.get_display_key()
        color_key_getter = getattr(cf_dlg, "get_color_key", None)
        color_key = color_key_getter() if callable(color_key_getter) else ""
        result = self._dataset_lifecycle.create_dataset(
            target_path=target_path,
            box_layout=box_layout,
            custom_fields=custom_fields,
            display_key=display_key,
            color_key=color_key,
        )
        return result.target_path


class ManageBoxesFlow(_ManageBoxesFlowImpl):
    """Compatibility export that preserves the legacy dialog patch point."""

    def prompt_request(self, yaml_path_override=None):
        window = self._window
        yaml_path = str(yaml_path_override or window.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            self._show_warning(t("main.fileNotFound", path=yaml_path))
            return None

        try:
            data = load_yaml(yaml_path)
            layout = (data or {}).get("meta", {}).get("box_layout", {})
        except Exception as exc:
            self._show_warning("%s: %s" % (tr("main.boxAdjustFailed"), exc))
            return None

        dialog = ManageBoxesDialog(layout=layout, parent=window)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.get_request()
