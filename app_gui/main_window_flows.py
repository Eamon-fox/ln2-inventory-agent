"""Extracted workflows for MainWindow to reduce UI-class bloat."""

import os
import subprocess
import sys
from typing import Callable, Optional

import yaml
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QInputDialog

from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS
from app_gui.gui_config import save_gui_config
from app_gui.i18n import t, tr
from app_gui.system_notice import build_system_notice
from lib.position_fmt import get_box_numbers
from lib.yaml_ops import load_yaml


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
        export_task_bundle_dialog_cls,
        import_validated_yaml_dialog_cls,
    ):
        self._window = window
        self._app_version = str(app_version)
        self._release_url = str(release_url)
        self._github_api_latest = str(github_api_latest)
        self._is_version_newer = is_version_newer
        self._show_nonblocking_dialog = show_nonblocking_dialog
        self._export_task_bundle_dialog_cls = export_task_bundle_dialog_cls
        self._import_validated_yaml_dialog_cls = import_validated_yaml_dialog_cls

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
        """Fetch latest release in background and notify if newer."""
        import threading

        window = self._window

        def _fetch_and_notify():
            try:
                import json
                import urllib.request
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG

                req = urllib.request.Request(
                    self._github_api_latest,
                    headers={
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "LN2InventoryAgent",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = str(data.get("tag_name", "")).strip().lstrip("vV")
                if not self._is_version_newer(latest_tag, self._app_version):
                    return
                last_notified = window.gui_config.get("last_notified_release", "0.0.0")
                if not self._is_version_newer(latest_tag, last_notified):
                    return
                body = (data.get("body") or "")[:200]
                QMetaObject.invokeMethod(
                    window,
                    "_show_update_dialog",
                    Qt.QueuedConnection,
                    Q_ARG(str, latest_tag),
                    Q_ARG(str, body),
                )
            except Exception as exc:
                print("[VersionCheck] %s" % exc)

        threading.Thread(target=_fetch_and_notify, daemon=True).start()

    def show_update_dialog(self, latest_tag, release_notes):
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

            update_btn = msg_box.addButton(tr("main.newReleaseUpdate"), QMessageBox.ActionRole)
            copy_btn = msg_box.addButton(tr("main.newReleaseCopy"), QMessageBox.ActionRole)
            open_btn = msg_box.addButton(tr("main.newReleaseOpen"), QMessageBox.ActionRole)
            msg_box.addButton(tr("main.newReleaseLater"), QMessageBox.RejectRole)

            msg_box.setDefaultButton(update_btn)

            def _mark_notified_once():
                self._persist_gui_config_once("last_notified_release", latest_tag)

            def _handle_button(clicked):
                if clicked == update_btn:
                    self.start_automatic_update(latest_tag, release_notes)
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

    def start_automatic_update(self, latest_tag, release_notes):
        """Run automatic update with progress dialog."""
        from PySide6.QtCore import Qt
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

        def _on_progress(progress_value, message):
            progress.setValue(progress_value)
            progress.setLabelText(message)
            QApplication.processEvents()

        def _on_complete(success, message):
            progress.close()
            if success:
                self._show_status_box(tr("main.updateComplete"), message, QMessageBox.Information)
            else:
                self._show_status_box(
                    tr("main.updateFailed"),
                    "Update failed: %s" % message,
                    QMessageBox.Warning,
                )

        def _on_error(error_message):
            progress.close()
            self._show_status_box(tr("main.updateFailed"), error_message, QMessageBox.Warning)

        updater = AutoUpdater(
            latest_tag=latest_tag,
            release_notes=release_notes,
            on_progress=lambda p, msg: _on_progress(p, msg),
            on_complete=lambda success, msg: _on_complete(success, msg),
            on_error=lambda err: _on_error(err),
        )
        updater.start_update()

    def check_empty_inventory_onboarding(self):
        """Show onboarding actions when active inventory file is empty."""
        window = self._window
        try:
            if window.gui_config.get("import_onboarding_seen", False):
                return
            if not os.path.isfile(window.current_yaml_path):
                return

            try:
                data = load_yaml(window.current_yaml_path) or {}
            except Exception:
                return

            inventory = data.get("inventory") if isinstance(data, dict) else None
            if inventory and len(inventory) > 0:
                return

            msg_box = self._build_message_box(
                title=tr("main.importStartupTitle"),
                text=tr("main.importStartupMessage"),
                icon=QMessageBox.Information,
            )

            export_btn = msg_box.addButton(tr("main.exportTaskBundleTitle"), QMessageBox.ActionRole)
            import_yaml_btn = msg_box.addButton(tr("main.importValidatedTitle"), QMessageBox.ActionRole)
            new_btn = msg_box.addButton(tr("main.new"), QMessageBox.ActionRole)
            later_btn = msg_box.addButton(QMessageBox.Close)
            later_btn.setText(tr("main.newReleaseLater"))
            msg_box.setDefaultButton(export_btn)

            def _mark_onboarding_seen_once():
                self._persist_gui_config_once("import_onboarding_seen", True)

            def _handle_onboarding_action(clicked):
                _mark_onboarding_seen_once()
                if clicked == export_btn:
                    dlg = self._export_task_bundle_dialog_cls(window)
                    dlg.exec()
                elif clicked == import_yaml_btn:
                    dlg = self._import_validated_yaml_dialog_cls(
                        window,
                        default_target_path=window.current_yaml_path,
                    )
                    if dlg.exec() == QDialog.Accepted:
                        imported_yaml = str(getattr(dlg, "imported_yaml_path", "") or "").strip()
                        if imported_yaml:
                            old_abs = os.path.abspath(str(window.current_yaml_path or ""))
                            window.current_yaml_path = imported_yaml
                            if old_abs != os.path.abspath(imported_yaml):
                                window.operations_panel.reset_for_dataset_switch()
                            window._update_dataset_label()
                            window.overview_panel.refresh()
                            window.gui_config["yaml_path"] = imported_yaml
                            save_gui_config(window.gui_config)
                elif clicked == new_btn:
                    window.on_create_new_dataset()

            msg_box.buttonClicked.connect(_handle_onboarding_action)
            msg_box.finished.connect(lambda _result: _mark_onboarding_seen_once())
            self._show_nonblocking_dialog(msg_box)
        except Exception as exc:
            print("[ImportOnboarding] Empty inventory check failed: %s" % exc)


class WindowStateFlow:
    """UI state wiring and persistence extracted from MainWindow."""

    def __init__(self, window):
        self._window = window

    def wire_plan_store(self):
        """Connect PlanStore.on_change to OperationsPanel refresh (thread-safe)."""
        from PySide6.QtCore import QMetaObject, Qt as QtConst

        window = self._window
        ops = window.operations_panel

        def _on_plan_changed():
            QMetaObject.invokeMethod(ops, "_on_store_changed", QtConst.QueuedConnection)

        window.plan_store._on_change = _on_plan_changed

    def on_operation_completed(self, success):
        window = self._window
        if success:
            window.overview_panel.refresh()

    def update_dataset_label(self):
        window = self._window
        window.dataset_label.setText(window.current_yaml_path)

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
        provider = ai_cfg.get("provider") or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        window.ai_panel.ai_provider.setText(provider)
        window.ai_panel.ai_model.setText(ai_cfg.get("model") or provider_cfg["model"])
        window.ai_panel.ai_steps.setValue(ai_cfg.get("max_steps", 8))
        window.ai_panel.ai_thinking_enabled.setChecked(bool(ai_cfg.get("thinking_enabled", True)))
        window.ai_panel.ai_thinking_collapsed = not bool(ai_cfg.get("thinking_expanded", True))
        window.ai_panel.ai_custom_prompt = ai_cfg.get("custom_prompt", "")

    def handle_close_event(self, event):
        window = self._window
        if window.ai_panel.ai_run_inflight:
            QMessageBox.warning(
                window,
                tr("main.aiBusyTitle"),
                tr("main.aiBusyMessage"),
            )
            event.ignore()
            return False

        window.settings.setValue("ui/geometry", window.saveGeometry())

        provider = window.ai_panel.ai_provider.text().strip() or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        window.gui_config["yaml_path"] = window.current_yaml_path
        window.gui_config["ai"] = {
            "provider": provider,
            "model": window.ai_panel.ai_model.text().strip() or provider_cfg["model"],
            "max_steps": window.ai_panel.ai_steps.value(),
            "thinking_enabled": window.ai_panel.ai_thinking_enabled.isChecked(),
            "thinking_expanded": not window.ai_panel.ai_thinking_collapsed,
            "custom_prompt": window.ai_panel.ai_custom_prompt,
        }
        save_gui_config(window.gui_config)
        return True


class SettingsFlow:
    """Settings dialog side effects extracted from MainWindow."""

    def __init__(self, window, normalize_yaml_path: Callable[[str], str]):
        self._window = window
        self._normalize_yaml_path = normalize_yaml_path

    def apply_dialog_values(self, values):
        window = self._window
        window.gui_config["api_keys"] = values.get("api_keys", {})

        new_lang = values.get("language", "en")
        if new_lang != window.gui_config.get("language"):
            window.gui_config["language"] = new_lang
            self.ask_restart(tr("main.languageChangedRestart"))

        new_theme = values.get("theme", "dark")
        if new_theme != window.gui_config.get("theme"):
            window.gui_config["theme"] = new_theme
            self.ask_restart(tr("main.themeChangedRestart"))

        new_scale = values.get("ui_scale", 1.0)
        if new_scale != window.gui_config.get("ui_scale"):
            window.gui_config["ui_scale"] = new_scale
            QMessageBox.information(
                window,
                tr("common.info"),
                tr("main.scaleChangedManualRestart"),
            )

        window.gui_config["ai"] = {
            "provider": values.get("ai_provider", DEFAULT_PROVIDER),
            "model": values.get("ai_model", PROVIDER_DEFAULTS[DEFAULT_PROVIDER]["model"]),
            "max_steps": values.get("ai_max_steps", 8),
            "thinking_enabled": values.get("ai_thinking_enabled", True),
            "thinking_expanded": values.get("ai_thinking_expanded", True),
            "custom_prompt": values.get("ai_custom_prompt", ""),
        }
        window.bridge.set_api_keys(window.gui_config["api_keys"])
        window.ai_panel.ai_provider.setText(window.gui_config["ai"]["provider"])
        window.ai_panel.ai_model.setText(window.gui_config["ai"]["model"])
        window.ai_panel.ai_steps.setValue(window.gui_config["ai"]["max_steps"])
        window.ai_panel.ai_thinking_enabled.setChecked(window.gui_config["ai"]["thinking_enabled"])
        window.ai_panel.ai_thinking_collapsed = not window.gui_config["ai"]["thinking_expanded"]
        window.ai_panel.ai_custom_prompt = window.gui_config["ai"].get("custom_prompt", "")

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

    def __init__(self, window):
        self._window = window

    def create_dataset_file(self, *, target_path, box_layout, custom_fields_dialog_cls) -> Optional[str]:
        target_dir = os.path.dirname(target_path)
        if target_dir and not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        cf_dlg = custom_fields_dialog_cls(self._window)
        if cf_dlg.exec() != QDialog.Accepted:
            return None
        custom_fields = cf_dlg.get_custom_fields()
        display_key = cf_dlg.get_display_key()
        cell_line_required = cf_dlg.get_cell_line_required()
        cell_line_options = cf_dlg.get_cell_line_options()

        meta = {
            "version": "1.0",
            "box_layout": box_layout,
            "custom_fields": custom_fields,
            "cell_line_required": bool(cell_line_required),
        }
        if display_key:
            meta["display_key"] = display_key
        if cell_line_options:
            meta["cell_line_options"] = cell_line_options

        new_payload = {
            "meta": meta,
            "inventory": [],
        }
        with open(target_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(new_payload, handle, allow_unicode=True, sort_keys=False)
        return target_path


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
            [tr("main.boxOpAdd"), tr("main.boxOpRemove")],
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
                20,
                1,
            )
            if not ok:
                return None
            return {"operation": "add", "count": int(count)}

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
        window = self._window
        if not isinstance(request, dict):
            return self._error_response("invalid_tool_input", "Invalid manage boxes request")

        yaml_path = str(yaml_path_override or window.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            return self._error_response("load_failed", t("main.fileNotFound", path=yaml_path))

        op = str(request.get("operation") or "").strip().lower()
        if op not in {"add", "remove"}:
            return self._error_response("invalid_operation", "operation must be add/remove")

        payload = {"operation": op}
        mode = self._normalize_mode_alias(request.get("renumber_mode"))

        if op == "add":
            try:
                payload["count"] = int(request.get("count", 1))
            except Exception:
                return self._invalid_count_response()
            if payload["count"] <= 0:
                return self._invalid_count_response()

            if not self._confirm_action(
                window,
                tr("main.manageBoxes"),
                t("main.boxConfirmAdd", count=payload["count"]),
            ):
                return self._user_cancelled_response()
        else:
            try:
                target_box = int(request.get("box"))
            except Exception:
                return self._error_response("invalid_box", "box must be an integer")
            payload["box"] = target_box

            try:
                data = load_yaml(yaml_path)
                layout = (data or {}).get("meta", {}).get("box_layout", {})
                box_numbers = get_box_numbers(layout)
            except Exception as exc:
                return self._error_response("load_failed", str(exc))

            chosen_mode = self.ask_remove_mode(box_numbers, target_box, suggested_mode=mode)
            if chosen_mode is None:
                return self._user_cancelled_response()
            payload["renumber_mode"] = chosen_mode

            mode_label = (
                tr("main.boxDeleteKeepGaps")
                if chosen_mode == "keep_gaps"
                else tr("main.boxDeleteRenumber")
            )
            if not self._confirm_action(
                window,
                tr("main.manageBoxes"),
                t("main.boxConfirmRemove", box=target_box, mode=mode_label),
            ):
                return self._user_cancelled_response()

        response = window.bridge.adjust_box_count(
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

    @staticmethod
    def _normalize_mode_alias(mode_value):
        if mode_value in (None, ""):
            return None
        mode = str(mode_value).strip().lower()
        alias = {
            "keep": "keep_gaps",
            "gaps": "keep_gaps",
            "renumber": "renumber_contiguous",
            "compact": "renumber_contiguous",
        }
        return alias.get(mode, mode)

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
