"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import sys
import yaml
from PySide6.QtCore import Qt, QSettings, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFileDialog, QGroupBox,
    QComboBox, QSpinBox, QCheckBox, QScrollArea, QTextEdit,
    QInputDialog,
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
from agent.llm_client import DEFAULT_PROVIDER, PROVIDER_DEFAULTS
from app_gui.i18n import t, tr, set_language
from lib.config import YAML_PATH
from lib.plan_store import PlanStore
from lib.position_fmt import get_box_numbers
from lib.yaml_ops import load_yaml
from app_gui.ui.theme import apply_dark_theme, apply_light_theme
from app_gui.ui.overview_panel import OverviewPanel
from app_gui.ui.operations_panel import OperationsPanel
from app_gui.ui.ai_panel import AIPanel

APP_VERSION = "1.0.0"
APP_RELEASE_URL = "https://github.com/Eamon-fox/ln2-inventory-agent/releases"
_GITHUB_API_LATEST = "https://api.github.com/repos/Eamon-fox/ln2-inventory-agent/releases/latest"


def _parse_version(v: str) -> tuple:
    """Parse version string like '1.0.2' to tuple (1, 0, 2) for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _is_version_newer(new_version: str, old_version: str) -> bool:
    """Return True if new_version > old_version using semver comparison."""
    return _parse_version(new_version) > _parse_version(old_version)


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

    def __init__(self, parent=None, config=None, on_create_new_dataset=None, on_manage_boxes=None, on_data_changed=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(750)
        self.setMinimumHeight(750)
        self._config = config or {}
        self._on_create_new_dataset = on_create_new_dataset
        self._on_manage_boxes = on_manage_boxes
        self._on_data_changed = on_data_changed

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

        tool_row = QHBoxLayout()
        cf_btn = QPushButton(tr("main.manageCustomFields"))
        cf_btn.clicked.connect(self._open_custom_fields_editor)
        tool_row.addWidget(cf_btn)

        box_btn = QPushButton(tr("main.manageBoxes"))
        box_btn.clicked.connect(self._open_manage_boxes)
        tool_row.addWidget(box_btn)

        import_btn = QPushButton(tr("main.importPromptTitle"))
        import_btn.clicked.connect(self._open_import_prompt)
        tool_row.addWidget(import_btn)

        tool_row.addStretch()
        data_layout.addRow("", tool_row)

        content_layout.addWidget(data_group)

        ai_group = QGroupBox(tr("settings.ai"))
        ai_layout = QFormLayout(ai_group)

        api_keys_config = self._config.get("api_keys", {})
        self._api_key_edits = {}
        for provider_id, cfg in PROVIDER_DEFAULTS.items():
            key_edit = QLineEdit(api_keys_config.get(provider_id, ""))
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("sk-...")
            self._api_key_edits[provider_id] = key_edit
            label = f'{cfg["display_name"]} ({cfg["env_key"]}):'
            ai_layout.addRow(label, key_edit)
            if cfg.get("help_url"):
                help_label = QLabel(f'<a href="{cfg["help_url"]}">{cfg["help_url"]}</a>')
                help_label.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
                help_label.setOpenExternalLinks(True)
                ai_layout.addRow("", help_label)

        api_hint = QLabel(tr("settings.apiKeyHint"))
        api_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
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
            f'{tr("app.title")}  v{APP_VERSION}<br>'
            f'{tr("settings.aboutDesc")}<br><br>'
            f'GitHub: <a href="{APP_RELEASE_URL}">'
            f'Eamon-fox/ln2-inventory-agent</a>'
        )
        about_label.setOpenExternalLinks(True)
        about_label.setWordWrap(True)
        about_label.setStyleSheet("color: var(--text-muted); font-size: 12px; padding: 4px;")
        about_layout.addWidget(about_label)

        self._check_update_btn = QPushButton(tr("settings.checkUpdate"))
        self._check_update_btn.setFixedWidth(160)
        self._check_update_btn.clicked.connect(self._on_check_update)
        about_layout.addWidget(self._check_update_btn)

        donate_path = os.path.join(ROOT, "app_gui", "assets", "donate.png")
        if os.path.isfile(donate_path):
            from PySide6.QtGui import QPixmap
            donate_vbox = QVBoxLayout()
            donate_vbox.setAlignment(Qt.AlignCenter)
            donate_text = QLabel(tr("settings.supportHint"))
            donate_text.setStyleSheet("color: var(--text-muted); font-size: 12px; margin-bottom: 4px;")
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
                    _GITHUB_API_LATEST,
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
        if _is_version_newer(latest_tag, APP_VERSION):
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
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

        meta = data.get("meta", {})
        existing = meta.get("custom_fields", [])
        current_dk = meta.get("display_key")
        current_ck = meta.get("color_key")
        current_clo = meta.get("cell_line_options")

        dlg = CustomFieldsDialog(self, custom_fields=existing, display_key=current_dk,
                                 color_key=current_ck, cell_line_options=current_clo)
        if dlg.exec() != QDialog.Accepted:
            return

        new_fields = dlg.get_custom_fields()
        new_dk = dlg.get_display_key()
        new_ck = dlg.get_color_key()
        new_clo = dlg.get_cell_line_options()
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
                confirm_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                ok_btn = confirm_buttons.button(QDialogButtonBox.Ok)
                ok_btn.setEnabled(False)
                confirm_input.textChanged.connect(
                    lambda txt: ok_btn.setEnabled(txt.strip() == confirm_phrase)
                )
                confirm_buttons.accepted.connect(confirm_dlg.accept)
                confirm_buttons.rejected.connect(confirm_dlg.reject)
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
        data["meta"] = meta
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        if callable(self._on_data_changed):
            self._on_data_changed()

    def _open_manage_boxes(self):
        if callable(self._on_manage_boxes):
            self._on_manage_boxes(self.yaml_edit.text().strip())

    def _open_import_prompt(self):
        dlg = ImportPromptDialog(self)
        dlg.exec()

    def _on_provider_changed(self):
        provider = self.ai_provider_combo.currentData()
        cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        self.ai_model_edit.setPlaceholderText(cfg["model"])
        self.ai_model_edit.setText(cfg["model"])

    def get_values(self):
        provider = self.ai_provider_combo.currentData() or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        api_keys = {}
        for prov_id, edit in self._api_key_edits.items():
            key_text = edit.text().strip()
            if key_text:
                api_keys[prov_id] = key_text
        return {
            "yaml_path": self.yaml_edit.text().strip(),
            "api_keys": api_keys,
            "language": self.lang_combo.currentData(),
            "theme": self.theme_combo.currentData(),
            "ai_provider": provider,
            "ai_model": self.ai_model_edit.text().strip() or provider_cfg["model"],
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


def _get_import_prompt():
    return """你是数据清洗与结构化助手。请把我粘贴的 Excel/CSV/表格数据转换为 LN2 Inventory YAML。

