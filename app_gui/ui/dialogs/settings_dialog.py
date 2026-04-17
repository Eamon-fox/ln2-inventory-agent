"""Settings dialog extracted from main window module."""

import os
import sys

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_gui.application.custom_fields_use_case import CustomFieldsUseCase
from app_gui.application.settings_dialog_submission import SettingsDialogSubmission
from app_gui.application.settings_dataset_use_case import SettingsDatasetUseCase
from app_gui.application.settings_validation_use_case import SettingsValidationUseCase
from app_gui.i18n import t, tr
from app_gui.ui.dialogs import settings_dialog_about_section as _about_section
from app_gui.ui.dialogs import settings_dialog_ai_section as _ai_section
from app_gui.ui.dialogs import settings_dialog_custom_fields as _custom_fields
from app_gui.ui.dialogs import settings_dialog_dataset_section as _dataset_section
from app_gui.ui.dialogs import settings_dialog_formatters as _formatters
from app_gui.ui.dialogs import settings_dialog_local_api_section as _local_api_section
from lib.inventory_paths import normalize_inventory_yaml_path as _normalize_inventory_yaml_path
from lib.validators import format_validation_errors
from app_gui.version import (
    APP_VERSION,
    APP_RELEASE_URL,
    UPDATE_CHECK_URL as _GITHUB_API_LATEST,
)

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _is_valid_inventory_file_path(path_text):
    """Legacy helper retained for compatibility with existing tests."""
    path = _normalize_inventory_yaml_path(path_text)
    if not path or os.path.isdir(path):
        return False
    suffix = os.path.splitext(path)[1].lower()
    if suffix not in {".yaml", ".yml"}:
        return False
    return os.path.isfile(path)


class _NoWheelComboBox(QComboBox):
    """Let parent scroll area handle mouse wheel."""

    def wheelEvent(self, event):
        event.ignore()


class _NoWheelSpinBox(QSpinBox):
    """Let parent scroll area handle mouse wheel."""

    def wheelEvent(self, event):
        event.ignore()


