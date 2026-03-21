"""Extracted workflows for MainWindow to reduce UI-class bloat."""

from contextlib import suppress
import os
import subprocess
import sys
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QInputDialog

from app_gui.application import DatasetLifecycleUseCase
from app_gui.application.ai_provider_catalog import (
    default_ai_model,
    normalize_ai_provider,
)
from app_gui.gui_config import DEFAULT_MAX_STEPS, save_gui_config
from app_gui.i18n import t, tr
from app_gui.system_notice import build_system_notice
from app_gui.ui.limits import MAX_BOX_COUNT_UI
from app_gui.version import resolve_platform_release_info
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.position_fmt import box_tag_text, get_box_numbers
from lib.tool_api_write_validation import (
    normalize_manage_boxes_operation,
    normalize_manage_boxes_renumber_mode,
)
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
                body = str(data.get("release_notes", ""))[:200]
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
            title = tr("main.newReleaseTitle")
            message = t(
                "main.newReleaseMessage",
                version=latest_tag,
                notes=release_notes or tr("main.releaseNotesDefault"),
            )

            msg_box = self._build_message_box(
                title=title,
                text=message,
                icon=QMessageBox.Information,
            )

            release_info = resolve_platform_release_info({"download_url": download_url})
            update_label = (
                tr("main.newReleaseUpdate")
                if bool(release_info.get("auto_update"))
                else tr("main.newReleaseDownload")
            )

            update_btn = msg_box.addButton(update_label, QMessageBox.ActionRole)
            copy_btn = msg_box.addButton(tr("main.newReleaseCopy"), QMessageBox.ActionRole)
            open_btn = msg_box.addButton(tr("main.newReleaseOpen"), QMessageBox.ActionRole)
            msg_box.addButton(tr("main.newReleaseLater"), QMessageBox.RejectRole)

            msg_box.setDefaultButton(update_btn)

            def _mark_notified_once():
                self._persist_gui_config_once("last_notified_release", latest_tag)

            def _handle_button(clicked):
                if clicked == update_btn:
                    self.start_automatic_update(latest_tag, release_notes, download_url)
                elif clicked == copy_btn:
                    try:
                        QApplication.clipboard().setText(self._release_url)
                    except Exception as exc:
                        print("[VersionCheck] Copy to clipboard failed: %s" % exc)
                elif clicked == open_btn:
                    try:
                        from PySide6.QtCore import QUrl
                        from PySide6.QtGui import QDesktopServices

                        QDesktopServices.openUrl(QUrl(self._release_url))
                    except Exception as exc:
                        print("[VersionCheck] Open URL failed: %s" % exc)

            msg_box.buttonClicked.connect(_handle_button)
            msg_box.finished.connect(lambda _result: _mark_notified_once())
            self._show_nonblocking_dialog(msg_box)
        except Exception as exc:
            print("[VersionCheck] Dialog failed: %s" % exc)

    def start_automatic_update(self, latest_tag, release_notes, download_url=""):
        """Run automatic update with progress dialog."""
        release_info = resolve_platform_release_info({"download_url": download_url})
        package_url = str(release_info.get("download_url", "")).strip()
        target_url = package_url or self._release_url
        if not bool(release_info.get("auto_update")):
            try:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not target_url:
                    raise RuntimeError(tr("main.updateManualNoUrl"))
                QDesktopServices.openUrl(QUrl(target_url))
                self._show_status_box(
                    tr("main.updateManualTitle"),
                    t(
                        "main.updateManualMessage",
                        platform=str(release_info.get("platform_name", "macOS")),
                    ),
                    QMessageBox.Information,
                )
            except Exception as exc:
                self._show_status_box(tr("main.updateFailed"), str(exc), QMessageBox.Warning)
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
                self._show_status_box(tr("main.updateComplete"), message, QMessageBox.Information)
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
        save_gui_config(window.gui_config)
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
        window.agent_session.set_api_keys(window.gui_config["api_keys"])
        window.ai_panel.apply_runtime_settings(
            provider=window.gui_config["ai"]["provider"],
            model=window.gui_config["ai"]["model"],
            max_steps=window.gui_config["ai"]["max_steps"],
            thinking_enabled=window.gui_config["ai"]["thinking_enabled"],
            custom_prompt=window.gui_config["ai"].get("custom_prompt", ""),
        )

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