严格要求：
1) 只输出 YAML 纯文本，不要 Markdown 代码块，不要解释。
2) 顶层必须包含：
meta:
  version: "1.0"
  box_layout:
    rows: 9
    cols: 9
  custom_fields: []
inventory: []
3) 数据模型是 tube-level：一条 inventory 记录 = 一支物理冻存管。
4) 每条记录必填：
   - id: 正整数，唯一
   - short_name: 非空字符串
   - box: 整数
   - positions: 仅包含 1 个整数的列表（如 [12]）
   - frozen_at: YYYY-MM-DD
5) 常用可选字段：
    - cell_line, plasmid_name, plasmid_id, note, thaw_events
6) 字段映射：
    - 若原表是 cell_line 列，直接映射
   - 若有 quantity/tube_count>1，拆成多条记录
7) 若位置是 A1/B3 形式，换算为整数 position：
   position = (row_index-1)*cols + col_index，其中 A=1, B=2...
8) 空值统一用 null；字符串去首尾空格；日期统一 YYYY-MM-DD。
9) 如果缺少必填字段（尤其 box/position/frozen_at），先列出"缺失信息清单"，先不要输出 YAML。

输出前自检：
- 顶层只有 meta 和 inventory
- inventory 是列表
- 每条 positions 只有一个整数
- id 无重复

