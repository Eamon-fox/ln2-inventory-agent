"""Manage-boxes workflow implementation kept out of the shared chokepoint."""

from __future__ import annotations

from contextlib import suppress
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from app_gui.i18n import t, tr
from app_gui.system_notice import build_system_notice
from app_gui.ui.dialogs.manage_boxes_dialog import ManageBoxesDialog
from lib.yaml_ops import load_yaml

from .box_layout_mutation_use_case import BoxLayoutMutationUseCase


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

    def __init__(self, window, *, mutation_use_case=None):
        self._window = window
        self._mutation_use_case = mutation_use_case or BoxLayoutMutationUseCase(
            bridge=getattr(window, "bridge", None),
            current_yaml_path_getter=lambda: getattr(window, "current_yaml_path", ""),
        )

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
        prepared = self._mutation_use_case.prepare_request(
            request,
            yaml_path_override=yaml_path_override,
        )
        if (
            isinstance(prepared, dict)
            and prepared.get("ok") is False
            and prepared.get("error_code") == "load_failed"
        ):
            return self._error_response(
                "load_failed",
                t("main.fileNotFound", path=str(yaml_path_override or self._window.current_yaml_path)),
            )
        return prepared

    def _preflight_prepared_request(self, prepared):
        return self._mutation_use_case.preflight(prepared)

    def _load_box_numbers_for_presentation(self, yaml_path):
        return self._mutation_use_case.load_box_numbers_for_presentation(yaml_path)

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
        elif op == "set_indexing":
            response = window.bridge.set_box_layout_indexing(
                yaml_path=yaml_path,
                indexing=payload["indexing"],
                execution_mode="execute",
            )
        else:
            response = window.bridge.manage_boxes(
                yaml_path=yaml_path,
                execution_mode="execute",
                **payload,
            )

        if response.get("ok"):
            apply_meta_update = getattr(getattr(window, "operations_panel", None), "apply_meta_update", None)
            if callable(apply_meta_update):
                apply_meta_update()
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
        preflight = self._preflight_prepared_request(prepared)

        if (
            op == "remove"
            and isinstance(preflight, dict)
            and not preflight.get("ok")
            and preflight.get("error_code") == "renumber_mode_required"
        ):
            box_numbers = self._load_box_numbers_for_presentation(prepared["yaml_path"])
            if isinstance(box_numbers, dict) and box_numbers.get("ok") is False:
                return box_numbers
            chosen_mode = self.ask_remove_mode(box_numbers, int(payload.get("box")))
            if chosen_mode is None:
                return self._user_cancelled_response()
            payload["renumber_mode"] = chosen_mode
            preflight = self._preflight_prepared_request(prepared)

        if not isinstance(preflight, dict) or not preflight.get("ok"):
            return preflight

        preview = preflight.get("preview") or {}
        if op == "add":
            add_count = len(list(preview.get("added_boxes") or [])) or payload.get("count")
            if not self._confirm_action(
                self._window,
                tr("main.manageBoxes"),
                t("main.boxConfirmAdd", count=add_count),
            ):
                return self._user_cancelled_response()
        elif op == "remove":
            target_box = int(payload["box"])
            chosen_mode = str(preview.get("renumber_mode") or payload.get("renumber_mode") or "").strip().lower()
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
            return self.handle_request(
                request,
                from_ai=from_ai,
                yaml_path_override=yaml_path_override,
            )

        initial_preflight = self._preflight_prepared_request(prepared)
        if prepared["op"] in {"set_tag", "set_indexing"}:
            if not isinstance(initial_preflight, dict) or not initial_preflight.get("ok"):
                return initial_preflight
            return self._execute_prepared_request(prepared, from_ai=from_ai)

        if prepared["op"] == "add":
            if not isinstance(initial_preflight, dict) or not initial_preflight.get("ok"):
                return initial_preflight
        elif (
            not isinstance(initial_preflight, dict)
            or (
                not initial_preflight.get("ok")
                and initial_preflight.get("error_code") != "renumber_mode_required"
            )
        ):
            return initial_preflight

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
            preview = initial_preflight.get("preview") or {}
            add_count = len(list(preview.get("added_boxes") or [])) or prepared["payload"].get("count")
            box = QMessageBox(self._window)
            box.setWindowTitle(tr("main.manageBoxes"))
            box.setText(t("main.boxConfirmAdd", count=add_count))
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

        def _show_remove_confirm(chosen_mode, preflight_result=None):
            if result_state["done"]:
                return
            prepared["payload"]["renumber_mode"] = chosen_mode
            preflight = preflight_result or self._preflight_prepared_request(prepared)
            if not isinstance(preflight, dict) or not preflight.get("ok"):
                _finish(preflight)
                return
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
            box_numbers = self._load_box_numbers_for_presentation(prepared["yaml_path"])
            if isinstance(box_numbers, dict) and box_numbers.get("ok") is False:
                _finish(box_numbers)
                return
            target_box = int(prepared["payload"]["box"])

            message = t("main.boxRemoveMiddlePrompt", box=target_box)

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
        elif isinstance(initial_preflight, dict) and initial_preflight.get("ok"):
            _show_remove_confirm(
                str((initial_preflight.get("preview") or {}).get("renumber_mode") or "keep_gaps"),
                preflight_result=initial_preflight,
            )
        else:
            _show_remove_mode()
        return session

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