class _AsyncManageBoxesSession:
    def __init__(self):
        self._current_dialog = None
        self._closed = False

    def attach_dialog(self, dialog):
        if self._closed:
            with suppress(Exception):
                dialog.close()
            return False
        self._current_dialog = dialog
        return True

    def close(self):
        self._closed = True
        dialog = self._current_dialog
        self._current_dialog = None
        if dialog is not None:
            with suppress(Exception):
                dialog.close()


class ManageBoxesFlow:
    """Box-layout interaction workflow extracted from MainWindow."""

    def __init__(self, window):
        self._window = window

    def _show_info(self, message, title=None):
        QMessageBox.information(
            self._window,
            str(title or tr("common.info")),
            str(message or ""),
        )

    def _show_warning(self, message, title=None):
        QMessageBox.warning(
            self._window,
            str(title or tr("common.info")),
            str(message or ""),
        )

    def _show_nonblocking_dialog(self, dialog):
        window = self._window
        helper = getattr(window, "_show_nonblocking_dialog", None)
        if callable(helper):
            helper(dialog)
            return

        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setModal(False)
        refs = getattr(window, "_floating_dialog_refs", None)
        if not isinstance(refs, list):
            refs = []
            setattr(window, "_floating_dialog_refs", refs)
        refs.append(dialog)

        def _release_ref(_result=0):
            with suppress(ValueError):
                refs.remove(dialog)

        dialog.finished.connect(_release_ref)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _prepare_request(self, request, yaml_path_override=None):
        window = self._window
        if not isinstance(request, dict):
            return self._error_response("invalid_tool_input", "Invalid manage boxes request")

        yaml_path = str(yaml_path_override or window.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            return self._error_response("load_failed", t("main.fileNotFound", path=yaml_path))

        raw_op = str(request.get("operation") or "").strip().lower()
        if raw_op == "set_tag":
            op = "set_tag"
        else:
            op = normalize_manage_boxes_operation(raw_op)
        if op not in {"add", "remove", "set_tag"}:
            return self._error_response("invalid_operation", "operation must be add/remove/set_tag")

        prepared = {
            "yaml_path": yaml_path,
            "op": op,
            "payload": {"operation": op},
        }
        mode = self._normalize_mode_alias(request.get("renumber_mode"))

        if op == "add":
            if "count" not in request:
                return self._invalid_count_response()
            try:
                prepared["payload"]["count"] = int(request.get("count"))
            except Exception:
                return self._invalid_count_response()
            if prepared["payload"]["count"] <= 0:
                return self._invalid_count_response()
            return prepared

        if op == "set_tag":
            try:
                target_box = int(request.get("box"))
            except Exception:
                return self._error_response("invalid_box", "box must be an integer")

            raw_tag = request.get("tag", "")
            if raw_tag is None:
                raw_tag = ""
            prepared["payload"]["box"] = target_box
            prepared["payload"]["tag"] = str(raw_tag)

            try:
                data = load_yaml(yaml_path)
                layout = (data or {}).get("meta", {}).get("box_layout", {})
                box_numbers = get_box_numbers(layout)
            except Exception as exc:
                return self._error_response("load_failed", str(exc))
            if target_box not in box_numbers:
                return self._error_response(
                    "invalid_box",
                    "box does not exist in current layout",
                )
            return prepared

        try:
            target_box = int(request.get("box"))
        except Exception:
            return self._error_response("invalid_box", "box must be an integer")

        prepared["payload"]["box"] = target_box
        try:
            data = load_yaml(yaml_path)
            layout = (data or {}).get("meta", {}).get("box_layout", {})
            box_numbers = get_box_numbers(layout)
        except Exception as exc:
            return self._error_response("load_failed", str(exc))
        if target_box not in box_numbers:
            return self._error_response(
                "invalid_box",
                "box does not exist in current layout",
            )

        prepared["box_numbers"] = box_numbers
        prepared["suggested_mode"] = mode
        return prepared

    def _execute_prepared_request(self, prepared, *, from_ai):
        window = self._window
        yaml_path = prepared["yaml_path"]
        op = prepared["op"]
        payload = dict(prepared.get("payload") or {})

        if op == "set_tag":
            response = window.bridge.set_box_tag(
                yaml_path=yaml_path,
                box=payload["box"],
                tag=payload.get("tag", ""),
                execution_mode="execute",
            )
        else:
            response = window.bridge.manage_boxes(
                yaml_path=yaml_path,
                execution_mode="execute",
                **payload,
            )

        if response.get("ok"):
            window.overview_panel.refresh()
            window.on_operation_completed(True)
        notice_level = "success" if response.get("ok") else "error"
        notice_text = str(
            response.get("message")
            or (tr("main.boxAdjustSuccess") if response.get("ok") else tr("main.boxAdjustFailed"))
        )
        notice = build_system_notice(
            code="box.layout.adjusted",
            text=notice_text,
            level=notice_level,
            source="ai" if from_ai else "settings",
            timeout_ms=3000,
            data={
                "operation": op,
                "ok": bool(response.get("ok")),
                "preview": response.get("preview") or response.get("result") or {},
                "error_code": response.get("error_code"),
            },
        )
        window.show_status(notice_text, 3000, notice_level)
        window.operations_panel.emit_external_operation_event(notice)
        return response

    def manage_boxes(self, yaml_path_override=None):
        request = self.prompt_request(yaml_path_override=yaml_path_override)
        if not request:
            return
        result = self.handle_request(
            request,
            from_ai=False,
            yaml_path_override=yaml_path_override,
        )
        if isinstance(result, dict) and result.get("ok"):
            self._show_info(tr("main.boxAdjustSuccess"))
        elif isinstance(result, dict) and result.get("error_code") != "user_cancelled":
            self._show_warning(result.get("message") or tr("main.boxAdjustFailed"))

    def prompt_request(self, yaml_path_override=None):
        window = self._window
        yaml_path = str(yaml_path_override or window.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            self._show_warning(t("main.fileNotFound", path=yaml_path))
            return None

        operation, ok = QInputDialog.getItem(
            window,
            tr("main.manageBoxes"),
            tr("main.boxActionPrompt"),
            [tr("main.boxOpAdd"), tr("main.boxOpRemove"), tr("main.boxOpSetTag")],
            0,
            False,
        )
        if not ok:
            return None

        if operation == tr("main.boxOpAdd"):
            count, ok = QInputDialog.getInt(
                window,
                tr("main.manageBoxes"),
                tr("main.boxAddCountPrompt"),
                1,
                1,
                MAX_BOX_COUNT_UI,
                1,
            )
            if not ok:
                return None
            return {"operation": "add", "count": int(count)}

        if operation == tr("main.boxOpSetTag"):
            try:
                data = load_yaml(yaml_path)
                layout = (data or {}).get("meta", {}).get("box_layout", {})
                box_numbers = get_box_numbers(layout)
            except Exception as exc:
                self._show_warning("%s: %s" % (tr("main.boxAdjustFailed"), exc))
                return None

            if not box_numbers:
                self._show_warning(tr("main.boxNoAvailable"))
                return None

            box_text, ok = QInputDialog.getItem(
                window,
                tr("main.manageBoxes"),
                tr("main.boxTagTargetPrompt"),
                [str(box_num) for box_num in box_numbers],
                0,
                False,
            )
            if not ok:
                return None

            current_tag = self._get_box_tag(layout, int(box_text))
            tag_text, ok = QInputDialog.getText(
                window,
                tr("main.manageBoxes"),
                t("main.boxTagInputPrompt", box=box_text),
                text=current_tag,
            )
            if not ok:
                return None
            return {"operation": "set_tag", "box": int(box_text), "tag": str(tag_text or "")}

        try:
            data = load_yaml(yaml_path)
            layout = (data or {}).get("meta", {}).get("box_layout", {})
            box_numbers = get_box_numbers(layout)
        except Exception as exc:
            self._show_warning("%s: %s" % (tr("main.boxAdjustFailed"), exc))
            return None

        if not box_numbers:
            self._show_warning(tr("main.boxNoAvailable"))
            return None

        box_text, ok = QInputDialog.getItem(
            window,
            tr("main.manageBoxes"),
            tr("main.boxRemovePrompt"),
            [str(box_num) for box_num in box_numbers],
            0,
            False,
        )
        if not ok:
            return None
        return {"operation": "remove", "box": int(box_text)}

    def ask_remove_mode(self, box_numbers, target_box, suggested_mode=None):
        window = self._window
        if not any(int(box_num) > int(target_box) for box_num in box_numbers):
            if suggested_mode in {"keep_gaps", "renumber_contiguous"}:
                return suggested_mode
            return "keep_gaps"

        message = t("main.boxRemoveMiddlePrompt", box=target_box)
        if suggested_mode in {"keep_gaps", "renumber_contiguous"}:
            mode_label = (
                tr("main.boxDeleteKeepGaps")
                if suggested_mode == "keep_gaps"
                else tr("main.boxDeleteRenumber")
            )
            message += "\n" + t("main.boxAiSuggestedMode", mode=mode_label)

        dlg = QMessageBox(window)
        dlg.setWindowTitle(tr("main.manageBoxes"))
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(message)
        keep_btn = dlg.addButton(tr("main.boxDeleteKeepGaps"), QMessageBox.AcceptRole)
        renumber_btn = dlg.addButton(tr("main.boxDeleteRenumber"), QMessageBox.ActionRole)
        dlg.addButton(QMessageBox.Cancel)
        dlg.setDefaultButton(keep_btn)
        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked == keep_btn:
            return "keep_gaps"
        if clicked == renumber_btn:
            return "renumber_contiguous"
        return None

    def handle_request(self, request, from_ai=True, yaml_path_override=None):
        prepared = self._prepare_request(request, yaml_path_override=yaml_path_override)
        if isinstance(prepared, dict) and prepared.get("ok") is False:
            return prepared

        op = prepared["op"]
        payload = prepared["payload"]
        if op == "add":
            if not self._confirm_action(
                self._window,
                tr("main.manageBoxes"),
                t("main.boxConfirmAdd", count=payload["count"]),
            ):
                return self._user_cancelled_response()
        elif op == "remove":
            target_box = payload["box"]
            chosen_mode = self.ask_remove_mode(
                prepared.get("box_numbers") or [],
                target_box,
                suggested_mode=prepared.get("suggested_mode"),
            )
            if chosen_mode is None:
                return self._user_cancelled_response()
            payload["renumber_mode"] = chosen_mode

            mode_label = (
                tr("main.boxDeleteKeepGaps")
                if chosen_mode == "keep_gaps"
                else tr("main.boxDeleteRenumber")
            )
            if not self._confirm_action(
                self._window,
                tr("main.manageBoxes"),
                t("main.boxConfirmRemove", box=target_box, mode=mode_label),
            ):
                return self._user_cancelled_response()
        return self._execute_prepared_request(prepared, from_ai=from_ai)

    def handle_request_async(self, request, on_result, from_ai=True, yaml_path_override=None):
        prepared = self._prepare_request(request, yaml_path_override=yaml_path_override)
        if isinstance(prepared, dict) and prepared.get("ok") is False:
            return prepared
        if not callable(on_result):
            return self._execute_prepared_request(prepared, from_ai=from_ai)

        if prepared["op"] == "set_tag":
            return self._execute_prepared_request(prepared, from_ai=from_ai)

        session = _AsyncManageBoxesSession()
        result_state = {"done": False}

        def _finish(result):
            if result_state["done"]:
                return
            result_state["done"] = True
            session.close()
            on_result(result)

        def _show_with_session(dialog):
            if not session.attach_dialog(dialog):
                return False
            self._show_nonblocking_dialog(dialog)
            return True

        def _show_add_confirm():
            box = QMessageBox(self._window)
            box.setWindowTitle(tr("main.manageBoxes"))
            box.setText(t("main.boxConfirmAdd", count=prepared["payload"]["count"]))
            box.setIcon(QMessageBox.Question)
            yes_btn = box.addButton(QMessageBox.Yes)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(yes_btn)

            def _on_finished(_result):
                if result_state["done"]:
                    return
                if box.clickedButton() == yes_btn:
                    _finish(self._execute_prepared_request(prepared, from_ai=from_ai))
                else:
                    _finish(self._user_cancelled_response())

            box.finished.connect(_on_finished)
            _show_with_session(box)

        def _show_remove_confirm(chosen_mode):
            if result_state["done"]:
                return
            prepared["payload"]["renumber_mode"] = chosen_mode
            mode_label = (
                tr("main.boxDeleteKeepGaps")
                if chosen_mode == "keep_gaps"
                else tr("main.boxDeleteRenumber")
            )
            box = QMessageBox(self._window)
            box.setWindowTitle(tr("main.manageBoxes"))
            box.setText(
                t(
                    "main.boxConfirmRemove",
                    box=prepared["payload"]["box"],
                    mode=mode_label,
                )
            )
            box.setIcon(QMessageBox.Warning)
            yes_btn = box.addButton(QMessageBox.Yes)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(yes_btn)

            def _on_finished(_result):
                if result_state["done"]:
                    return
                if box.clickedButton() == yes_btn:
                    _finish(self._execute_prepared_request(prepared, from_ai=from_ai))
                else:
                    _finish(self._user_cancelled_response())

            box.finished.connect(_on_finished)
            _show_with_session(box)

        def _show_remove_mode():
            if result_state["done"]:
                return
            target_box = prepared["payload"]["box"]
            box_numbers = prepared.get("box_numbers") or []
            suggested_mode = prepared.get("suggested_mode")
            if not any(int(box_num) > int(target_box) for box_num in box_numbers):
                chosen_mode = suggested_mode if suggested_mode in {"keep_gaps", "renumber_contiguous"} else "keep_gaps"
                _show_remove_confirm(chosen_mode)
                return

            message = t("main.boxRemoveMiddlePrompt", box=target_box)
            if suggested_mode in {"keep_gaps", "renumber_contiguous"}:
                mode_label = (
                    tr("main.boxDeleteKeepGaps")
                    if suggested_mode == "keep_gaps"
                    else tr("main.boxDeleteRenumber")
                )
                message += "\n" + t("main.boxAiSuggestedMode", mode=mode_label)

            box = QMessageBox(self._window)
            box.setWindowTitle(tr("main.manageBoxes"))
            box.setIcon(QMessageBox.Warning)
            box.setText(message)
            keep_btn = box.addButton(tr("main.boxDeleteKeepGaps"), QMessageBox.AcceptRole)
            renumber_btn = box.addButton(tr("main.boxDeleteRenumber"), QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(keep_btn)

            def _on_finished(_result):
                if result_state["done"]:
                    return
                clicked = box.clickedButton()
                if clicked == keep_btn:
                    _show_remove_confirm("keep_gaps")
                elif clicked == renumber_btn:
                    _show_remove_confirm("renumber_contiguous")
                else:
                    _finish(self._user_cancelled_response())

            box.finished.connect(_on_finished)
            _show_with_session(box)

        if prepared["op"] == "add":
            _show_add_confirm()
        else:
            _show_remove_mode()
        return session

    @staticmethod
    def _normalize_mode_alias(mode_value):
        return normalize_manage_boxes_renumber_mode(mode_value)

    @staticmethod
    def _invalid_count_response():
        return ManageBoxesFlow._error_response("invalid_count", "count must be a positive integer")

    @staticmethod
    def _error_response(error_code, message):
        return {
            "ok": False,
            "error_code": str(error_code or "unknown_error"),
            "message": str(message or ""),
        }

    @staticmethod
    def _user_cancelled_response():
        return ManageBoxesFlow._error_response("user_cancelled", tr("main.boxCancelled"))

    @staticmethod
    def _confirm_action(window, title, message):
        reply = QMessageBox.question(
            window,
            title,
            message,
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes

    @staticmethod
    def _get_box_tag(layout, box_num):
        return box_tag_text(box_num, layout)