下面是原始数据：
<<<DATA
（把 Excel 粘贴内容放这里）
DATA"""


def _get_yaml_example():
    return """meta:
  version: "1.0"
  box_layout:
    rows: 9
    cols: 9
  custom_fields:
    - key: plasmid_name
      label: Plasmid Name
      type: str
    - key: passage_number
      label: Passage #
      type: int
    - key: short_name
      label: Short Name
      type: str

inventory:
  - id: 1
    cell_line: K562
    short_name: K562_ctrl_A
    plasmid_name: pLenti-empty
    plasmid_id: p0001
    passage_number: 3
    box: 1
    positions: [1]
    frozen_at: "2026-02-01"
    note: baseline control

  - id: 2
    cell_line: HeLa
    short_name: HeLa_test_B
    plasmid_name: null
    plasmid_id: null
    passage_number: 5
    box: 1
    positions: [2]
    frozen_at: "2026-01-15"
    note: null"""


class ImportPromptDialog(QDialog):
    """Dialog showing import prompt for converting Excel/CSV to YAML."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("main.importPromptTitle"))
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        desc = QLabel(tr("main.importPromptDesc"))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #64748b; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(desc)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlainText(_get_import_prompt())
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setFontFamily("monospace")
        self.prompt_edit.setFontPointSize(10)
        layout.addWidget(self.prompt_edit, 1)

        buttons = QDialogButtonBox()
        copy_btn = QPushButton(tr("main.importPromptCopy"))
        copy_btn.clicked.connect(self._copy_prompt)
        buttons.addButton(copy_btn, QDialogButtonBox.ActionRole)

        view_yaml_btn = QPushButton(tr("main.importPromptViewYaml"))
        view_yaml_btn.clicked.connect(self._view_yaml_example)
        buttons.addButton(view_yaml_btn, QDialogButtonBox.ActionRole)

        close_btn = QDialogButtonBox.Close
        buttons.addButton(close_btn)
        layout.addWidget(buttons)

    def _copy_prompt(self):
        try:
            QApplication.clipboard().setText(_get_import_prompt())
            self.status_message = tr("main.importPromptCopied")
            QMessageBox.information(self, tr("common.info"), tr("main.importPromptCopied"))
        except Exception as e:
            print(f"[ImportPrompt] Copy failed: {e}")

    def _view_yaml_example(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("main.importPromptViewYamlTitle"))
        dlg.setMinimumWidth(500)
        dlg.setMinimumHeight(400)
        layout = QVBoxLayout(dlg)
        text_edit = QTextEdit()
        text_edit.setPlainText(_get_yaml_example())
        text_edit.setReadOnly(True)
        text_edit.setFontFamily("monospace")
        text_edit.setFontPointSize(10)
        layout.addWidget(text_edit)
        close_btn = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn.rejected.connect(dlg.reject)
        layout.addWidget(close_btn)
        dlg.exec()


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

    def __init__(self, parent=None, custom_fields=None, display_key=None, color_key=None, cell_line_options=None):
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

        from lib.custom_fields import STRUCTURAL_FIELD_KEYS, DEFAULT_PRESET_FIELDS

        # --- Structural fields (read-only, same row style as user fields) ---
        struct_group = QGroupBox(tr("main.cfCoreFields"))
        struct_layout = QVBoxLayout(struct_group)
        struct_layout.setContentsMargins(8, 4, 8, 4)
        struct_layout.setSpacing(6)

        # Column header for structural fields
        s_header = QWidget()
        s_header_l = QHBoxLayout(s_header)
        s_header_l.setContentsMargins(0, 0, 0, 0)
        s_header_l.setSpacing(4)
        for text, width in [(tr("main.cfKey"), 140), (tr("main.cfLabel"), 120),
                            (tr("main.cfType"), 70), (tr("main.cfDefault"), 100)]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 600;")
            s_header_l.addWidget(lbl)
        req_lbl = QLabel(tr("main.cfRequired"))
        req_lbl.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 600;")
        s_header_l.addWidget(req_lbl)
        spacer_lbl = QWidget(); spacer_lbl.setFixedWidth(60)
        s_header_l.addWidget(spacer_lbl)
        struct_layout.addWidget(s_header)

        _STRUCTURAL_DISPLAY = [
            ("id", "ID", "int"),
            ("box", "Box", "int"),
            ("positions", "Positions", "str"),
            ("cell_line", "Cell Line", "str"),
            ("frozen_at", "Frozen At", "date"),
            ("thaw_events", "Thaw Events", "str"),
        ]
        for s_key, s_label, s_type in _STRUCTURAL_DISPLAY:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            k_edit = QLineEdit(s_key); k_edit.setFixedWidth(140); k_edit.setReadOnly(True); k_edit.setEnabled(False)
            row_l.addWidget(k_edit)
            l_edit = QLineEdit(s_label); l_edit.setFixedWidth(120); l_edit.setReadOnly(True); l_edit.setEnabled(False)
            row_l.addWidget(l_edit)
            t_combo = QComboBox(); t_combo.addItem(s_type); t_combo.setFixedWidth(70); t_combo.setEnabled(False)
            row_l.addWidget(t_combo)
            d_edit = QLineEdit(); d_edit.setFixedWidth(100); d_edit.setEnabled(False)
            row_l.addWidget(d_edit)
            r_cb = QCheckBox(tr("main.cfRequired")); r_cb.setChecked(True); r_cb.setEnabled(False)
            row_l.addWidget(r_cb)
            spacer = QWidget(); spacer.setFixedWidth(60)
            row_l.addWidget(spacer)
            struct_layout.addWidget(row_w)
        scroll_layout.addWidget(struct_group)

        # --- User fields (all editable) ---
        custom_group = QGroupBox(tr("main.cfCustomFields"))
        self._rows_layout = QVBoxLayout(custom_group)
        self._rows_layout.setContentsMargins(8, 4, 8, 4)
        self._rows_layout.setSpacing(6)

        # Column header for user fields
        u_header = QWidget()
        u_header_l = QHBoxLayout(u_header)
        u_header_l.setContentsMargins(0, 0, 0, 0)
        u_header_l.setSpacing(4)
        for text, width in [(tr("main.cfKey"), 140), (tr("main.cfLabel"), 120),
                            (tr("main.cfType"), 70), (tr("main.cfDefault"), 100)]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 600;")
            u_header_l.addWidget(lbl)
        req_lbl = QLabel(tr("main.cfRequired"))
        req_lbl.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 600;")
        u_header_l.addWidget(req_lbl)
        rm_spacer = QWidget(); rm_spacer.setFixedWidth(60)
        u_header_l.addWidget(rm_spacer)
        self._rows_layout.addWidget(u_header)

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

        # Color key selector
        ck_row = QHBoxLayout()
        ck_row.addWidget(QLabel(tr("main.cfColorKey")))
        self._color_key_combo = QComboBox()
        self._refresh_color_key_combo(color_key)
        ck_row.addWidget(self._color_key_combo, 1)
        root.addLayout(ck_row)

        # Cell line options editor
        clo_row = QVBoxLayout()
        clo_row.addWidget(QLabel(tr("main.cfCellLineOptions")))
        self._cell_line_options_edit = QTextEdit()
        self._cell_line_options_edit.setMaximumHeight(80)
        self._cell_line_options_edit.setPlaceholderText(tr("main.cfCellLineOptionsPh"))
        if cell_line_options:
            self._cell_line_options_edit.setPlainText("\n".join(cell_line_options))
        else:
            from lib.custom_fields import DEFAULT_CELL_LINE_OPTIONS
            self._cell_line_options_edit.setPlainText("\n".join(DEFAULT_CELL_LINE_OPTIONS))
        root.addLayout(clo_row)
        clo_row.addWidget(self._cell_line_options_edit)

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

    def _refresh_color_key_combo(self, current_ck=None):
        combo = self._color_key_combo
        combo.clear()
        # cell_line is always an option for color_key
        combo.addItem("cell_line", "cell_line")
        for entry in self._field_rows:
            key = entry["key"].text().strip()
            if key:
                combo.addItem(key, key)
        if current_ck:
            idx = combo.findData(current_ck)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def get_display_key(self):
        return self._display_key_combo.currentData() or ""

    def get_color_key(self):
        return self._color_key_combo.currentData() or "cell_line"

    def get_cell_line_options(self):
        text = self._cell_line_options_edit.toPlainText().strip()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

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

        required_cb = QCheckBox(tr("main.cfRequired"))
        required_cb.setChecked(bool(required))
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
        if entry not in self._field_rows:
            return
        key_name = entry["key"].text().strip() or "?"
        reply = QMessageBox.question(
            self,
            tr("main.customFieldsTitle"),
            t("main.cfRemoveConfirm", field=key_name),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
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
        self.settings = QSettings("EamonFox", "LN2InventoryAgent")
        self.gui_config = load_gui_config()
        set_language(self.gui_config.get("language") or "zh-CN")

        self.setWindowTitle(tr("app.title"))
        self.resize(1300, 900)

        self.bridge = GuiToolBridge()
        self.bridge.set_api_keys(self.gui_config.get("api_keys", {}))

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

        self.setup_ui()
        self.connect_signals()
        self.restore_ui_settings()

        self.statusBar().showMessage(tr("app.ready"), 2000)
        self._check_release_notice_once()
        self._check_empty_inventory_prompt()
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
        self.plan_store = PlanStore()
        self.operations_panel = OperationsPanel(self.bridge, lambda: self.current_yaml_path, self.plan_store)
        self.ai_panel = AIPanel(
            self.bridge,
            lambda: self.current_yaml_path,
            plan_store=self.plan_store,
            manage_boxes_request_handler=self.handle_manage_boxes_request,
        )

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

        # AI -> Operations: agent writes to plan_store directly;
        # on_change callback triggers GUI refresh (see _wire_plan_store below).
        self.ai_panel.operation_completed.connect(self.on_operation_completed)

        # Plan store -> Operations panel (thread-safe refresh)
        self._wire_plan_store()

        # Status messages
        self.overview_panel.status_message.connect(self.show_status)
        self.operations_panel.status_message.connect(self.show_status)
        self.ai_panel.status_message.connect(self.show_status)

    def show_status(self, msg, timeout=2000, level="info"):
        self.statusBar().showMessage(msg, timeout)

    def _check_release_notice_once(self):
        """Fetch latest release from GitHub in background and notify if newer."""
        import threading

        def _fetch_and_notify():
            try:
                import urllib.request
                import json
                req = urllib.request.Request(
                    _GITHUB_API_LATEST,
                    headers={"Accept": "application/vnd.github.v3+json",
                             "User-Agent": "LN2InventoryAgent"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                latest_tag = data.get("tag_name", "").lstrip("v").lstrip("1.0.1")
                if not _is_version_newer(latest_tag, APP_VERSION):
                    return
                last_notified = self.gui_config.get("last_notified_release", "0.0.0")
                if not _is_version_newer(latest_tag, last_notified):
                    return
                body = (data.get("body") or "")[:200]
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_show_update_dialog",
                    Qt.QueuedConnection,
                    Q_ARG(str, latest_tag),
                    Q_ARG(str, body),
                )
            except Exception as e:
                print(f"[VersionCheck] {e}")

        threading.Thread(target=_fetch_and_notify, daemon=True).start()

    @Slot(str, str)
    def _show_update_dialog(self, latest_tag, release_notes):
        """Show update notification dialog (called from main thread)."""
        try:
            title = tr("main.newReleaseTitle")
            message = t("main.newReleaseMessage", version=latest_tag, notes=release_notes or tr("main.releaseNotesDefault"))

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            msg_box.setIcon(QMessageBox.Information)

            copy_btn = msg_box.addButton(tr("main.newReleaseCopy"), QMessageBox.ActionRole)
            open_btn = msg_box.addButton(tr("main.newReleaseOpen"), QMessageBox.ActionRole)
            later_btn = msg_box.addButton(tr("main.newReleaseLater"), QMessageBox.RejectRole)

            msg_box.setDefaultButton(later_btn)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == copy_btn:
                try:
                    QApplication.clipboard().setText(APP_RELEASE_URL)
                except Exception as e:
                    print(f"[VersionCheck] Copy to clipboard failed: {e}")
            elif clicked == open_btn:
                try:
                    from PySide6.QtCore import QUrl
                    from PySide6.QtGui import QDesktopServices
                    QDesktopServices.openUrl(QUrl(APP_RELEASE_URL))
                except Exception as e:
                    print(f"[VersionCheck] Open URL failed: {e}")

            self.gui_config["last_notified_release"] = latest_tag
            save_gui_config(self.gui_config)

        except Exception as e:
            print(f"[VersionCheck] Dialog failed: {e}")

    def _check_empty_inventory_prompt(self):
        """Show import prompt if inventory is empty and user hasn't seen the prompt."""
        try:
            if self.gui_config.get("import_prompt_seen", False):
                return

            if not os.path.isfile(self.current_yaml_path):
                return

            try:
                with open(self.current_yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                return

            inventory = data.get("inventory") if isinstance(data, dict) else None
            if inventory and len(inventory) > 0:
                return

            title = tr("main.importStartupTitle")
            message = tr("main.importStartupMessage")

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(title)
            msg_box.setText(message)
            msg_box.setIcon(QMessageBox.Information)

            import_btn = msg_box.addButton(tr("main.importStartupAction"), QDialogButtonBox.ActionRole)
            new_btn = msg_box.addButton(tr("main.importPromptNewInventory"), QDialogButtonBox.ActionRole)
            later_btn = msg_box.addButton(QDialogButtonBox.Close)
            later_btn.setText(tr("main.newReleaseLater"))

            msg_box.setDefaultButton(import_btn)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            self.gui_config["import_prompt_seen"] = True
            save_gui_config(self.gui_config)

            if clicked == import_btn:
                dlg = ImportPromptDialog(self)
                dlg.exec()
            elif clicked == new_btn:
                self.on_create_new_dataset()

        except Exception as e:
            print(f"[ImportPrompt] Empty inventory check failed: {e}")

    def _wire_plan_store(self):
        """Connect PlanStore.on_change to OperationsPanel refresh (thread-safe)."""
        from PySide6.QtCore import QMetaObject, Qt as QtConst

        ops = self.operations_panel

        def _on_plan_changed():
            QMetaObject.invokeMethod(ops, "_on_store_changed", QtConst.QueuedConnection)

        self.plan_store._on_change = _on_plan_changed

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
                "api_keys": self.gui_config.get("api_keys", {}),
                "ai": self.gui_config.get("ai", {}),
                "language": self.gui_config.get("language", "en"),
                "theme": self.gui_config.get("theme", "dark"),
            },
            on_create_new_dataset=self.on_create_new_dataset,
            on_manage_boxes=self.on_manage_boxes,
            on_data_changed=lambda: self.overview_panel.refresh(),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.get_values()
        self.current_yaml_path = values["yaml_path"]
        self.gui_config["api_keys"] = values.get("api_keys", {})

        new_lang = values.get("language", "en")
        if new_lang != self.gui_config.get("language"):
            self.gui_config["language"] = new_lang
            self._ask_restart(tr("main.languageChangedRestart"))

        new_theme = values.get("theme", "dark")
        if new_theme != self.gui_config.get("theme"):
            self.gui_config["theme"] = new_theme
            self._ask_restart(tr("main.themeChangedRestart"))

        self.gui_config["ai"] = {
            "provider": values.get("ai_provider", "deepseek"),
            "model": values.get("ai_model", "deepseek-chat"),
            "max_steps": values.get("ai_max_steps", 8),
            "thinking_enabled": values.get("ai_thinking_enabled", True),
            "thinking_expanded": values.get("ai_thinking_expanded", True),
            "custom_prompt": values.get("ai_custom_prompt", ""),
        }
        self.bridge.set_api_keys(self.gui_config["api_keys"])
        self.ai_panel.ai_provider.setText(self.gui_config["ai"]["provider"])
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

    def _ask_restart(self, message):
        box = QMessageBox(self)
        box.setWindowTitle(tr("common.info"))
        box.setText(message)
        btn_restart = box.addButton(tr("main.restartNow"), QMessageBox.AcceptRole)
        btn_later = box.addButton(tr("main.restartLater"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == btn_restart:
            self._restart_app()

    def _restart_app(self):
        save_gui_config(self.gui_config)
        QApplication.quit()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def on_manage_boxes(self, yaml_path_override=None):
        request = self._prompt_manage_boxes_request(yaml_path_override=yaml_path_override)
        if not request:
            return
        result = self.handle_manage_boxes_request(
            request,
            from_ai=False,
            yaml_path_override=yaml_path_override,
        )
        if isinstance(result, dict) and result.get("ok"):
            QMessageBox.information(
                self,
                tr("common.info"),
                tr("main.boxAdjustSuccess"),
            )
        elif isinstance(result, dict) and result.get("error_code") != "user_cancelled":
            QMessageBox.warning(
                self,
                tr("common.info"),
                result.get("message") or tr("main.boxAdjustFailed"),
            )

    def _prompt_manage_boxes_request(self, yaml_path_override=None):
        yaml_path = str(yaml_path_override or self.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            QMessageBox.warning(self, tr("common.info"), t("main.fileNotFound", path=yaml_path))
            return None

        operation, ok = QInputDialog.getItem(
            self,
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
                self,
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
            QMessageBox.warning(self, tr("common.info"), f"{tr('main.boxAdjustFailed')}: {exc}")
            return None

        if not box_numbers:
            QMessageBox.warning(self, tr("common.info"), tr("main.boxNoAvailable"))
            return None

        box_text, ok = QInputDialog.getItem(
            self,
            tr("main.manageBoxes"),
            tr("main.boxRemovePrompt"),
            [str(box_num) for box_num in box_numbers],
            0,
            False,
        )
        if not ok:
            return None
        return {"operation": "remove", "box": int(box_text)}

    def _ask_remove_mode(self, box_numbers, target_box, suggested_mode=None):
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

        dlg = QMessageBox(self)
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

    def handle_manage_boxes_request(self, request, from_ai=True, yaml_path_override=None):
        if not isinstance(request, dict):
            return {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": "Invalid manage boxes request",
            }

        yaml_path = str(yaml_path_override or self.current_yaml_path)
        if not yaml_path or not os.path.isfile(yaml_path):
            return {
                "ok": False,
                "error_code": "load_failed",
                "message": t("main.fileNotFound", path=yaml_path),
            }

        op = str(request.get("operation") or "").strip().lower()
        if op not in {"add", "remove"}:
            return {
                "ok": False,
                "error_code": "invalid_operation",
                "message": "operation must be add/remove",
            }

        payload = {"operation": op}
        mode = request.get("renumber_mode")
        if mode not in (None, ""):
            mode = str(mode).strip().lower()
            alias = {
                "keep": "keep_gaps",
                "gaps": "keep_gaps",
                "renumber": "renumber_contiguous",
                "compact": "renumber_contiguous",
            }
            mode = alias.get(mode, mode)

        if op == "add":
            try:
                payload["count"] = int(request.get("count", 1))
            except Exception:
                return {
                    "ok": False,
                    "error_code": "invalid_count",
                    "message": "count must be a positive integer",
                }
            if payload["count"] <= 0:
                return {
                    "ok": False,
                    "error_code": "invalid_count",
                    "message": "count must be a positive integer",
                }

            reply = QMessageBox.question(
                self,
                tr("main.manageBoxes"),
                t("main.boxConfirmAdd", count=payload["count"]),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return {
                    "ok": False,
                    "error_code": "user_cancelled",
                    "message": tr("main.boxCancelled"),
                }

        else:
            try:
                target_box = int(request.get("box"))
            except Exception:
                return {
                    "ok": False,
                    "error_code": "invalid_box",
                    "message": "box must be an integer",
                }
            payload["box"] = target_box

            try:
                data = load_yaml(yaml_path)
                layout = (data or {}).get("meta", {}).get("box_layout", {})
                box_numbers = get_box_numbers(layout)
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "load_failed",
                    "message": str(exc),
                }

            chosen_mode = self._ask_remove_mode(box_numbers, target_box, suggested_mode=mode)
            if chosen_mode is None:
                return {
                    "ok": False,
                    "error_code": "user_cancelled",
                    "message": tr("main.boxCancelled"),
                }
            payload["renumber_mode"] = chosen_mode

            mode_label = (
                tr("main.boxDeleteKeepGaps")
                if chosen_mode == "keep_gaps"
                else tr("main.boxDeleteRenumber")
            )
            reply = QMessageBox.question(
                self,
                tr("main.manageBoxes"),
                t("main.boxConfirmRemove", box=target_box, mode=mode_label),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return {
                    "ok": False,
                    "error_code": "user_cancelled",
                    "message": tr("main.boxCancelled"),
                }

        response = self.bridge.adjust_box_count(yaml_path=yaml_path, **payload)

        if response.get("ok"):
            self.overview_panel.refresh()
            self.on_operation_completed(True)
        self.operations_panel.emit_external_operation_event(
            {
                "type": "box_layout_adjusted",
                "source": "ai" if from_ai else "settings",
                "operation": op,
                "ok": bool(response.get("ok")),
                "preview": response.get("preview") or response.get("result") or {},
                "error_code": response.get("error_code"),
                "message": response.get("message"),
            }
        )

        return response

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
        provider = ai_cfg.get("provider") or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        self.ai_panel.ai_provider.setText(provider)
        self.ai_panel.ai_model.setText(ai_cfg.get("model") or provider_cfg["model"])
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
        provider = self.ai_panel.ai_provider.text().strip() or DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
        self.gui_config["yaml_path"] = self.current_yaml_path
        self.gui_config["ai"] = {
            "provider": provider,
            "model": self.ai_panel.ai_model.text().strip() or provider_cfg["model"],
            "max_steps": self.ai_panel.ai_steps.value(),
            "thinking_enabled": self.ai_panel.ai_thinking_enabled.isChecked(),
            "thinking_expanded": not self.ai_panel.ai_thinking_collapsed,
            "custom_prompt": self.ai_panel.ai_custom_prompt,
        }
        save_gui_config(self.gui_config)

        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)

    # Set application icon (taskbar, window title bar, etc.)
    icon_path = os.path.join(ROOT, "app_gui", "assets", "icon.png")
    if os.path.isfile(icon_path):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

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
