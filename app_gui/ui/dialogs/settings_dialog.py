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
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS
from app_gui.gui_config import DEFAULT_MAX_STEPS
from app_gui.i18n import t, tr
from app_gui.ui.icons import Icons, get_icon
from lib.import_acceptance import validate_candidate_yaml
from lib.yaml_ops import load_yaml

APP_VERSION = "1.1.1"
APP_RELEASE_URL = "https://github.com/Eamon-fox/snowfox/releases"
_GITHUB_API_LATEST = "https://api.github.com/repos/Eamon-fox/snowfox/releases/latest"

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _is_version_newer(new_version: str, old_version: str) -> bool:
    return _parse_version(new_version) > _parse_version(old_version)


def _normalize_inventory_yaml_path(path_text) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    abs_path = os.path.abspath(raw)
    if ".demo." in os.path.basename(abs_path).lower():
        return abs_path
    return abs_path


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


class SettingsDialog(QDialog):
    """Enhanced Settings dialog with sections and help text."""

    def __init__(
        self,
        parent=None,
        config=None,
        on_create_new_dataset=None,
        on_manage_boxes=None,
        on_data_changed=None,
        *,
        app_version=APP_VERSION,
        app_release_url=APP_RELEASE_URL,
        github_api_latest=_GITHUB_API_LATEST,
        root_dir=None,
        export_task_bundle_dialog_cls=None,
        import_validated_yaml_dialog_cls=None,
        custom_fields_dialog_cls=None,
        normalize_yaml_path=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(750)
        self.setMinimumHeight(750)
        self._config = config or {}
        self._on_create_new_dataset = on_create_new_dataset
        self._on_manage_boxes = on_manage_boxes
        self._on_data_changed = on_data_changed
        self._app_version = str(app_version or APP_VERSION)
        self._app_release_url = str(app_release_url or APP_RELEASE_URL)
        self._github_api_latest = str(github_api_latest or _GITHUB_API_LATEST)
        self._root_dir = root_dir or ROOT
        self._export_task_bundle_dialog_cls = export_task_bundle_dialog_cls
        self._import_validated_yaml_dialog_cls = import_validated_yaml_dialog_cls
        self._custom_fields_dialog_cls = custom_fields_dialog_cls
        self._normalize_yaml_path = normalize_yaml_path or _normalize_inventory_yaml_path

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
        self.yaml_new_btn = QPushButton(tr("main.new"))
        self.yaml_new_btn.setIcon(get_icon(Icons.FILE_PLUS))
        self.yaml_new_btn.setIconSize(QSize(14, 14))
        self.yaml_new_btn.setMinimumWidth(60)
        self.yaml_new_btn.clicked.connect(self._emit_create_new_dataset_request)
        yaml_browse = QPushButton(tr("settings.browse"))
        yaml_browse.setIcon(get_icon(Icons.FOLDER_OPEN))
        yaml_browse.setIconSize(QSize(14, 14))
        yaml_browse.setMinimumWidth(60)
        yaml_browse.clicked.connect(self._browse_yaml)
        yaml_row.addWidget(self.yaml_edit, 1)
        yaml_row.addWidget(self.yaml_new_btn)
        yaml_row.addWidget(yaml_browse)
        data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

        yaml_hint = QLabel(tr("settings.inventoryFileHint"))
        yaml_hint.setProperty("role", "settingsHint")
        yaml_hint.setWordWrap(True)
        data_layout.addRow("", yaml_hint)

        tool_row = QHBoxLayout()
        cf_btn = QPushButton(tr("main.manageCustomFields"))
        cf_btn.clicked.connect(self._open_custom_fields_editor)
        tool_row.addWidget(cf_btn)

        box_btn = QPushButton(tr("main.manageBoxes"))
        box_btn.clicked.connect(self._open_manage_boxes)
        tool_row.addWidget(box_btn)

        export_bundle_btn = QPushButton(tr("main.exportTaskBundleTitle"))
        export_bundle_btn.clicked.connect(self._open_export_task_bundle)
        tool_row.addWidget(export_bundle_btn)

        import_validated_btn = QPushButton(tr("main.importValidatedTitle"))
        import_validated_btn.clicked.connect(self._open_import_validated_yaml)
        tool_row.addWidget(import_validated_btn)

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
            label = f'{cfg["display_name"]} ({cfg["env_key"]}):'
            ai_layout.addRow(label, key_row)
            if cfg.get("help_url"):
                help_label = QLabel(f'<a href="{cfg["help_url"]}">{cfg["help_url"]}</a>')
                help_label.setProperty("role", "settingsHint")
                help_label.setOpenExternalLinks(True)
                ai_layout.addRow("", help_label)

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
        self.ai_model_edit = QLineEdit(default_model)
        self.ai_model_edit.setPlaceholderText(provider_cfg["model"])
        self.ai_model_edit.setEnabled(False)
        self.ai_model_edit.setObjectName("settingsModelPreview")
        ai_layout.addRow(tr("settings.aiModel"), self.ai_model_edit)

        self.ai_max_steps = _NoWheelSpinBox()
        self.ai_max_steps.setRange(1, 20)
        self.ai_max_steps.setValue(ai_advanced.get("max_steps", DEFAULT_MAX_STEPS))
        ai_layout.addRow(tr("settings.aiMaxSteps"), self.ai_max_steps)

        self.ai_thinking_enabled = QCheckBox()
        self.ai_thinking_enabled.setChecked(ai_advanced.get("thinking_enabled", True))
        ai_layout.addRow(tr("settings.aiThinking"), self.ai_thinking_enabled)

        self.ai_thinking_expanded = QCheckBox()
        self.ai_thinking_expanded.setChecked(ai_advanced.get("thinking_expanded", True))
        ai_layout.addRow(tr("settings.aiThinkingExpanded"), self.ai_thinking_expanded)

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

    @staticmethod
    def _is_valid_inventory_file_path(path_text):
        path = _normalize_inventory_yaml_path(path_text)
        if not path or os.path.isdir(path):
            return False
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in {".yaml", ".yml"}:
            return False
        return os.path.isfile(path)

    def _refresh_yaml_path_validity(self):
        if not hasattr(self, "_ok_button") or self._ok_button is None:
            return
        self._ok_button.setEnabled(self._is_valid_inventory_file_path(self.yaml_edit.text().strip()))

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

    def _browse_yaml(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("settings.selectInventoryFile"),
            "",
            "YAML Files (*.yaml *.yml)",
        )
        if path:
            self.yaml_edit.setText(self._normalize_yaml_path(path))

    def _emit_create_new_dataset_request(self):
        if not callable(self._on_create_new_dataset):
            return
        # Create + switch immediately so users keep the newly created dataset
        # even if they close Settings without pressing OK.
        new_path = self._on_create_new_dataset(update_window=True)
        if new_path:
            self.yaml_edit.setText(self._normalize_yaml_path(new_path))

    def _on_check_update(self):
        """Manually check for updates from GitHub."""
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText(tr("settings.checking"))
        import threading

        def _fetch():
            try:
                import urllib.request
                import json
                req = urllib.request.Request(
                    self._github_api_latest,
                    headers={"Accept": "application/vnd.github.v3+json",
                             "User-Agent": "LN2InventoryAgent"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = data.get("tag_name", "").lstrip("v")
                body = (data.get("body") or "")[:200]
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_check_update_result",
                    Qt.QueuedConnection,
                    Q_ARG(str, latest_tag),
                    Q_ARG(str, body),
                )
            except Exception as e:
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_check_update_result",
                    Qt.QueuedConnection,
                    Q_ARG(str, ""),
                    Q_ARG(str, str(e)),
                )

        threading.Thread(target=_fetch, daemon=True).start()

    @Slot(str, str)
    def _on_check_update_result(self, latest_tag, info):
        """Handle update check result in main thread."""
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText(tr("settings.checkUpdate"))
        if not latest_tag:
            QMessageBox.warning(self, tr("settings.checkUpdate"),
                                t("settings.checkUpdateFailed", error=info))
            return
        if _is_version_newer(latest_tag, self._app_version):
            QMessageBox.information(
                self, tr("settings.checkUpdate"),
                t("settings.newVersionAvailable", version=latest_tag, notes=info))
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
        existing = meta.get("custom_fields", [])
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
                confirm_dlg = QDialog(self)
                confirm_dlg.setWindowTitle(tr("main.customFieldsTitle"))
                confirm_layout = QVBoxLayout(confirm_dlg)
                confirm_label = QLabel(t("main.cfRemoveDataConfirm", phrase=confirm_phrase))
                confirm_label.setWordWrap(True)
                confirm_layout.addWidget(confirm_label)

                class _NoPasteLineEdit(QLineEdit):
                    """QLineEdit that blocks paste via keyboard, context menu, and middle-click."""
                    def keyPressEvent(self, event):
                        if event.matches(QKeySequence.Paste):
                            return
                        super().keyPressEvent(event)
                    def contextMenuEvent(self, event):
                        pass  # disable right-click menu entirely
                    def mousePressEvent(self, event):
                        if event.button() == Qt.MiddleButton:
                            return
                        super().mousePressEvent(event)
                    def insertFromMimeData(self, source):
                        pass  # block any remaining paste path

                confirm_input = _NoPasteLineEdit()
                confirm_input.setPlaceholderText(confirm_phrase)
                confirm_layout.addWidget(confirm_input)
                confirm_buttons = QDialogButtonBox()
                ok_btn = QPushButton(tr("common.ok"))
                ok_btn.setEnabled(False)
                ok_btn.clicked.connect(confirm_dlg.accept)
                confirm_buttons.addButton(ok_btn, QDialogButtonBox.AcceptRole)
                cancel_btn = QPushButton(tr("common.cancel"))
                cancel_btn.clicked.connect(confirm_dlg.reject)
                confirm_buttons.addButton(cancel_btn, QDialogButtonBox.RejectRole)
                confirm_input.textChanged.connect(
                    lambda txt: ok_btn.setEnabled(txt.strip() == confirm_phrase)
                )
                confirm_layout.addWidget(confirm_buttons)

                if confirm_dlg.exec() != QDialog.Accepted:
                    return  # cancelled

                for rec in inventory:
                    if isinstance(rec, dict):
                        for k in removed_keys:
                            rec.pop(k, None)

        # --- Step 3: save ---
        meta["custom_fields"] = new_fields
        if new_dk:
            meta["display_key"] = new_dk
        if new_ck:
            meta["color_key"] = new_ck
        if new_clo:
            meta["cell_line_options"] = new_clo
        elif "cell_line_options" in meta:
            del meta["cell_line_options"]
        meta["cell_line_required"] = bool(new_cl_required)
        data["meta"] = meta
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        self._notify_data_changed(yaml_path=yaml_path, meta=meta)

    def _open_manage_boxes(self):
        if callable(self._on_manage_boxes):
            self._on_manage_boxes(self.yaml_edit.text().strip())

    def _open_export_task_bundle(self):
        dialog_cls = self._export_task_bundle_dialog_cls
        if dialog_cls is None:
            from app_gui.ui.dialogs.export_task_bundle_dialog import ExportTaskBundleDialog as dialog_cls
        dlg = dialog_cls(self)
        dlg.exec()

    def _suggest_import_target_path(self):
        current = self.yaml_edit.text().strip()
        if current and os.path.splitext(current)[1].lower() in {".yaml", ".yml"}:
            return current

        if current:
            candidate_dir = os.path.dirname(self._normalize_yaml_path(current))
        else:
            candidate_dir = os.getcwd()
        if not candidate_dir:
            candidate_dir = os.getcwd()
        return os.path.join(candidate_dir, "ln2_inventory.imported.yaml")

    def _open_import_validated_yaml(self):
        dialog_cls = self._import_validated_yaml_dialog_cls
        if dialog_cls is None:
            from app_gui.ui.dialogs.import_validated_yaml_dialog import (
                ImportValidatedYamlDialog as dialog_cls,
            )
        dlg = dialog_cls(self, default_target_path=self._suggest_import_target_path())
        if dlg.exec() != QDialog.Accepted:
            return
        imported_yaml = getattr(dlg, "imported_yaml_path", "")
        if imported_yaml:
            self.yaml_edit.setText(self._normalize_yaml_path(imported_yaml))

    def _on_provider_changed(self):
        provider = self.ai_provider_combo.currentData()
        cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        self.ai_model_edit.setPlaceholderText(cfg["model"])
        self.ai_model_edit.setText(cfg["model"])

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
        return {
            "yaml_path": self._normalize_yaml_path(self.yaml_edit.text().strip()),
            "api_keys": api_keys,
            "language": self.lang_combo.currentData(),
            "theme": self.theme_combo.currentData(),
            "ui_scale": self.scale_combo.currentData(),
            "ai_provider": provider,
            "ai_model": self.ai_model_edit.text().strip() or provider_cfg["model"],
            "ai_max_steps": self.ai_max_steps.value(),
            "ai_thinking_enabled": self.ai_thinking_enabled.isChecked(),
            "ai_thinking_expanded": self.ai_thinking_expanded.isChecked(),
            "ai_custom_prompt": self.ai_custom_prompt.toPlainText().strip(),
        }



__all__ = ["SettingsDialog"]
