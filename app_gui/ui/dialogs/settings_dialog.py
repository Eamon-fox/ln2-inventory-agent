"""Settings dialog extracted from main window module."""

import os
import sys

from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_gui.application.ai_provider_catalog import (
    AI_PROVIDER_DEFAULTS,
    normalize_ai_provider,
)
from app_gui.application.custom_fields_use_case import CustomFieldsUseCase
from app_gui.application.settings_dialog_submission import SettingsDialogSubmission
from app_gui.application.settings_dataset_use_case import SettingsDatasetUseCase
from app_gui.application.settings_validation_use_case import SettingsValidationUseCase
from app_gui.application.open_api.contracts import LOCAL_OPEN_API_DEFAULT_PORT
from app_gui.error_localizer import localize_error
from app_gui.gui_config import DEFAULT_MAX_STEPS, MAX_AGENT_STEPS
from app_gui.i18n import t, tr
from app_gui.ui.icons import Icons, get_icon
from lib.inventory_paths import normalize_inventory_yaml_path as _normalize_inventory_yaml_path
from lib.position_fmt import box_to_display, pos_to_display
from lib.validators import format_validation_errors
from app_gui.version import (
    APP_VERSION,
    APP_RELEASE_URL,
    UPDATE_CHECK_URL as _GITHUB_API_LATEST,
    is_version_newer as _is_version_newer,
    resolve_platform_release_info,
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

        data_group = QGroupBox(tr("settings.data"))
        data_layout = QFormLayout(data_group)

        yaml_row = QHBoxLayout()
        self.yaml_edit = QLineEdit(self._config.get("yaml_path", ""))
        self._initial_yaml_path = self._normalize_yaml_path(
            self._config.get("yaml_path", "")
        )
        self.yaml_edit.setReadOnly(self._inventory_path_locked)
        self.yaml_new_btn = QPushButton(tr("main.new"))
        self.yaml_new_btn.setIcon(get_icon(Icons.FILE_PLUS))
        self.yaml_new_btn.setIconSize(QSize(14, 14))
        self.yaml_new_btn.setMinimumWidth(60)
        self.yaml_new_btn.clicked.connect(self._emit_create_new_dataset_request)
        yaml_row.addWidget(self.yaml_edit, 1)
        yaml_row.addWidget(self.yaml_new_btn)
        data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

        data_root_row = QHBoxLayout()
        self.data_root_edit = QLineEdit(self._config.get("data_root", ""))
        self.data_root_edit.setReadOnly(True)
        self.data_root_change_btn = QPushButton(tr("settings.changeDataRoot"))
        self.data_root_change_btn.clicked.connect(self._emit_change_data_root_request)
        self.data_root_change_btn.setEnabled(callable(self._on_change_data_root))
        data_root_row.addWidget(self.data_root_edit, 1)
        data_root_row.addWidget(self.data_root_change_btn)
        data_layout.addRow(tr("settings.dataRoot"), data_root_row)

        self.dataset_switch_combo = None
        self.dataset_rename_btn = None
        self.dataset_delete_btn = None
        switch_row = QHBoxLayout()
        self.dataset_switch_combo = _NoWheelComboBox()
        self.dataset_switch_combo.currentIndexChanged.connect(self._on_dataset_switch_changed)
        switch_row.addWidget(self.dataset_switch_combo, 1)
        self.dataset_rename_btn = QPushButton(tr("settings.renameDataset"))
        self.dataset_rename_btn.clicked.connect(self._emit_rename_dataset_request)
        self.dataset_rename_btn.setEnabled(callable(self._on_rename_dataset))
        switch_row.addWidget(self.dataset_rename_btn)
        self.dataset_delete_btn = QPushButton(tr("settings.deleteDataset"))
        self.dataset_delete_btn.clicked.connect(self._emit_delete_dataset_request)
        self.dataset_delete_btn.setEnabled(callable(self._on_delete_dataset))
        switch_row.addWidget(self.dataset_delete_btn)
        data_layout.addRow(tr("settings.datasetSwitch"), switch_row)
        self._refresh_dataset_choices(selected_yaml=self.yaml_edit.text().strip())

        lock_hint = QLabel(tr("settings.inventoryFileLockedHint"))
        lock_hint.setProperty("role", "settingsHint")
        lock_hint.setWordWrap(True)
        data_layout.addRow("", lock_hint)

        data_root_hint = QLabel(tr("settings.dataRootHint"))
        data_root_hint.setProperty("role", "settingsHint")
        data_root_hint.setWordWrap(True)
        data_layout.addRow("", data_root_hint)

        tool_row = QHBoxLayout()
        cf_btn = QPushButton(tr("main.manageCustomFields"))
        cf_btn.clicked.connect(self._open_custom_fields_editor)
        tool_row.addWidget(cf_btn)

        box_btn = QPushButton(tr("main.manageBoxes"))
        box_btn.clicked.connect(self._open_manage_boxes)
        tool_row.addWidget(box_btn)

        import_btn = QPushButton(tr("main.importExistingDataTitle"))
        import_btn.setToolTip(tr("main.importExistingDataHint"))
        import_btn.clicked.connect(self._open_import_journey)
        tool_row.addWidget(import_btn)

        self.export_csv_btn = QPushButton(tr("operations.exportFullCsv"))
        self.export_csv_btn.setIcon(get_icon(Icons.DOWNLOAD))
        self.export_csv_btn.setIconSize(QSize(14, 14))
        self.export_csv_btn.setToolTip(tr("operations.exportFullCsvHint"))
        self.export_csv_btn.clicked.connect(self._open_export_inventory_csv)
        self.export_csv_btn.setEnabled(callable(self._on_export_inventory_csv))
        tool_row.addWidget(self.export_csv_btn)

        tool_row.addStretch()
        data_layout.addRow("", tool_row)

        content_layout.addWidget(data_group)

        ai_group = QGroupBox(tr("settings.ai"))
        ai_layout = QFormLayout(ai_group)

        api_keys_config = self._config.get("api_keys", {})
        self._api_key_edits = {}
        self._api_key_lock_buttons = {}
        for provider_id, cfg in AI_PROVIDER_DEFAULTS.items():
            key_row, key_edit, lock_btn = self._build_locked_api_key_row(
                api_keys_config.get(provider_id, "")
            )
            self._api_key_edits[provider_id] = key_edit
            self._api_key_lock_buttons[provider_id] = lock_btn
            help_url = str(cfg.get("help_url") or "").strip()
            if help_url:
                label_widget = QLabel(
                    f'<a href="{help_url}">{cfg["display_name"]}</a> ({cfg["env_key"]}):'
                )
                label_widget.setOpenExternalLinks(True)
            else:
                label_widget = QLabel(f'{cfg["display_name"]} ({cfg["env_key"]}):')
            ai_layout.addRow(label_widget, key_row)

        api_hint_text = str(tr("settings.apiKeyHint") or "").strip()
        if api_hint_text:
            api_hint = QLabel(api_hint_text)
            api_hint.setProperty("role", "settingsHint")
            api_hint.setWordWrap(True)
            ai_layout.addRow("", api_hint)

        ai_advanced = self._config.get("ai", {})
        current_provider = normalize_ai_provider(ai_advanced.get("provider"))
        self.ai_provider_combo = _NoWheelComboBox()
        for provider_id, cfg in AI_PROVIDER_DEFAULTS.items():
            self.ai_provider_combo.addItem(cfg["display_name"], provider_id)
        idx = self.ai_provider_combo.findData(current_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        ai_layout.addRow(tr("settings.aiProvider"), self.ai_provider_combo)

        provider_cfg = AI_PROVIDER_DEFAULTS[current_provider]
        default_model = ai_advanced.get("model") or provider_cfg["model"]
        self.ai_model_edit = _NoWheelComboBox()
        self.ai_model_edit.setEditable(True)
        self.ai_model_edit.setInsertPolicy(QComboBox.NoInsert)
        self.ai_model_edit.setObjectName("settingsModelPreview")
        self._refresh_model_options(current_provider, selected_model=default_model)
        ai_layout.addRow(tr("settings.aiModel"), self.ai_model_edit)

        self.ai_max_steps = _NoWheelSpinBox()
        self.ai_max_steps.setRange(1, MAX_AGENT_STEPS)
        self.ai_max_steps.setValue(ai_advanced.get("max_steps", DEFAULT_MAX_STEPS))
        ai_layout.addRow(tr("settings.aiMaxSteps"), self.ai_max_steps)

        self.ai_thinking_enabled = QCheckBox()
        self.ai_thinking_enabled.setChecked(ai_advanced.get("thinking_enabled", True))
        ai_layout.addRow(tr("settings.aiThinking"), self.ai_thinking_enabled)

        self.ai_custom_prompt = _NoWheelTextEdit()
        self.ai_custom_prompt.setPlaceholderText(tr("settings.customPromptPlaceholder"))
        self.ai_custom_prompt.setPlainText(ai_advanced.get("custom_prompt", ""))
        self.ai_custom_prompt.setMaximumHeight(100)
        ai_layout.addRow(tr("settings.customPrompt"), self.ai_custom_prompt)

        custom_prompt_hint = QLabel(tr("settings.customPromptHint"))
        custom_prompt_hint.setProperty("role", "settingsHint")
        custom_prompt_hint.setWordWrap(True)
        ai_layout.addRow("", custom_prompt_hint)

        content_layout.addWidget(ai_group)

        local_api_group = QGroupBox(tr("settings.localApi"))
        local_api_layout = QFormLayout(local_api_group)

        open_api_cfg = self._config.get("open_api", {})
        self.open_api_enabled = QCheckBox()
        self.open_api_enabled.setChecked(bool(open_api_cfg.get("enabled", False)))
        local_api_layout.addRow(tr("settings.localApiEnabled"), self.open_api_enabled)

        self.open_api_port = _NoWheelSpinBox()
        self.open_api_port.setRange(1024, 65535)
        try:
            open_api_port = int(open_api_cfg.get("port", LOCAL_OPEN_API_DEFAULT_PORT))
        except Exception:
            open_api_port = LOCAL_OPEN_API_DEFAULT_PORT
        if open_api_port <= 0:
            open_api_port = LOCAL_OPEN_API_DEFAULT_PORT
        self.open_api_port.setValue(open_api_port)
        local_api_layout.addRow(tr("settings.localApiPort"), self.open_api_port)

        local_api_hint = QLabel(tr("settings.localApiHint"))
        local_api_hint.setProperty("role", "settingsHint")
        local_api_hint.setWordWrap(True)
        local_api_layout.addRow("", local_api_hint)

        content_layout.addWidget(local_api_group)

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

        self.lang_combo = _NoWheelComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        current_lang = self._config.get("language", "en")
        idx = self.lang_combo.findData(current_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        row_layout.addWidget(self.lang_combo)

        theme_label = QLabel(tr("settings.theme"))
        theme_label.setProperty("role", "inlineFormLabel")
        row_layout.addWidget(theme_label)

        self.theme_combo = _NoWheelComboBox()
        self.theme_combo.addItem(tr("settings.themeAuto"), "auto")
        self.theme_combo.addItem(tr("settings.themeDark"), "dark")
        self.theme_combo.addItem(tr("settings.themeLight"), "light")
        current_theme = self._config.get("theme", "dark")
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        row_layout.addWidget(self.theme_combo)

        scale_label = QLabel(tr("settings.uiScale"))
        scale_label.setProperty("role", "inlineFormLabel")
        row_layout.addWidget(scale_label)

        self.scale_combo = _NoWheelComboBox()
        self.scale_combo.addItem("100%", 1.0)
        self.scale_combo.addItem("125%", 1.25)
        self.scale_combo.addItem("150%", 1.5)
        # Removed 175% and 200% - too extreme, causes display issues
        current_scale = self._config.get("ui_scale", 1.0)
        # Cap scale at 1.5 if config has higher value
        if current_scale > 1.5:
            current_scale = 1.5
        idx = self.scale_combo.findData(current_scale)
        if idx >= 0:
            self.scale_combo.setCurrentIndex(idx)
        row_layout.addWidget(self.scale_combo)

        row_layout.addStretch()

        preferences_layout.addRow(prefs_row)

        content_layout.addWidget(preferences_group)

        about_group = QGroupBox(tr("settings.about"))
        about_layout = QVBoxLayout(about_group)
        about_label = QLabel(
            f'{tr("app.title")}  v{self._app_version}<br>'
            f'{tr("settings.aboutDesc")}<br><br>'
            f'{tr("settings.downloadPageLabel")}: <a href="{self._app_release_url}">'
            f'SnowFox</a>'
        )
        about_label.setOpenExternalLinks(True)
        about_label.setWordWrap(True)
        about_label.setObjectName("settingsAboutLabel")
        about_layout.addWidget(about_label)

        self._check_update_btn = QPushButton(tr("settings.checkUpdate"))
        self._check_update_btn.setMinimumWidth(140)
        self._check_update_btn.clicked.connect(self._on_check_update)
        about_layout.addWidget(self._check_update_btn)

        donate_path = os.path.join(self._root_dir, "app_gui", "assets", "donate.png")
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

        content_layout.addWidget(about_group)

        content_layout.addStretch()

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

    def _refresh_dataset_choices(self, selected_yaml=""):
        if self.dataset_switch_combo is None:
            return

        combo = self.dataset_switch_combo
        items, selected_idx = self._settings_dataset_use_case.build_dataset_choices(
            selected_yaml=selected_yaml or self.yaml_edit.text().strip(),
        )

        combo.blockSignals(True)
        combo.clear()
        for name, yaml_path in items:
            combo.addItem(name, yaml_path)

        combo.setEnabled(bool(items))
        if self.dataset_rename_btn is not None:
            self.dataset_rename_btn.setEnabled(bool(items) and callable(self._on_rename_dataset))
        if self.dataset_delete_btn is not None:
            self.dataset_delete_btn.setEnabled(bool(items) and callable(self._on_delete_dataset))
        if items:
            combo.setCurrentIndex(selected_idx)
            selected_path = combo.currentData()
            if selected_path:
                self.yaml_edit.setText(self._normalize_yaml_path(selected_path))
        combo.blockSignals(False)

    def _on_dataset_switch_changed(self):
        if self.dataset_switch_combo is None:
            return
        selected_path = self.dataset_switch_combo.currentData()
        if not selected_path:
            return
        self.yaml_edit.setText(self._normalize_yaml_path(selected_path))

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
        if not callable(self._on_create_new_dataset):
            return
        # Create + switch immediately so users keep the newly created dataset
        # even if they close Settings without pressing OK.
        new_path = self._on_create_new_dataset(update_window=True)
        if new_path:
            self.yaml_edit.setText(self._normalize_yaml_path(new_path))
            self._refresh_dataset_choices(selected_yaml=new_path)

    def _emit_change_data_root_request(self):
        if not callable(self._on_change_data_root):
            return
        result = self._on_change_data_root(self.data_root_edit.text().strip())
        if not isinstance(result, dict):
            return
        new_root = str(result.get("data_root") or "").strip()
        new_yaml = str(result.get("yaml_path") or "").strip()
        if new_root:
            self.data_root_edit.setText(new_root)
            self._config["data_root"] = new_root
        if new_yaml:
            self.yaml_edit.setText(self._normalize_yaml_path(new_yaml))
            self._initial_yaml_path = self._normalize_yaml_path(new_yaml)
        self._refresh_dataset_choices(selected_yaml=new_yaml or self.yaml_edit.text().strip())

    def _emit_rename_dataset_request(self):
        if not callable(self._on_rename_dataset):
            return

        current_yaml = self._normalize_yaml_path(self.yaml_edit.text().strip())
        if not current_yaml:
            return

        default_name = self._settings_dataset_use_case.managed_dataset_name(
            yaml_path=current_yaml,
        )
        new_name, ok = QInputDialog.getText(
            self,
            tr("settings.renameDataset"),
            tr("settings.renameDatasetPrompt"),
            text=default_name,
        )
        if not ok:
            return

        try:
            new_path = self._on_rename_dataset(current_yaml, str(new_name or ""))
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("settings.renameDataset"),
                t("settings.renameDatasetFailed", error=str(exc)),
            )
            return

        if new_path:
            self.yaml_edit.setText(self._normalize_yaml_path(new_path))
            self._refresh_dataset_choices(selected_yaml=new_path)

    def _confirm_phrase_dialog(self, *, title, prompt_text, phrase, strip_input=False):
        confirm_dlg = QDialog(self)
        confirm_dlg.setWindowTitle(title)
        confirm_layout = QVBoxLayout(confirm_dlg)

        confirm_label = QLabel(prompt_text)
        confirm_label.setWordWrap(True)
        confirm_layout.addWidget(confirm_label)

        confirm_input = _NoPasteLineEdit()
        confirm_input.setPlaceholderText(phrase)
        confirm_layout.addWidget(confirm_input)

        confirm_buttons = QDialogButtonBox()
        ok_btn = QPushButton(tr("common.ok"))
        ok_btn.setEnabled(False)
        ok_btn.clicked.connect(confirm_dlg.accept)
        confirm_buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
        cancel_btn = QPushButton(tr("common.cancel"))
        cancel_btn.clicked.connect(confirm_dlg.reject)
        confirm_buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
        confirm_layout.addWidget(confirm_buttons)

        def _matches(text):
            candidate = str(text or "")
            if strip_input:
                candidate = candidate.strip()
            return candidate == phrase

        confirm_input.textChanged.connect(lambda txt: ok_btn.setEnabled(_matches(txt)))
        if confirm_dlg.exec() != QDialog.Accepted:
            return False
        return _matches(confirm_input.text())

    def _emit_delete_dataset_request(self):
        if not callable(self._on_delete_dataset):
            return

        current_yaml = self._normalize_yaml_path(self.yaml_edit.text().strip())
        if not current_yaml:
            return

        dataset_name = self._settings_dataset_use_case.managed_dataset_name(
            yaml_path=current_yaml,
        )

        if not self._confirm_delete_dataset_initial(dataset_name):
            return

        confirm_phrase = t("settings.deleteDatasetPhrase", name=dataset_name)
        phrase_prompt = t("settings.deleteDatasetPhrasePrompt", phrase=confirm_phrase)
        if not self._confirm_phrase_dialog(
            title=tr("settings.deleteDataset"),
            prompt_text=phrase_prompt,
            phrase=confirm_phrase,
            strip_input=False,
        ):
            return

        if not self._confirm_delete_dataset_final(dataset_name):
            return

        try:
            new_path = self._on_delete_dataset(current_yaml)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("settings.deleteDataset"),
                t("settings.deleteDatasetFailed", error=str(exc)),
            )
            return

        if new_path:
            self.yaml_edit.setText(self._normalize_yaml_path(new_path))
            self._refresh_dataset_choices(selected_yaml=new_path)

    def _confirm_delete_dataset_initial(self, dataset_name):
        first_confirm = QMessageBox(self)
        first_confirm.setIcon(QMessageBox.Warning)
        first_confirm.setWindowTitle(tr("settings.deleteDataset"))
        first_confirm.setText(t("settings.deleteDatasetPrompt", name=dataset_name))
        first_confirm.setInformativeText(tr("settings.deleteDatasetPromptDetail"))
        delete_btn = first_confirm.addButton(tr("settings.deleteDatasetAction"), QMessageBox.DestructiveRole)
        first_confirm.addButton(tr("common.cancel"), QMessageBox.RejectRole)
        first_confirm.setDefaultButton(first_confirm.button(QMessageBox.Cancel))
        first_confirm.exec()
        return first_confirm.clickedButton() == delete_btn

    def _confirm_delete_dataset_final(self, dataset_name):
        final_confirm = QMessageBox(self)
        final_confirm.setIcon(QMessageBox.Critical)
        final_confirm.setWindowTitle(tr("settings.deleteDataset"))
        final_confirm.setText(t("settings.deleteDatasetFinalPrompt", name=dataset_name))
        final_delete_btn = final_confirm.addButton(tr("settings.deleteDatasetAction"), QMessageBox.DestructiveRole)
        final_confirm.addButton(tr("common.cancel"), QMessageBox.RejectRole)
        final_confirm.setDefaultButton(final_confirm.button(QMessageBox.Cancel))
        final_confirm.exec()
        return final_confirm.clickedButton() == final_delete_btn

    def _on_check_update(self):
        """Manually check for updates from OSS."""
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText(tr("settings.checking"))
        import threading

        def _fetch():
            try:
                import urllib.request
                import json
                req = urllib.request.Request(
                    self._github_api_latest,
                    headers={"User-Agent": "SnowFox"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = str(data.get("version", "")).strip()
                body = str(data.get("release_notes", ""))[:200]
                release_info = resolve_platform_release_info(data)
                download_url = str(release_info.get("download_url", ""))
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_check_update_result",
                    Qt.QueuedConnection,
                    Q_ARG(str, latest_tag),
                    Q_ARG(str, body),
                    Q_ARG(str, download_url),
                )
            except Exception as e:
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_check_update_result",
                    Qt.QueuedConnection,
                    Q_ARG(str, ""),
                    Q_ARG(str, str(e)),
                    Q_ARG(str, ""),
                )

        threading.Thread(target=_fetch, daemon=True).start()

    @Slot(str, str, str)
    def _on_check_update_result(self, latest_tag, info, download_url):
        """Handle update check result in main thread."""
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText(tr("settings.checkUpdate"))
        if not latest_tag:
            QMessageBox.warning(self, tr("settings.checkUpdate"),
                                t("settings.checkUpdateFailed", error=info))
            return
        if _is_version_newer(latest_tag, self._app_version):
            release_info = resolve_platform_release_info({"download_url": download_url})
            update_label = (
                tr("main.newReleaseUpdate")
                if bool(release_info.get("auto_update"))
                else tr("main.newReleaseDownload")
            )
            box = QMessageBox(self)
            box.setWindowTitle(tr("settings.checkUpdate"))
            box.setText(t("settings.newVersionAvailable", version=latest_tag, notes=info))
            box.setIcon(QMessageBox.Information)
            update_btn = box.addButton(update_label, QMessageBox.AcceptRole)
            box.addButton(tr("main.newReleaseLater"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() == update_btn:
                main_window = self.parent()
                if hasattr(main_window, "_startup_flow"):
                    self.close()
                    main_window._startup_flow.start_automatic_update(
                        latest_tag, info, download_url)
        else:
            QMessageBox.information(
                self, tr("settings.checkUpdate"),
                tr("settings.alreadyLatest"))

    @staticmethod
    def _format_removed_field_preview_value(value, *, max_length=80):
        text = str(value)
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        if len(text) > max_length:
            return f"{text[: max_length - 3]}..."
        return text

    @staticmethod
    def _format_removed_field_preview_box(box, layout):
        if box in (None, ""):
            return "?"
        try:
            return box_to_display(box, layout)
        except Exception:
            return str(box)

    @staticmethod
    def _format_removed_field_preview_position(position, layout):
        if position in (None, ""):
            return "?"
        try:
            return pos_to_display(int(position), layout)
        except Exception:
            return str(position)

    def _format_removed_field_preview_entry(self, entry, *, layout):
        record_id = entry.record_id
        if record_id in (None, ""):
            record_id = "?"
        return t(
            "main.cfRemoveDataPreviewItem",
            id=record_id,
            box=self._format_removed_field_preview_box(entry.box, layout),
            position=self._format_removed_field_preview_position(entry.position, layout),
            value=self._format_removed_field_preview_value(entry.value),
        )

    def _format_removed_field_preview_summary(self, previews, *, layout):
        blocks = []
        for preview in previews:
            lines = [
                t(
                    "main.cfRemoveDataPreviewField",
                    field=preview.field_key,
                    count=preview.affected_count,
                )
            ]
            lines.extend(
                self._format_removed_field_preview_entry(entry, layout=layout)
                for entry in preview.samples
            )
            if preview.hidden_count:
                lines.append(
                    t("main.cfRemoveDataPreviewMore", count=preview.hidden_count)
                )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _format_removed_field_preview_details(self, previews, *, layout):
        blocks = []
        for preview in previews:
            lines = [
                t(
                    "main.cfRemoveDataPreviewField",
                    field=preview.field_key,
                    count=preview.affected_count,
                )
            ]
            lines.extend(
                self._format_removed_field_preview_entry(entry, layout=layout)
                for entry in preview.entries
            )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _open_custom_fields_editor(self):
        yaml_path = self.yaml_edit.text().strip()
        if not yaml_path or not os.path.isfile(yaml_path):
            QMessageBox.warning(self, tr("common.info"),
                                t("main.fileNotFound", path=yaml_path))
            return

        load_result = self._custom_fields_use_case.load_editor_state(yaml_path=yaml_path)
        editor_state = load_result.state
        meta = editor_state.meta
        unsupported_issue = load_result.unsupported_issue
        if unsupported_issue:
            QMessageBox.warning(
                self,
                tr("main.customFieldsTitle"),
                localize_error(
                    unsupported_issue.get("error_code"),
                    unsupported_issue.get("message"),
                    details=unsupported_issue.get("details"),
                ),
            )
            return

        dialog_cls = self._custom_fields_dialog_cls
        if dialog_cls is None:
            from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog as dialog_cls
        dlg = dialog_cls(
            self,
            custom_fields=editor_state.existing_fields,
            display_key=editor_state.current_display_key,
            color_key=editor_state.current_color_key,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        new_fields = dlg.get_custom_fields()
        new_dk = dlg.get_display_key()
        new_ck = dlg.get_color_key()

        draft = self._custom_fields_use_case.prepare_update(
            state=editor_state,
            new_fields=new_fields,
            requested_display_key=new_dk,
            requested_color_key=new_ck,
        )

        if draft.blocked_renames:
            sample_lines = []
            for item in draft.blocked_renames[:20]:
                reason = str(item.get("reason") or "").strip()
                if reason == "fixed_system_field":
                    kind = "fixed system field"
                else:
                    kind = "structural field"
                sample_lines.append(
                    f"{item.get('from_key', '?')} -> {item.get('to_key', '?')}: "
                    f"target is a {kind}"
                )
            hidden_count = len(draft.blocked_renames) - len(sample_lines)
            detail_text = "\n".join(sample_lines)
            if hidden_count > 0:
                detail_text += f"\n... and {hidden_count} more blocked rename(s)"
            QMessageBox.warning(
                self,
                tr("main.customFieldsTitle"),
                (
                    "Field rename blocked. Fixed/system field names cannot be used as "
                    "rename targets.\n\n"
                    f"{detail_text}\n\n"
                    "Please choose a different custom field key."
                ),
            )
            return

        if draft.rename_conflicts:
            sample_lines = []
            for item in draft.rename_conflicts[:20]:
                sample_lines.append(
                    f"id={item.get('record_id', '?')}: "
                    f"{item['from_key']}={item['from_value']!r} vs {item['to_key']}={item['to_value']!r}"
                )
            hidden_count = len(draft.rename_conflicts) - len(sample_lines)
            detail_text = "\n".join(sample_lines)
            if hidden_count > 0:
                detail_text += f"\n... and {hidden_count} more conflict(s)"
            QMessageBox.warning(
                self,
                tr("main.customFieldsTitle"),
                (
                    "Field rename conflict detected. "
                    "The target field already contains different values.\n\n"
                    f"{detail_text}\n\n"
                    "Please resolve conflicts in data before renaming."
                ),
            )
            return

        removed_data_cleaned = False
        removed_records_count = 0
        if draft.removed_field_previews:
            box_layout = meta.get("box_layout") if isinstance(meta.get("box_layout"), dict) else None
            names = ", ".join(preview.field_key for preview in draft.removed_field_previews)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle(tr("main.customFieldsTitle"))
            msg.setText(t("main.cfRemoveDataPrompt", fields=names))
            msg.setInformativeText(
                self._format_removed_field_preview_summary(
                    draft.removed_field_previews,
                    layout=box_layout,
                )
            )
            if any(preview.hidden_count for preview in draft.removed_field_previews):
                msg.setDetailedText(
                    self._format_removed_field_preview_details(
                        draft.removed_field_previews,
                    layout=box_layout,
                )
            )
            btn_clean = _ProgrammaticClickButton(tr("main.cfRemoveDataClean"), msg)
            btn_cancel = _ProgrammaticClickButton(tr("common.cancel"), msg)
            msg.addButton(btn_clean, QMessageBox.DestructiveRole)
            msg.addButton(btn_cancel, QMessageBox.RejectRole)
            msg.setDefaultButton(btn_cancel)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked != btn_clean:
                return

            confirm_phrase = "DELETE"
            if not self._confirm_phrase_dialog(
                title=tr("main.customFieldsTitle"),
                prompt_text=t("main.cfRemoveDataConfirm", phrase=confirm_phrase),
                phrase=confirm_phrase,
                strip_input=True,
            ):
                return
            removed_data_cleaned = True

        commit_result = self._custom_fields_use_case.commit_update(
            yaml_path=yaml_path,
            state=editor_state,
            draft=draft,
            remove_removed_field_data=removed_data_cleaned,
        )
        if commit_result.meta_errors:
            self._show_validation_blocked_result(
                self._validation_failed_result(
                    commit_result.meta_errors,
                    prefix="Validation failed",
                )
            )
            return

        if not commit_result.ok:
            QMessageBox.warning(
                self,
                tr("main.customFieldsTitle"),
                str(commit_result.message or "Failed to save custom fields."),
            )
            return

        self._notify_data_changed(yaml_path=yaml_path, meta=draft.pending_meta)

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
        provider = normalize_ai_provider(self.ai_provider_combo.currentData())
        cfg = AI_PROVIDER_DEFAULTS[provider]
        self._refresh_model_options(provider, selected_model=cfg["model"])

    @staticmethod
    def _provider_models(provider):
        normalized_provider = normalize_ai_provider(provider)
        cfg = AI_PROVIDER_DEFAULTS[normalized_provider]
        models = []
        seen = set()
        for raw in cfg.get("models") or []:
            text = str(raw or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            models.append(text)
        default_model = str(cfg.get("model") or "").strip()
        if default_model:
            key = default_model.casefold()
            if key not in seen:
                models.append(default_model)
        return models, default_model

    def _refresh_model_options(self, provider, selected_model=None):
        models, default_model = self._provider_models(provider)
        target_model = str(selected_model or "").strip() or default_model

        self.ai_model_edit.blockSignals(True)
        self.ai_model_edit.clear()
        for model in models:
            self.ai_model_edit.addItem(model, model)
        if target_model and self.ai_model_edit.findText(target_model) < 0:
            self.ai_model_edit.addItem(target_model, target_model)
        idx = self.ai_model_edit.findText(target_model)
        if idx >= 0:
            self.ai_model_edit.setCurrentIndex(idx)
        elif target_model:
            self.ai_model_edit.setEditText(target_model)
        self.ai_model_edit.setPlaceholderText(default_model)
        self.ai_model_edit.blockSignals(False)

    def _build_locked_api_key_row(self, initial_value):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        key_edit = QLineEdit(initial_value or "")
        key_edit.setEchoMode(QLineEdit.Password)
        key_edit.setPlaceholderText("sk-...")
        key_edit.setReadOnly(True)
        row_layout.addWidget(key_edit, 1)

        lock_btn = QPushButton("\U0001F512")
        lock_btn.setObjectName("inlineLockBtn")
        lock_btn.setFixedSize(16, 16)
        lock_btn.setToolTip(tr("operations.edit"))
        lock_btn.clicked.connect(
            lambda _checked=False, edit=key_edit, btn=lock_btn: self._toggle_api_key_lock(edit, btn)
        )
        row_layout.addWidget(lock_btn)

        return row_widget, key_edit, lock_btn

    @staticmethod
    def _toggle_api_key_lock(key_edit, lock_btn):
        if key_edit.isReadOnly():
            key_edit.setReadOnly(False)
            key_edit.setEchoMode(QLineEdit.Normal)
            lock_btn.setText("\U0001F513")
            key_edit.setFocus()
            key_edit.selectAll()
            return

        key_edit.setReadOnly(True)
        key_edit.setEchoMode(QLineEdit.Password)
        lock_btn.setText("\U0001F512")

    def get_submission(self):
        provider = normalize_ai_provider(self.ai_provider_combo.currentData())
        provider_cfg = AI_PROVIDER_DEFAULTS[provider]
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
            ai_model=self.ai_model_edit.currentText().strip() or provider_cfg["model"],
            ai_max_steps=self.ai_max_steps.value(),
            ai_thinking_enabled=self.ai_thinking_enabled.isChecked(),
            ai_custom_prompt=self.ai_custom_prompt.toPlainText().strip(),
        )

    def get_values(self):
        return self.get_submission().as_dict()



__all__ = ["SettingsDialog"]