class _NoWheelTextEdit(QTextEdit):
    """Scroll parent unless this editor is actively focused."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class _NoWheelPlainTextEdit(QPlainTextEdit):
    """Scroll parent unless this editor is actively focused."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class _NoPasteLineEdit(QLineEdit):
    """QLineEdit that blocks paste paths for destructive confirmations."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            return
        if event.key() == Qt.Key_Insert and event.modifiers() & Qt.ShiftModifier:
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            return
        super().mousePressEvent(event)

    def insertFromMimeData(self, source):
        return

    def dragEnterEvent(self, event):
        event.ignore()

    def dragMoveEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()


class _ProgrammaticClickButton(QPushButton):
    """Keep programmatic test clicks non-blocking without affecting real UI clicks."""

    def click(self):
        self.clicked.emit()


def _read_bundled_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return ""


class SettingsDialog(QDialog):
    """Enhanced Settings dialog with sections and help text."""

    def __init__(
        self,
        parent=None,
        config=None,
        on_create_new_dataset=None,
        on_rename_dataset=None,
        on_delete_dataset=None,
        on_change_data_root=None,
        on_manage_boxes=None,
        on_data_changed=None,
        *,
        app_version=APP_VERSION,
        app_release_url=APP_RELEASE_URL,
        github_api_latest=_GITHUB_API_LATEST,
        root_dir=None,
        on_import_existing_data=None,
        on_export_inventory_csv=None,
        custom_fields_dialog_cls=None,
        custom_fields_use_case=None,
        settings_dataset_use_case=None,
        settings_validation_use_case=None,
        normalize_yaml_path=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(750)
        self.setMinimumHeight(750)
        self._config = config or {}
        self._on_create_new_dataset = on_create_new_dataset
        self._on_rename_dataset = on_rename_dataset
        self._on_delete_dataset = on_delete_dataset
        self._on_change_data_root = on_change_data_root
        self._on_manage_boxes = on_manage_boxes
        self._on_data_changed = on_data_changed
        self._app_version = str(app_version or APP_VERSION)
        self._app_release_url = str(app_release_url or APP_RELEASE_URL)
        self._github_api_latest = str(github_api_latest or _GITHUB_API_LATEST)
        self._root_dir = root_dir or ROOT
        self._on_import_existing_data = on_import_existing_data
        self._on_export_inventory_csv = on_export_inventory_csv
        self._custom_fields_dialog_cls = custom_fields_dialog_cls
        self._normalize_yaml_path = normalize_yaml_path or _normalize_inventory_yaml_path
        self._settings_dataset_use_case = settings_dataset_use_case or SettingsDatasetUseCase(
            normalize_yaml_path=self._normalize_yaml_path,
        )
        self._custom_fields_use_case = custom_fields_use_case or CustomFieldsUseCase()
        self._settings_validation_use_case = (
            settings_validation_use_case or SettingsValidationUseCase()
        )
        self._inventory_path_locked = True
        self._local_api_skill_copy_reset_ms = 1800
        self._checkbox_cls = QCheckBox
        self._combo_box_cls = _NoWheelComboBox
        self._line_edit_cls = _NoPasteLineEdit
        self._spin_box_cls = _NoWheelSpinBox
        self._plain_text_edit_cls = _NoWheelPlainTextEdit
        self._read_bundled_text_file = _read_bundled_text_file
        self._programmatic_click_button_cls = _ProgrammaticClickButton

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
        self.yaml_edit = QLineEdit(self._config.get("yaml_path", ""))
        self._initial_yaml_path = self._normalize_yaml_path(
            self._config.get("yaml_path", "")
        )
        self.data_root_edit = QLineEdit(self._config.get("data_root", ""))
        self.dataset_switch_combo = _NoWheelComboBox()
        self.dataset_rename_btn = None
        self.dataset_delete_btn = None
        content_layout.addWidget(_dataset_section.build_dataset_group(self))
        content_layout.addWidget(
            _ai_section.build_ai_group(
                self,
                combo_box_cls=_NoWheelComboBox,
                spin_box_cls=_NoWheelSpinBox,
                text_edit_cls=_NoWheelTextEdit,
            )
        )
        content_layout.addWidget(
            _local_api_section.build_local_api_group(
                self,
                spin_box_cls=_NoWheelSpinBox,
                plain_text_edit_cls=_NoWheelPlainTextEdit,
            )
        )
        content_layout.addWidget(
            _about_section.build_preferences_group(
                self,
                combo_box_cls=_NoWheelComboBox,
            )
        )
        content_layout.addWidget(_about_section.build_about_group(self))

        content_layout.addStretch()

        self._refresh_local_api_skill_template()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        if self._ok_button is not None:
            self._ok_button.setText(tr("common.ok"))
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.yaml_edit.textChanged.connect(self._refresh_yaml_path_validity)
        self._refresh_yaml_path_validity()
        layout.addWidget(buttons)

    def _is_valid_inventory_file_path(self, path_text):
        return self._settings_dataset_use_case.is_valid_inventory_file_path(
            path_text=path_text,
        )

    def _refresh_yaml_path_validity(self):
        if not hasattr(self, "_ok_button") or self._ok_button is None:
            return
        self._ok_button.setEnabled(self._is_valid_inventory_file_path(self.yaml_edit.text().strip()))

    def _current_template_language(self) -> str:
        return _local_api_section.current_template_language(self)

    def _resolve_local_api_skill_template_text(self, language: str) -> tuple[str, bool]:
        return _local_api_section.resolve_local_api_skill_template_text(self, language)

    @Slot()
    @Slot(int)
    def _refresh_local_api_skill_template(self, *_args):
        _local_api_section.refresh_local_api_skill_template(self, *_args)

    @Slot()
    def _reset_local_api_skill_copy_button_text(self):
        _local_api_section.reset_local_api_skill_copy_button_text(self)

    @Slot()
    def _copy_local_api_skill_template(self):
        _local_api_section.copy_local_api_skill_template(self)

    def _refresh_dataset_choices(self, selected_yaml=""):
        _dataset_section.refresh_dataset_choices(self, selected_yaml=selected_yaml)

    def _on_dataset_switch_changed(self):
        _dataset_section.on_dataset_switch_changed(self)

    @staticmethod
    def _render_validation_report(report, *, max_items=8):
        if not isinstance(report, dict):
            return ""
        errors = list(report.get("errors") or [])
        if not errors:
            return ""
        lines = [f"- {item}" for item in errors[:max_items]]
        if len(errors) > max_items:
            lines.append(f"- ... and {len(errors) - max_items} more")
        return "\n".join(lines)

    @staticmethod
    def _validation_failed_result(errors, *, warnings=None, prefix="Validation failed"):
        normalized_errors = list(errors or [])
        normalized_warnings = list(warnings or [])
        return {
            "ok": False,
            "error_code": "validation_failed",
            "message": format_validation_errors(normalized_errors, prefix=prefix),
            "report": {
                "error_count": len(normalized_errors),
                "warning_count": len(normalized_warnings),
                "errors": normalized_errors,
                "warnings": normalized_warnings,
            },
        }

    def _show_validation_blocked_result(self, result, *, include_dataset_hint=False):
        normalized = dict(result or {})
        report_text = self._render_validation_report(normalized.get("report") or {})
        message = t(
            "main.datasetYamlValidationBlocked",
            message=normalized.get("message") or tr("main.importValidationFailed"),
        )
        if report_text:
            message += "\n\n" + report_text
        if include_dataset_hint:
            message += "\n\n" + tr("main.datasetYamlValidationHint")
        QMessageBox.warning(self, tr("main.importValidatedTitle"), message)

    def accept(self):
        """Block saving settings when selected dataset YAML fails validation.

        When the YAML path has not changed, use meta-only validation (skip
        per-record checks) so that field-definition edits made by the custom
        fields editor don't block closing the dialog.  When the path *has*
        changed the user is loading a different file, so full strict
        validation applies.
        """
        yaml_path = self._normalize_yaml_path(self.yaml_edit.text().strip())
        if self._is_valid_inventory_file_path(yaml_path):
            result = self._settings_validation_use_case.validate_yaml_for_settings_accept(
                yaml_path=yaml_path,
                initial_yaml_path=getattr(self, "_initial_yaml_path", ""),
            )
            if not result.get("ok"):
                self._show_validation_blocked_result(
                    result,
                    include_dataset_hint=True,
                )
                return

        super().accept()

    def _notify_data_changed(self, *, yaml_path=None, meta=None):
        """Notify parent window after metadata edits."""
        if not callable(self._on_data_changed):
            return
        self._on_data_changed(yaml_path=yaml_path, meta=meta)

    def _emit_create_new_dataset_request(self):
        _dataset_section.emit_create_new_dataset_request(self)

    def _emit_change_data_root_request(self):
        _dataset_section.emit_change_data_root_request(self)

    def _emit_rename_dataset_request(self):
        _dataset_section.emit_rename_dataset_request(
            self,
            qinputdialog_cls=QInputDialog,
            message_box_cls=QMessageBox,
        )

    def _confirm_phrase_dialog(self, *, title, prompt_text, phrase, strip_input=False):
        return _dataset_section.confirm_phrase_dialog(
            self,
            title=title,
            prompt_text=prompt_text,
            phrase=phrase,
            line_edit_cls=self._line_edit_cls,
            dialog_cls=QDialog,
            label_cls=QLabel,
            button_cls=QPushButton,
            dialog_button_box_cls=QDialogButtonBox,
            strip_input=strip_input,
        )

    def _emit_delete_dataset_request(self):
        _dataset_section.emit_delete_dataset_request(
            self,
            message_box_cls=QMessageBox,
        )

    def _confirm_delete_dataset_initial(self, dataset_name):
        return _dataset_section.confirm_delete_dataset_initial(
            self,
            dataset_name,
            message_box_cls=QMessageBox,
        )

    def _confirm_delete_dataset_final(self, dataset_name):
        return _dataset_section.confirm_delete_dataset_final(
            self,
            dataset_name,
            message_box_cls=QMessageBox,
        )

    def _on_check_update(self):
        _about_section.start_check_update(self)

    @Slot(str, str, str)
    def _on_check_update_result(self, latest_tag, info, download_url):
        _about_section.handle_check_update_result(self, latest_tag, info, download_url)

    @staticmethod
    def _format_removed_field_preview_value(value, *, max_length=80):
        return _formatters.format_removed_field_preview_value(value, max_length=max_length)

    @staticmethod
    def _format_removed_field_preview_box(box, layout):
        return _formatters.format_removed_field_preview_box(box, layout)

    @staticmethod
    def _format_removed_field_preview_position(position, layout):
        return _formatters.format_removed_field_preview_position(position, layout)

    def _format_removed_field_preview_entry(self, entry, *, layout):
        return _formatters.format_removed_field_preview_entry(entry, layout=layout)

    def _format_removed_field_preview_summary(self, previews, *, layout):
        return _formatters.format_removed_field_preview_summary(previews, layout=layout)

    def _format_removed_field_preview_details(self, previews, *, layout):
        return _formatters.format_removed_field_preview_details(previews, layout=layout)

    def _open_custom_fields_editor(self):
        _custom_fields.open_custom_fields_editor(
            self,
            destructive_button_cls=_ProgrammaticClickButton,
        )

    def _open_manage_boxes(self):
        if callable(self._on_manage_boxes):
            self._on_manage_boxes(self.yaml_edit.text().strip())

    def _open_import_journey(self):
        if not callable(self._on_import_existing_data):
            raise RuntimeError("SettingsDialog requires `on_import_existing_data` callback.")
        stage = str(self._on_import_existing_data(parent=self) or "").strip().lower()
        if stage == "awaiting_ai":
            # Import migration now continues in the main window AI panel.
            self.reject()

    def _open_export_inventory_csv(self):
        if not callable(self._on_export_inventory_csv):
            return
        self._on_export_inventory_csv(
            parent=self,
            yaml_path_override=self.yaml_edit.text().strip(),
        )

    def _on_provider_changed(self):
        provider = self.ai_provider_combo.currentData()
        _, default_model = self._provider_models(provider)
        self._refresh_model_options(provider, selected_model=default_model)

    @staticmethod
    def _provider_models(provider):
        return _ai_section.provider_models(provider)

    def _refresh_model_options(self, provider, selected_model=None):
        _ai_section.refresh_model_options(self, provider, selected_model=selected_model)

    def _build_locked_api_key_row(self, initial_value):
        return _ai_section.build_locked_api_key_row(self, initial_value)

    @staticmethod
    def _toggle_api_key_lock(key_edit, lock_btn):
        _ai_section.toggle_api_key_lock(key_edit, lock_btn)

    def get_submission(self):
        provider = self.ai_provider_combo.currentData()
        _, default_model = self._provider_models(provider)
        api_keys = {}
        for prov_id, edit in self._api_key_edits.items():
            key_text = edit.text().strip()
            if key_text:
                api_keys[prov_id] = key_text
        yaml_path = self._settings_dataset_use_case.resolve_existing_yaml_path(
            yaml_path=self.yaml_edit.text().strip(),
        )
        return SettingsDialogSubmission(
            yaml_path=yaml_path,
            api_keys=api_keys,
            language=self.lang_combo.currentData(),
            theme=self.theme_combo.currentData(),
            ui_scale=self.scale_combo.currentData(),
            open_api_enabled=self.open_api_enabled.isChecked(),
            open_api_port=self.open_api_port.value(),
            ai_provider=provider,
            ai_model=self.ai_model_edit.currentText().strip() or default_model,
            ai_max_steps=self.ai_max_steps.value(),
            ai_thinking_enabled=self.ai_thinking_enabled.isChecked(),
            ai_custom_prompt=self.ai_custom_prompt.toPlainText().strip(),
        )

    def get_values(self):
        return self.get_submission().as_dict()



__all__ = ["SettingsDialog"]
