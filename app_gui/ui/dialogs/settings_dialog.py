"""Settings dialog extracted from main window module."""

import os
import sys

import yaml
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

from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS
from app_gui.gui_config import DEFAULT_MAX_STEPS, MAX_AGENT_STEPS
from app_gui.i18n import t, tr
from app_gui.ui.icons import Icons, get_icon
from lib.inventory_paths import (
    assert_allowed_inventory_yaml_path,
    list_managed_datasets,
    managed_dataset_name_from_yaml_path,
)
from lib.import_acceptance import validate_candidate_yaml
from lib.import_validation_core import validate_inventory_document
from lib.validators import format_validation_errors
from lib.yaml_ops import load_yaml

APP_VERSION = "1.2.7"
APP_RELEASE_URL = "https://github.com/Eamon-fox/snowfox/releases"
_GITHUB_API_LATEST = "https://snowfox-release.oss-cn-beijing.aliyuncs.com/latest.json"

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _parse_version(v: str) -> tuple:
    try:
        normalized = str(v or "").strip().lstrip("vV")
        return tuple(int(x) for x in normalized.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _is_version_newer(new_version: str, old_version: str) -> bool:
    return _parse_version(new_version) > _parse_version(old_version)


def _normalize_inventory_yaml_path(path_text) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    return os.path.abspath(raw)


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


class SettingsDialog(QDialog):
    """Enhanced Settings dialog with sections and help text."""

    def __init__(
        self,
        parent=None,
        config=None,
        on_create_new_dataset=None,
        on_rename_dataset=None,
        on_delete_dataset=None,
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
        self.yaml_edit.setReadOnly(self._inventory_path_locked)
        self.yaml_new_btn = QPushButton(tr("main.new"))
        self.yaml_new_btn.setIcon(get_icon(Icons.FILE_PLUS))
        self.yaml_new_btn.setIconSize(QSize(14, 14))
        self.yaml_new_btn.setMinimumWidth(60)
        self.yaml_new_btn.clicked.connect(self._emit_create_new_dataset_request)
        yaml_row.addWidget(self.yaml_edit, 1)
        yaml_row.addWidget(self.yaml_new_btn)
        data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

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
        for provider_id, cfg in PROVIDER_DEFAULTS.items():
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
        current_provider = ai_advanced.get("provider") or DEFAULT_PROVIDER
        self.ai_provider_combo = _NoWheelComboBox()
        for provider_id, cfg in PROVIDER_DEFAULTS.items():
            self.ai_provider_combo.addItem(cfg["display_name"], provider_id)
        idx = self.ai_provider_combo.findData(current_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        ai_layout.addRow(tr("settings.aiProvider"), self.ai_provider_combo)

        provider_cfg = PROVIDER_DEFAULTS.get(current_provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
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
            f'GitHub: <a href="{self._app_release_url}">'
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
        path = self._normalize_yaml_path(path_text)
        if not path or os.path.isdir(path):
            return False
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in {".yaml", ".yml"}:
            return False
        try:
            assert_allowed_inventory_yaml_path(path, must_exist=True)
        except Exception:
            return False
        return True

    def _refresh_yaml_path_validity(self):
        if not hasattr(self, "_ok_button") or self._ok_button is None:
            return
        self._ok_button.setEnabled(self._is_valid_inventory_file_path(self.yaml_edit.text().strip()))

    def _refresh_dataset_choices(self, selected_yaml=""):
        if self.dataset_switch_combo is None:
            return

        rows = list_managed_datasets()
        combo = self.dataset_switch_combo
        combo.blockSignals(True)
        combo.clear()
        for row in rows:
            name = str(row.get("name") or "")
            yaml_path = str(row.get("yaml_path") or "")
            combo.addItem(name, yaml_path)

        combo.setEnabled(bool(rows))
        if self.dataset_rename_btn is not None:
            self.dataset_rename_btn.setEnabled(bool(rows) and callable(self._on_rename_dataset))
        if self.dataset_delete_btn is not None:
            self.dataset_delete_btn.setEnabled(bool(rows) and callable(self._on_delete_dataset))
        current_yaml = self._normalize_yaml_path(selected_yaml or self.yaml_edit.text().strip())
        if rows:
            idx = combo.findData(current_yaml)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
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
    def _validate_inventory_payload_strict(data):
        """Validate an in-memory inventory payload with strict warning blocking."""
        errors, warnings = validate_inventory_document(data)
        if warnings:
            errors.extend([f"Warning treated as error: {item}" for item in warnings])
        if errors:
            return {
                "ok": False,
                "message": format_validation_errors(errors, prefix="Import validation failed"),
                "report": {
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "errors": list(errors),
                    "warnings": list(warnings),
                },
            }
        return {
            "ok": True,
            "message": "Validation passed.",
            "report": {
                "error_count": 0,
                "warning_count": len(warnings),
                "errors": [],
                "warnings": list(warnings),
            },
        }

    def accept(self):
        """Block saving settings when selected dataset YAML fails strict validation."""
        yaml_path = self._normalize_yaml_path(self.yaml_edit.text().strip())
        if self._is_valid_inventory_file_path(yaml_path):
            result = validate_candidate_yaml(yaml_path, fail_on_warnings=True)
            if not result.get("ok"):
                report_text = self._render_validation_report(result.get("report") or {})
                message = t(
                    "main.datasetYamlValidationBlocked",
                    message=result.get("message") or tr("main.importValidationFailed"),
                )
                if report_text:
                    message += "\n\n" + report_text
                message += "\n\n" + tr("main.datasetYamlValidationHint")
                QMessageBox.warning(self, tr("main.importValidatedTitle"), message)
                return
        super().accept()

    def _notify_data_changed(self, *, yaml_path=None, meta=None):
        """Notify parent window after metadata edits (best-effort backward compatible)."""
        if not callable(self._on_data_changed):
            return
        try:
            self._on_data_changed(yaml_path=yaml_path, meta=meta)
        except TypeError:
            self._on_data_changed()

    def _emit_create_new_dataset_request(self):
        if not callable(self._on_create_new_dataset):
            return
        # Create + switch immediately so users keep the newly created dataset
        # even if they close Settings without pressing OK.
        new_path = self._on_create_new_dataset(update_window=True)
        if new_path:
            self.yaml_edit.setText(self._normalize_yaml_path(new_path))
            self._refresh_dataset_choices(selected_yaml=new_path)

    def _emit_rename_dataset_request(self):
        if not callable(self._on_rename_dataset):
            return

        current_yaml = self._normalize_yaml_path(self.yaml_edit.text().strip())
        if not current_yaml:
            return

        try:
            default_name = managed_dataset_name_from_yaml_path(current_yaml)
        except Exception:
            default_name = ""
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

        try:
            dataset_name = managed_dataset_name_from_yaml_path(current_yaml)
        except Exception:
            dataset_name = os.path.basename(os.path.dirname(current_yaml)) or current_yaml

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
                download_url = str(data.get("download_url", ""))
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
            box = QMessageBox(self)
            box.setWindowTitle(tr("settings.checkUpdate"))
            box.setText(t("settings.newVersionAvailable", version=latest_tag, notes=info))
            box.setIcon(QMessageBox.Information)
            update_btn = box.addButton(tr("main.newReleaseUpdate"), QMessageBox.AcceptRole)
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

    def _open_custom_fields_editor(self):
        yaml_path = self.yaml_edit.text().strip()
        if not yaml_path or not os.path.isfile(yaml_path):
            QMessageBox.warning(self, tr("common.info"),
                                t("main.fileNotFound", path=yaml_path))
            return

        try:
            data = load_yaml(yaml_path) or {}
        except Exception:
            data = {}

        meta = data.get("meta", {})
        from lib.custom_fields import get_effective_fields
        existing = get_effective_fields(meta)
        current_dk = meta.get("display_key")
        current_ck = meta.get("color_key")
        current_clo = meta.get("cell_line_options")
        current_cl_required = bool(meta.get("cell_line_required", True))

        dialog_cls = self._custom_fields_dialog_cls
        if dialog_cls is None:
            from app_gui.ui.dialogs.custom_fields_dialog import CustomFieldsDialog as dialog_cls
        dlg = dialog_cls(
            self,
            custom_fields=existing,
            display_key=current_dk,
            color_key=current_ck,
            cell_line_options=current_clo,
            cell_line_required=current_cl_required,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        new_fields = dlg.get_custom_fields()
        new_dk = dlg.get_display_key()
        new_ck = dlg.get_color_key()
        new_clo = dlg.get_cell_line_options()
        new_cl_required = dlg.get_cell_line_required()
        inventory = data.get("inventory") or []

        # --- Step 1: handle renames (old_key -> new_key) ---
        renames = {}  # old_key -> new_key
        for f in new_fields:
            orig = f.pop("_original_key", None)
            if orig:
                renames[orig] = f["key"]

        if renames and inventory:
            renames_with_data = {
                old: new for old, new in renames.items()
                if any(isinstance(r, dict) and r.get(old) is not None for r in inventory)
            }
            if renames_with_data:
                for rec in inventory:
                    if not isinstance(rec, dict):
                        continue
                    for old, new in renames_with_data.items():
                        if old in rec:
                            rec[new] = rec.pop(old)

        # --- Step 2: handle pure deletes ---
        new_keys = {f["key"] for f in new_fields}
        old_keys = {f["key"] for f in existing if isinstance(f, dict) and f.get("key")}
        # Keys that were renamed are not "deleted" - exclude them
        renamed_old_keys = set(renames.keys())
        removed_keys = old_keys - new_keys - renamed_old_keys

        if removed_keys and inventory:
            has_data = any(
                rec.get(k) is not None
                for rec in inventory
                for k in removed_keys
                if isinstance(rec, dict)
            )
            if has_data:
                names = ", ".join(sorted(removed_keys))
                msg = QMessageBox(self)
                msg.setWindowTitle(tr("main.customFieldsTitle"))
                msg.setText(t("main.cfRemoveDataPrompt", fields=names))
                btn_clean = msg.addButton(tr("main.cfRemoveDataClean"), QMessageBox.DestructiveRole)
                msg.addButton(QMessageBox.Cancel)
                msg.setDefaultButton(msg.button(QMessageBox.Cancel))
                msg.exec()
                clicked = msg.clickedButton()
                if clicked != btn_clean:
                    return  # cancelled

                # Second confirmation: require typing a phrase
                confirm_phrase = "DELETE"
                if not self._confirm_phrase_dialog(
                    title=tr("main.customFieldsTitle"),
                    prompt_text=t("main.cfRemoveDataConfirm", phrase=confirm_phrase),
                    phrase=confirm_phrase,
                    strip_input=True,
                ):
                    return  # cancelled

                for rec in inventory:
                    if isinstance(rec, dict):
                        for k in removed_keys:
                            rec.pop(k, None)

        # Build pending meta exactly as it would be saved.
        pending_meta = dict(meta)
        pending_meta["custom_fields"] = new_fields
        if new_dk:
            pending_meta["display_key"] = new_dk
        if new_ck:
            pending_meta["color_key"] = new_ck
        # Derive legacy cell_line keys from the custom_fields for backward compat
        if new_clo:
            pending_meta["cell_line_options"] = new_clo
        elif "cell_line_options" in pending_meta:
            del pending_meta["cell_line_options"]
        pending_meta["cell_line_required"] = bool(new_cl_required)

        # Run the same strict validation used by Settings OK to fail fast here.
        pending_data = dict(data)
        pending_data["meta"] = pending_meta
        pending_data["inventory"] = inventory
        validation = self._validate_inventory_payload_strict(pending_data)
        if not validation.get("ok"):
            report_text = self._render_validation_report(validation.get("report") or {})
            message = t(
                "main.datasetYamlValidationBlocked",
                message=validation.get("message") or tr("main.importValidationFailed"),
            )
            if report_text:
                message += "\n\n" + report_text
            message += "\n\n" + tr("main.datasetYamlValidationHint")
            QMessageBox.warning(self, tr("main.importValidatedTitle"), message)
            return

        # --- Step 3: save ---
        data["meta"] = pending_meta
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        self._notify_data_changed(yaml_path=yaml_path, meta=pending_meta)

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
        cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        self._refresh_model_options(provider, selected_model=cfg["model"])

    @staticmethod
    def _provider_models(provider):
        cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
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

    def get_values(self):
        provider = self.ai_provider_combo.currentData() or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        api_keys = {}
        for prov_id, edit in self._api_key_edits.items():
            key_text = edit.text().strip()
            if key_text:
                api_keys[prov_id] = key_text
        yaml_path = self._normalize_yaml_path(self.yaml_edit.text().strip())
        try:
            yaml_path = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
        except Exception:
            yaml_path = ""
        return {
            "yaml_path": yaml_path,
            "api_keys": api_keys,
            "language": self.lang_combo.currentData(),
            "theme": self.theme_combo.currentData(),
            "ui_scale": self.scale_combo.currentData(),
            "ai_provider": provider,
            "ai_model": self.ai_model_edit.currentText().strip() or provider_cfg["model"],
            "ai_max_steps": self.ai_max_steps.value(),
            "ai_thinking_enabled": self.ai_thinking_enabled.isChecked(),
            "ai_custom_prompt": self.ai_custom_prompt.toPlainText().strip(),
        }



__all__ = ["SettingsDialog"]
