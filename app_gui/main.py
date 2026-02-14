"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import sys
import yaml
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFileDialog, QGroupBox,
    QComboBox, QSpinBox, QCheckBox, QScrollArea, QTextEdit,
)

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from app_gui.tool_bridge import GuiToolBridge
from app_gui.gui_config import (
    DEFAULT_CONFIG_FILE,
    load_gui_config,
    save_gui_config,
)
from app_gui.i18n import t, tr, set_language
from lib.config import YAML_PATH
from app_gui.ui.theme import apply_dark_theme, apply_light_theme
from app_gui.ui.overview_panel import OverviewPanel
from app_gui.ui.operations_panel import OperationsPanel
from app_gui.ui.ai_panel import AIPanel


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

    def __init__(self, parent=None, config=None, on_create_new_dataset=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(750)
        self.setMinimumHeight(750)
        self._config = config or {}
        self._on_create_new_dataset = on_create_new_dataset

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
        self.yaml_new_btn.setFixedWidth(80)
        self.yaml_new_btn.clicked.connect(self._emit_create_new_dataset_request)
        yaml_browse = QPushButton(tr("settings.browse"))
        yaml_browse.setFixedWidth(80)
        yaml_browse.clicked.connect(self._browse_yaml)
        yaml_row.addWidget(self.yaml_edit, 1)
        yaml_row.addWidget(self.yaml_new_btn)
        yaml_row.addWidget(yaml_browse)
        data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

        yaml_hint = QLabel(tr("settings.inventoryFileHint"))
        yaml_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        yaml_hint.setWordWrap(True)
        data_layout.addRow("", yaml_hint)

        cf_btn = QPushButton(tr("main.manageCustomFields"))
        cf_btn.clicked.connect(self._open_custom_fields_editor)
        data_layout.addRow("", cf_btn)

        content_layout.addWidget(data_group)

        ai_group = QGroupBox(tr("settings.ai"))
        ai_layout = QFormLayout(ai_group)

        self.api_key_edit = QLineEdit(self._config.get("api_key") or "")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        ai_layout.addRow(tr("settings.apiKey"), self.api_key_edit)

        api_hint = QLabel(tr("settings.apiKeyHint"))
        api_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        api_hint.setWordWrap(True)
        ai_layout.addRow("", api_hint)

        ai_advanced = self._config.get("ai", {})
        self.ai_model_edit = QLineEdit(ai_advanced.get("model", "deepseek-chat"))
        self.ai_model_edit.setPlaceholderText("deepseek-chat")
        self.ai_model_edit.setEnabled(False)
        self.ai_model_edit.setStyleSheet("color: var(--text-muted);")
        ai_layout.addRow(tr("settings.aiModel"), self.ai_model_edit)

        self.ai_max_steps = _NoWheelSpinBox()
        self.ai_max_steps.setRange(1, 20)
        self.ai_max_steps.setValue(ai_advanced.get("max_steps", 8))
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
        custom_prompt_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        custom_prompt_hint.setWordWrap(True)
        ai_layout.addRow("", custom_prompt_hint)

        content_layout.addWidget(ai_group)

        from app_gui.i18n import SUPPORTED_LANGUAGES
        lang_group = QGroupBox(tr("settings.language").rstrip("："))
        lang_layout = QFormLayout(lang_group)

        self.lang_combo = _NoWheelComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        current_lang = self._config.get("language", "en")
        idx = self.lang_combo.findData(current_lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        lang_layout.addRow(tr("settings.language"), self.lang_combo)

        lang_hint = QLabel(tr("settings.languageHint"))
        lang_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        lang_hint.setWordWrap(True)
        lang_layout.addRow("", lang_hint)

        content_layout.addWidget(lang_group)

        theme_group = QGroupBox(tr("settings.theme"))
        theme_layout = QFormLayout(theme_group)

        self.theme_combo = _NoWheelComboBox()
        self.theme_combo.addItem(tr("settings.themeAuto"), "auto")
        self.theme_combo.addItem(tr("settings.themeDark"), "dark")
        self.theme_combo.addItem(tr("settings.themeLight"), "light")
        current_theme = self._config.get("theme", "dark")
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        theme_layout.addRow(tr("settings.theme"), self.theme_combo)

        theme_hint = QLabel(tr("settings.themeHint"))
        theme_hint.setStyleSheet("color: var(--text-muted); font-size: 11px; margin-left: 100px;")
        theme_hint.setWordWrap(True)
        theme_layout.addRow("", theme_hint)

        content_layout.addWidget(theme_group)

        about_group = QGroupBox(tr("settings.about"))
        about_layout = QVBoxLayout(about_group)
        about_label = QLabel(
            f'{tr("app.title")}  v1.0<br>'
            f'{tr("settings.aboutDesc")}<br><br>'
            f'GitHub: <a href="https://github.com/Eamon-fox/ln2-inventory-agent">'
            f'Eamon-fox/ln2-inventory-agent</a>'
        )
        about_label.setOpenExternalLinks(True)
        about_label.setWordWrap(True)
        about_label.setStyleSheet("color: var(--text-muted); font-size: 12px; padding: 4px;")
        about_layout.addWidget(about_label)

        donate_path = os.path.join(ROOT, "app_gui", "assets", "donate.png")
        if os.path.isfile(donate_path):
            from PySide6.QtGui import QPixmap
            donate_vbox = QVBoxLayout()
            donate_vbox.setAlignment(Qt.AlignCenter)
            donate_pixmap = QPixmap(donate_path)
            donate_img = QLabel()
            donate_scaled = donate_pixmap.scaledToWidth(380, Qt.SmoothTransformation)
            donate_img.setPixmap(donate_scaled)
            donate_img.setFixedSize(donate_scaled.size())
            donate_img.setAlignment(Qt.AlignCenter)
            donate_text = QLabel("Thanks for supporting ~")
            donate_text.setStyleSheet("color: var(--text-muted); font-size: 12px; margin-top: 8px;")
            donate_text.setAlignment(Qt.AlignCenter)
            donate_vbox.addWidget(donate_img, alignment=Qt.AlignCenter)
            donate_vbox.addWidget(donate_text, alignment=Qt.AlignCenter)
            about_layout.addLayout(donate_vbox)

        content_layout.addWidget(about_group)

        content_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_yaml(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("settings.selectInventoryFile"),
            "",
            "YAML Files (*.yaml *.yml)",
        )
        if path:
            self.yaml_edit.setText(path)

    def _emit_create_new_dataset_request(self):
        if not callable(self._on_create_new_dataset):
            return
        new_path = self._on_create_new_dataset(update_window=False)
        if new_path:
            self.yaml_edit.setText(new_path)

    def _open_custom_fields_editor(self):
        yaml_path = self.yaml_edit.text().strip()
        if not yaml_path or not os.path.isfile(yaml_path):
            QMessageBox.warning(self, tr("common.info"),
                                t("main.fileNotFound", path=yaml_path))
            return

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

        meta = data.get("meta", {})
        existing = meta.get("custom_fields", [])
        current_dk = meta.get("display_key")

        dlg = CustomFieldsDialog(self, custom_fields=existing, display_key=current_dk)
        if dlg.exec() != QDialog.Accepted:
            return

        new_fields = dlg.get_custom_fields()
        new_dk = dlg.get_display_key()
        inventory = data.get("inventory") or []

        # --- Step 1: handle renames (old_key -> new_key) ---
        renames = {}  # old_key -> new_key
        for f in new_fields:
            orig = f.pop("_original_key", None)
            if orig:
                renames[orig] = f["key"]

        if renames and inventory:
            # Check which renames actually have data to migrate
            renames_with_data = {
                old: new for old, new in renames.items()
                if any(isinstance(r, dict) and r.get(old) is not None for r in inventory)
            }
            if renames_with_data:
                lines = [f"  {old} → {new}" for old, new in renames_with_data.items()]
                msg = QMessageBox(self)
                msg.setWindowTitle(tr("main.customFieldsTitle"))
                msg.setText(t("main.cfRenamePrompt", details="\n".join(lines)))
                btn_migrate = msg.addButton(tr("main.cfRenameMigrate"), QMessageBox.AcceptRole)
                btn_discard = msg.addButton(tr("main.cfRenameDiscard"), QMessageBox.DestructiveRole)
                msg.addButton(QMessageBox.Cancel)
                msg.setDefaultButton(btn_migrate)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked == btn_migrate:
                    for rec in inventory:
                        if not isinstance(rec, dict):
                            continue
                        for old, new in renames_with_data.items():
                            if old in rec:
                                rec[new] = rec.pop(old)
                elif clicked == btn_discard:
                    for rec in inventory:
                        if not isinstance(rec, dict):
                            continue
                        for old in renames_with_data:
                            rec.pop(old, None)
                else:
                    return  # cancelled

        # --- Step 2: handle pure deletes ---
        new_keys = {f["key"] for f in new_fields}
        old_keys = {f["key"] for f in existing if isinstance(f, dict) and f.get("key")}
        # Keys that were renamed are not "deleted" — exclude them
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
                btn_keep = msg.addButton(tr("main.cfRemoveDataKeep"), QMessageBox.AcceptRole)
                msg.addButton(QMessageBox.Cancel)
                msg.setDefaultButton(btn_keep)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked == btn_clean:
                    for rec in inventory:
                        if isinstance(rec, dict):
                            for k in removed_keys:
                                rec.pop(k, None)
                elif clicked == btn_keep:
                    pass
                else:
                    return  # cancelled

        # --- Step 3: save ---
        meta["custom_fields"] = new_fields
        if new_dk:
            meta["display_key"] = new_dk
        data["meta"] = meta
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def get_values(self):
        return {
            "yaml_path": self.yaml_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip() or None,
            "language": self.lang_combo.currentData(),
            "theme": self.theme_combo.currentData(),
            "ai_model": self.ai_model_edit.text().strip() or "deepseek-chat",
            "ai_max_steps": self.ai_max_steps.value(),
            "ai_thinking_enabled": self.ai_thinking_enabled.isChecked(),
            "ai_thinking_expanded": self.ai_thinking_expanded.isChecked(),
            "ai_custom_prompt": self.ai_custom_prompt.toPlainText().strip(),
        }


_BOX_PRESETS = [
    ("9 x 9  (81)", 9, 9),
    ("10 x 10  (100)", 10, 10),
    ("8 x 12  (96)", 8, 12),
    ("5 x 5  (25)", 5, 5),
]


class NewDatasetDialog(QDialog):
    """Dialog for choosing box layout when creating a new dataset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.newDatasetLayout"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.preset_combo = QComboBox()
        for label, _r, _c in _BOX_PRESETS:
            self.preset_combo.addItem(label)
        self.preset_combo.addItem(tr("main.custom"))
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow(tr("main.boxSize"), self.preset_combo)

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 26)
        self.rows_spin.setValue(9)
        self.rows_spin.setEnabled(False)
        form.addRow(tr("main.rows"), self.rows_spin)

        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 26)
        self.cols_spin.setValue(9)
        self.cols_spin.setEnabled(False)
        form.addRow(tr("main.cols"), self.cols_spin)

        self.box_count_spin = QSpinBox()
        self.box_count_spin.setRange(1, 50)
        self.box_count_spin.setValue(5)
        form.addRow(tr("main.boxCount"), self.box_count_spin)

        self.indexing_combo = QComboBox()
        self.indexing_combo.addItem(tr("main.indexNumeric"), "numeric")
        self.indexing_combo.addItem(tr("main.indexAlpha"), "alphanumeric")
        form.addRow(tr("main.indexing"), self.indexing_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset_changed(self, index):
        is_custom = index >= len(_BOX_PRESETS)
        self.rows_spin.setEnabled(is_custom)
        self.cols_spin.setEnabled(is_custom)
        if not is_custom:
            _, r, c = _BOX_PRESETS[index]
            self.rows_spin.setValue(r)
            self.cols_spin.setValue(c)

    def get_layout(self):
        result = {
            "rows": self.rows_spin.value(),
            "cols": self.cols_spin.value(),
            "box_count": self.box_count_spin.value(),
        }
        indexing = self.indexing_combo.currentData()
        if indexing and indexing != "numeric":
            result["indexing"] = indexing
        return result


_FIELD_TYPES = ["str", "int", "float", "date"]


class CustomFieldsDialog(QDialog):
    """Visual editor for meta.custom_fields."""

    def __init__(self, parent=None, custom_fields=None, display_key=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.customFieldsTitle"))
        self.setMinimumWidth(620)
        self.setMinimumHeight(400)

        root = QVBoxLayout(self)

        desc = QLabel(tr("main.customFieldsDesc"))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 4px;")
        root.addWidget(desc)

        # Scrollable area for everything
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        # --- Structural fields info ---
        from lib.custom_fields import STRUCTURAL_FIELD_KEYS, DEFAULT_PRESET_FIELDS
        info_label = QLabel(tr("main.cfStructuralInfo") + "  " + "  ".join(sorted(STRUCTURAL_FIELD_KEYS)))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 4px;")
        scroll_layout.addWidget(info_label)

        # --- User fields (all editable) ---
        custom_group = QGroupBox(tr("main.cfCustomFields"))
        self._rows_layout = QVBoxLayout(custom_group)
        self._rows_layout.setContentsMargins(8, 4, 8, 4)
        self._rows_layout.setSpacing(6)
        scroll_layout.addWidget(custom_group)

        scroll_layout.addStretch()

        self._field_rows = []

        # Populate: use provided fields, or default preset
        fields_to_show = custom_fields if custom_fields else list(DEFAULT_PRESET_FIELDS)
        for f in fields_to_show:
            k = f.get("key", "")
            self._add_row(k, f.get("label", ""),
                          f.get("type", "str"), f.get("default"),
                          required=f.get("required", False),
                          original_key=k)

        # Display key selector
        dk_row = QHBoxLayout()
        dk_row.addWidget(QLabel(tr("main.cfDisplayKey")))
        self._display_key_combo = QComboBox()
        self._refresh_display_key_combo(display_key)
        dk_row.addWidget(self._display_key_combo, 1)
        root.addLayout(dk_row)

        # Add button
        add_btn = QPushButton(tr("main.cfAdd"))
        add_btn.clicked.connect(lambda: self._add_row())
        root.addWidget(add_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _refresh_display_key_combo(self, current_dk=None):
        combo = self._display_key_combo
        combo.clear()
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if current_dk:
            idx = combo.findData(current_dk)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def get_display_key(self):
        return self._display_key_combo.currentData() or ""

    def _add_row(self, key="", label="", ftype="str", default=None, *, required=False, original_key=None):
        from lib.custom_fields import STRUCTURAL_FIELD_KEYS

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        key_edit = QLineEdit(key)
        key_edit.setPlaceholderText(tr("main.cfKeyPh"))
        key_edit.setFixedWidth(140)
        row_layout.addWidget(key_edit)

        label_edit = QLineEdit(label)
        label_edit.setPlaceholderText(tr("main.cfLabelPh"))
        label_edit.setFixedWidth(120)
        row_layout.addWidget(label_edit)

        type_combo = QComboBox()
        for t in _FIELD_TYPES:
            type_combo.addItem(t, t)
        idx = type_combo.findData(ftype)
        if idx >= 0:
            type_combo.setCurrentIndex(idx)
        type_combo.setFixedWidth(70)
        row_layout.addWidget(type_combo)

        default_edit = QLineEdit(str(default) if default is not None else "")
        default_edit.setPlaceholderText(tr("main.cfDefaultPh"))
        default_edit.setFixedWidth(100)
        row_layout.addWidget(default_edit)

        required_cb = QCheckBox("Req")
        required_cb.setChecked(bool(required))
        required_cb.setToolTip(tr("main.cfRequiredTip"))
        row_layout.addWidget(required_cb)

        remove_btn = QPushButton(tr("main.cfRemove"))
        remove_btn.setFixedWidth(60)
        row_layout.addWidget(remove_btn)

        entry = {
            "widget": row_widget,
            "key": key_edit,
            "label": label_edit,
            "type": type_combo,
            "default": default_edit,
            "required": required_cb,
            "original_key": original_key,
        }
        self._field_rows.append(entry)
        self._rows_layout.addWidget(row_widget)

        remove_btn.clicked.connect(lambda: self._remove_row(entry))

    def _remove_row(self, entry):
        if entry in self._field_rows:
            self._field_rows.remove(entry)
            entry["widget"].setParent(None)
            entry["widget"].deleteLater()

    def get_custom_fields(self):
        """Return validated list of custom field dicts.

        Each dict has key/label/type/default/required plus an optional
        ``_original_key`` when the key was renamed from an existing field.
        """
        from lib.custom_fields import STRUCTURAL_FIELD_KEYS

        result = []
        seen = set()
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if not key or not key.isidentifier():
                continue
            if key in STRUCTURAL_FIELD_KEYS or key in seen:
                continue
            seen.add(key)
            label = entry["label"].text().strip() or key
            ftype = entry["type"].currentData() or "str"
            default_text = entry["default"].text().strip()
            default = default_text if default_text else None
            req = entry["required"].isChecked()
            item = {
                "key": key,
                "label": label,
                "type": ftype,
            }
            if default is not None:
                item["default"] = default
            if req:
                item["required"] = True
            orig = entry.get("original_key")
            if orig and orig != key:
                item["_original_key"] = orig
            result.append(item)
        return result


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
        self.resize(1300, 900)

        self.settings = QSettings("EamonFox", "LN2InventoryAgent")
        self.gui_config = load_gui_config()
        set_language(self.gui_config.get("language") or "en")

        if self.gui_config.get("api_key") and not os.environ.get("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"] = self.gui_config["api_key"]

        # One-time migration from QSettings if unified config file does not exist yet
        if not os.path.isfile(DEFAULT_CONFIG_FILE):
            migrated_yaml = self.settings.value("ui/current_yaml_path", "", type=str)
            migrated_model = self.settings.value("ai/model", "", type=str)
            migrated_steps = self.settings.value("ai/max_steps", 8, type=int)
            if migrated_yaml:
                self.gui_config["yaml_path"] = migrated_yaml
            self.gui_config["ai"] = {
                "model": migrated_model or "deepseek-chat",
                "max_steps": migrated_steps,
                "thinking_enabled": True,
            }
            save_gui_config(self.gui_config)

        self.current_yaml_path = self.gui_config.get("yaml_path") or YAML_PATH

        self.bridge = GuiToolBridge()

        self.setup_ui()
        self.connect_signals()
        self.restore_ui_settings()

        self.statusBar().showMessage(tr("app.ready"), 2000)
        self.overview_panel.refresh()
        if not os.path.isfile(self.current_yaml_path):
            self.statusBar().showMessage(
                t("main.fileNotFound", path=self.current_yaml_path),
                6000,
            )

    def setup_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Top Bar
        top = QHBoxLayout()
        self.dataset_label = QLabel()
        self._update_dataset_label()
        top.addWidget(self.dataset_label, 1)

        new_dataset_btn = QPushButton(tr("main.new"))
        new_dataset_btn.clicked.connect(self.on_create_new_dataset)
        top.addWidget(new_dataset_btn)

        settings_btn = QPushButton(tr("main.settings"))
        settings_btn.clicked.connect(self.on_open_settings)
        top.addWidget(settings_btn)

        root.addLayout(top)

        # Panels
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        self.overview_panel = OverviewPanel(self.bridge, lambda: self.current_yaml_path)
        self.operations_panel = OperationsPanel(self.bridge, lambda: self.current_yaml_path)
        self.ai_panel = AIPanel(self.bridge, lambda: self.current_yaml_path)

        screen = QApplication.primaryScreen()
        sw = screen.availableGeometry().width() if screen else 1920

        self.overview_panel.setMinimumWidth(int(sw * 0.15))
        self.operations_panel.setMinimumWidth(int(sw * 0.10))
        self.ai_panel.setMinimumWidth(int(sw * 0.12))
        self.ai_panel.setMaximumWidth(int(sw * 0.22))

        splitter.addWidget(self.overview_panel)
        splitter.addWidget(self.operations_panel)
        splitter.addWidget(self.ai_panel)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        root.addWidget(splitter, 1)

        self.setCentralWidget(container)

    def connect_signals(self):
        # Overview -> Operations (Plan staging)
        self.overview_panel.plan_items_requested.connect(
            self.operations_panel.add_plan_items)

        # Overview -> Operations (prefill)
        self.overview_panel.request_prefill.connect(self.operations_panel.set_prefill)
        self.overview_panel.request_prefill_background.connect(self.operations_panel.set_prefill_background)
        self.overview_panel.request_add_prefill.connect(self.operations_panel.set_add_prefill)
        self.overview_panel.request_add_prefill_background.connect(self.operations_panel.set_add_prefill_background)
        self.overview_panel.request_move_prefill.connect(self.operations_panel.set_move_prefill)
        self.overview_panel.request_query_prefill.connect(self.operations_panel.set_query_prefill)
        self.overview_panel.data_loaded.connect(self.operations_panel.update_records_cache)

        # Operations -> Overview (plan preview)
        self.operations_panel.plan_preview_updated.connect(
            self.overview_panel.update_plan_preview)
        self.operations_panel.plan_hover_item_changed.connect(
            self.overview_panel.on_plan_item_hovered
        )

        # Operations -> Overview (refresh after execution)
        self.operations_panel.operation_completed.connect(self.on_operation_completed)

        # Operations -> AI (operation events for context)
        self.operations_panel.operation_event.connect(self.ai_panel.on_operation_event)

        # AI -> Plan staging
        self.ai_panel.plan_items_staged.connect(
            self.operations_panel.add_plan_items)
        self.ai_panel.operation_completed.connect(self.on_operation_completed)

        # Status messages
        self.overview_panel.status_message.connect(self.show_status)
        self.operations_panel.status_message.connect(self.show_status)
        self.ai_panel.status_message.connect(self.show_status)

    def show_status(self, msg, timeout=2000, level="info"):
        self.statusBar().showMessage(msg, timeout)

    def on_operation_completed(self, success):
        if success:
            self.overview_panel.refresh()

    def _update_dataset_label(self):
        self.dataset_label.setText(self.current_yaml_path)

    def on_open_settings(self):
        dialog = SettingsDialog(
            self,
            config={
                "yaml_path": self.current_yaml_path,
                "api_key": self.gui_config.get("api_key"),
                "ai": self.gui_config.get("ai", {}),
                "language": self.gui_config.get("language", "en"),
                "theme": self.gui_config.get("theme", "dark"),
            },
            on_create_new_dataset=self.on_create_new_dataset,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.get_values()
        self.current_yaml_path = values["yaml_path"]
        api_key = values["api_key"]
        self.gui_config["api_key"] = api_key
        if api_key:
            os.environ["DEEPSEEK_API_KEY"] = api_key

        new_lang = values.get("language", "en")
        if new_lang != self.gui_config.get("language"):
            self.gui_config["language"] = new_lang
            QMessageBox.information(
                self,
                tr("common.info"),
                tr("main.languageChangedRestart")
            )

        new_theme = values.get("theme", "dark")
        if new_theme != self.gui_config.get("theme"):
            self.gui_config["theme"] = new_theme
            QMessageBox.information(
                self,
                tr("common.info"),
                tr("main.themeChangedRestart")
            )

        self.gui_config["ai"] = {
            "model": values.get("ai_model", "deepseek-chat"),
            "max_steps": values.get("ai_max_steps", 8),
            "thinking_enabled": values.get("ai_thinking_enabled", True),
            "thinking_expanded": values.get("ai_thinking_expanded", True),
            "custom_prompt": values.get("ai_custom_prompt", ""),
        }
        self.ai_panel.ai_model.setText(self.gui_config["ai"]["model"])
        self.ai_panel.ai_steps.setValue(self.gui_config["ai"]["max_steps"])
        self.ai_panel.ai_thinking_enabled.setChecked(self.gui_config["ai"]["thinking_enabled"])
        self.ai_panel.ai_thinking_collapsed = not self.gui_config["ai"]["thinking_expanded"]
        self.ai_panel.ai_custom_prompt = self.gui_config["ai"].get("custom_prompt", "")

        self._update_dataset_label()
        self.overview_panel.refresh()
        if not os.path.isfile(self.current_yaml_path):
            self.statusBar().showMessage(
                t("main.fileNotFound", path=self.current_yaml_path),
                6000,
            )
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)

    def on_create_new_dataset(self, update_window=True):
        layout_dlg = NewDatasetDialog(self)
        if layout_dlg.exec() != QDialog.Accepted:
            return
        box_layout = layout_dlg.get_layout()

        default_path = self.current_yaml_path
        if not default_path or os.path.isdir(default_path):
            default_path = os.path.join(os.getcwd(), "ln2_inventory.yaml")
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("main.new"),
            default_path,
            "YAML Files (*.yaml *.yml)",
        )
        if not target_path:
            return

        target_path = os.path.abspath(target_path)
        if os.path.isdir(target_path):
            target_path = os.path.join(target_path, "ln2_inventory.yaml")

        if not target_path.lower().endswith((".yaml", ".yml")):
            target_path += ".yaml"

        target_dir = os.path.dirname(target_path)
        if target_dir and not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        # Step 2: custom fields dialog
        cf_dlg = CustomFieldsDialog(self)
        if cf_dlg.exec() != QDialog.Accepted:
            return
        custom_fields = cf_dlg.get_custom_fields()
        display_key = cf_dlg.get_display_key()

        meta = {
            "version": "1.0",
            "box_layout": box_layout,
            "custom_fields": custom_fields,
        }
        if display_key:
            meta["display_key"] = display_key

        new_payload = {
            "meta": meta,
            "inventory": [],
        }
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_payload, f, allow_unicode=True, sort_keys=False)

        if not update_window:
            return target_path

        self.current_yaml_path = target_path
        self._update_dataset_label()
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)
        self.overview_panel.refresh()
        self.statusBar().showMessage(
            t("main.fileCreated", path=self.current_yaml_path),
            4000,
        )
        return target_path

    def restore_ui_settings(self):
        geometry = self.settings.value("ui/geometry")
        if geometry:
            self.restoreGeometry(geometry)

        # AI settings from unified config
        ai_cfg = self.gui_config.get("ai", {})
        self.ai_panel.ai_model.setText(ai_cfg.get("model") or "deepseek-chat")
        self.ai_panel.ai_steps.setValue(ai_cfg.get("max_steps", 8))
        self.ai_panel.ai_thinking_enabled.setChecked(bool(ai_cfg.get("thinking_enabled", True)))
        self.ai_panel.ai_thinking_collapsed = not bool(ai_cfg.get("thinking_expanded", True))
        self.ai_panel.ai_custom_prompt = ai_cfg.get("custom_prompt", "")

    def closeEvent(self, event):
        if self.ai_panel.ai_run_inflight:
            QMessageBox.warning(
                self,
                tr("main.aiBusyTitle"),
                tr("main.aiBusyMessage"),
            )
            event.ignore()
            return

        # Window geometry to QSettings (binary blob)
        self.settings.setValue("ui/geometry", self.saveGeometry())

        # Everything else to unified config
        self.gui_config["yaml_path"] = self.current_yaml_path
        self.gui_config["ai"] = {
            "model": self.ai_panel.ai_model.text().strip() or "deepseek-chat",
            "max_steps": self.ai_panel.ai_steps.value(),
            "thinking_enabled": self.ai_panel.ai_thinking_enabled.isChecked(),
            "thinking_expanded": not self.ai_panel.ai_thinking_collapsed,
            "custom_prompt": self.ai_panel.ai_custom_prompt,
        }
        save_gui_config(self.gui_config)

        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    
    gui_config = load_gui_config()
    theme = gui_config.get("theme", "dark")
    if theme == "light":
        apply_light_theme(app)
    else:
        apply_dark_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
