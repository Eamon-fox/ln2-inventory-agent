"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import sys
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFileDialog, QGroupBox,
    QFrame, QSpacerItem, QSizePolicy, QComboBox
)
from PySide6.QtGui import QFont

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
from app_gui.i18n import tr, t, set_language
from app_gui.path_utils import resolve_demo_dataset_path
from lib.config import YAML_PATH
from app_gui.ui.theme import apply_dark_theme, apply_light_theme
from app_gui.ui.overview_panel import OverviewPanel
from app_gui.ui.operations_panel import OperationsPanel
from app_gui.ui.ai_panel import AIPanel


class QuickStartDialog(QDialog):
    """Enhanced Quick Start dialog with explanations."""

    def __init__(self, parent=None, current_path="", demo_path=""):
        super().__init__(parent)
        self.setWindowTitle(tr("quickStart.title"))
        self.setMinimumWidth(500)
        self.chosen_path = None
        self.create_new = False

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel(tr("quickStart.title"))
        title.setFont(QFont("", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        intro = QLabel(tr("quickStart.intro"))
        intro.setAlignment(Qt.AlignCenter)
        intro.setStyleSheet("color: #94a3b8;")
        layout.addWidget(intro)

        options_layout = QVBoxLayout()
        options_layout.setSpacing(12)

        self.btn_demo = self._create_option_button(
            tr("quickStart.demo"),
            tr("quickStart.demoDesc"),
        )
        self.btn_demo.clicked.connect(self._on_demo)
        options_layout.addWidget(self.btn_demo)

        self.btn_open = self._create_option_button(
            tr("quickStart.open"),
            tr("quickStart.openDesc"),
        )
        self.btn_open.clicked.connect(self._on_open)
        options_layout.addWidget(self.btn_open)

        self.btn_current = self._create_option_button(
            tr("quickStart.current"),
            t("quickStart.currentDesc", path=current_path),
        )
        if not current_path or not os.path.exists(current_path):
            self.btn_current.setEnabled(False)
        self.btn_current.clicked.connect(self._on_current)
        options_layout.addWidget(self.btn_current)

        self.btn_new = self._create_option_button(
            tr("quickStart.new"),
            tr("quickStart.newDesc"),
        )
        self.btn_new.clicked.connect(self._on_new)
        options_layout.addWidget(self.btn_new)

        layout.addLayout(options_layout)

        btn_cancel = QPushButton(tr("quickStart.cancel"))
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel, alignment=Qt.AlignCenter)

        self._demo_path = demo_path
        self._current_path = current_path

    def _create_option_button(self, title, description):
        btn = QPushButton()
        btn.setStyleSheet("""
            QPushButton {
                background-color: var(--background-raised);
                border: 1px solid var(--border-weak);
                border-radius: var(--radius-md);
                padding: 16px;
                text-align: left;
                color: var(--text-strong);
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #383838;
                border-color: var(--border-subtle);
            }
            QPushButton:disabled {
                background-color: var(--background-strong);
                color: var(--text-muted);
                border-color: transparent;
            }
        """)
        btn.setText(f"{title}\n\n{description}")
        btn.setMinimumHeight(80)
        return btn

    def _on_demo(self):
        self.chosen_path = self._demo_path
        self.accept()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Inventory File", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            self.chosen_path = path
            self.accept()

    def _on_current(self):
        self.chosen_path = self._current_path
        self.accept()

    def _on_new(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Create New Inventory File", "ln2_inventory.yaml", "YAML Files (*.yaml *.yml)"
        )
        if path:
            self.chosen_path = path
            self.create_new = True
            self.accept()


class SettingsDialog(QDialog):
    """Enhanced Settings dialog with sections and help text."""

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(500)
        self._config = config or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        data_group = QGroupBox(tr("settings.data"))
        data_layout = QFormLayout(data_group)

        yaml_row = QHBoxLayout()
        self.yaml_edit = QLineEdit(self._config.get("yaml_path", ""))
        yaml_browse = QPushButton(tr("settings.browse"))
        yaml_browse.setFixedWidth(80)
        yaml_browse.clicked.connect(self._browse_yaml)
        yaml_row.addWidget(self.yaml_edit, 1)
        yaml_row.addWidget(yaml_browse)
        data_layout.addRow(tr("settings.inventoryFile"), yaml_row)

        yaml_hint = QLabel(tr("settings.inventoryFileHint"))
        yaml_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        yaml_hint.setWordWrap(True)
        data_layout.addRow("", yaml_hint)

        layout.addWidget(data_group)

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

        layout.addWidget(ai_group)

        user_group = QGroupBox(tr("settings.user"))
        user_layout = QFormLayout(user_group)

        self.actor_edit = QLineEdit(self._config.get("actor_id", "gui-user"))
        user_layout.addRow(tr("settings.actorId"), self.actor_edit)

        actor_hint = QLabel(tr("settings.actorIdHint"))
        actor_hint.setStyleSheet("color: #64748b; font-size: 11px; margin-left: 100px;")
        actor_hint.setWordWrap(True)
        user_layout.addRow("", actor_hint)

        layout.addWidget(user_group)

        from app_gui.i18n import SUPPORTED_LANGUAGES
        lang_group = QGroupBox(tr("settings.language").rstrip("："))
        lang_layout = QFormLayout(lang_group)

        self.lang_combo = QComboBox()
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

        layout.addWidget(lang_group)

        theme_group = QGroupBox(tr("settings.theme"))
        theme_layout = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Auto (System)", "auto")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        current_theme = self._config.get("theme", "dark")
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        theme_layout.addRow(tr("settings.theme"), self.theme_combo)

        theme_hint = QLabel(tr("settings.themeHint"))
        theme_hint.setStyleSheet("color: var(--text-muted); font-size: 11px; margin-left: 100px;")
        theme_hint.setWordWrap(True)
        theme_layout.addRow("", theme_hint)

        layout.addWidget(theme_group)

        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_yaml(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Inventory File", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            self.yaml_edit.setText(path)

    def get_values(self):
        return {
            "yaml_path": self.yaml_edit.text().strip(),
            "actor_id": self.actor_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip() or None,
            "language": self.lang_combo.currentData(),
            "theme": self.theme_combo.currentData(),
        }


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
            migrated_actor = self.settings.value("ui/current_actor_id", "", type=str)
            migrated_model = self.settings.value("ai/model", "", type=str)
            migrated_steps = self.settings.value("ai/max_steps", 8, type=int)
            if migrated_yaml:
                self.gui_config["yaml_path"] = migrated_yaml
            if migrated_actor:
                self.gui_config["actor_id"] = migrated_actor
            self.gui_config["ai"] = {
                "model": migrated_model or "deepseek-chat",
                "max_steps": migrated_steps,
            }
            save_gui_config(self.gui_config)

        self.current_yaml_path = self.gui_config.get("yaml_path") or YAML_PATH
        self.current_actor_id = self.gui_config.get("actor_id") or "gui-user"

        self.bridge = GuiToolBridge(actor_id=self.current_actor_id)

        self.setup_ui()
        self.connect_signals()
        self.restore_ui_settings()

        self.statusBar().showMessage(tr("app.ready"), 2000)

        if os.path.isfile(self.current_yaml_path):
            self.overview_panel.refresh()
        else:
            self.on_quick_start()

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

        quick_start_btn = QPushButton(tr("main.quickStart"))
        quick_start_btn.clicked.connect(self.on_quick_start)
        top.addWidget(quick_start_btn)

        settings_btn = QPushButton(tr("main.settings"))
        settings_btn.clicked.connect(self.on_open_settings)
        top.addWidget(settings_btn)
        root.addLayout(top)

        # Panels
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        self.overview_panel = OverviewPanel(self.bridge, lambda: self.current_yaml_path)
        self.operations_panel = OperationsPanel(self.bridge, lambda: self.current_yaml_path)
        self.ai_panel = AIPanel(self.bridge, lambda: self.current_yaml_path)

        self.overview_panel.setMinimumWidth(320)
        self.operations_panel.setMinimumWidth(280)
        self.ai_panel.setMinimumWidth(320)
        self.operations_panel.setMaximumWidth(480)

        splitter.addWidget(self.overview_panel)
        splitter.addWidget(self.operations_panel)
        splitter.addWidget(self.ai_panel)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 4)
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
        self.overview_panel.request_quick_add.connect(lambda: self.operations_panel.set_mode("add"))
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
        self.dataset_label.setText(f"Dataset: {self.current_yaml_path} | Actor: {self.current_actor_id}")

    def _resolve_demo_dataset_path(self):
        return resolve_demo_dataset_path(root=ROOT)

    def on_quick_start(self):
        dialog = QuickStartDialog(
            self,
            current_path=self.current_yaml_path,
            demo_path=self._resolve_demo_dataset_path()
        )
        if dialog.exec() != QDialog.Accepted:
            return

        chosen = dialog.chosen_path
        if not chosen:
            return

        if dialog.create_new:
            empty_data = {
                "meta": {"version": "1.0", "box_layout": {"rows": 9, "cols": 9}},
                "inventory": []
            }
            import yaml
            with open(chosen, "w", encoding="utf-8") as f:
                yaml.dump(empty_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        if not os.path.exists(chosen):
            QMessageBox.warning(
                self,
                "Error",
                f"File not found: {chosen}"
            )
            return

        self.current_yaml_path = os.path.abspath(chosen)
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)
        self._update_dataset_label()
        self.overview_panel.refresh()
        self.statusBar().showMessage(f"Loaded: {self.current_yaml_path}", 5000)

    def on_open_settings(self):
        dialog = SettingsDialog(
            self,
            config={
                "yaml_path": self.current_yaml_path,
                "actor_id": self.current_actor_id,
                "api_key": self.gui_config.get("api_key"),
                "ai": self.gui_config.get("ai", {}),
                "language": self.gui_config.get("language", "en"),
                "theme": self.gui_config.get("theme", "dark"),
            }
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.get_values()
        self.current_yaml_path = values["yaml_path"]
        self.current_actor_id = values["actor_id"]
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
                "Language changed. Please restart the application to apply."
            )

        new_theme = values.get("theme", "dark")
        if new_theme != self.gui_config.get("theme"):
            self.gui_config["theme"] = new_theme
            QMessageBox.information(
                self,
                tr("common.info"),
                "Theme changed. Please restart the application to apply."
            )

        self.bridge.set_actor(self.current_actor_id)
        self._update_dataset_label()
        self.overview_panel.refresh()
        self.gui_config["yaml_path"] = self.current_yaml_path
        self.gui_config["actor_id"] = self.current_actor_id
        save_gui_config(self.gui_config)

    def restore_ui_settings(self):
        geometry = self.settings.value("ui/geometry")
        if geometry:
            self.restoreGeometry(geometry)

        # AI settings from unified config
        ai_cfg = self.gui_config.get("ai", {})
        self.ai_panel.ai_model.setText(ai_cfg.get("model") or "deepseek-chat")
        self.ai_panel.ai_steps.setValue(ai_cfg.get("max_steps", 8))

    def closeEvent(self, event):
        if self.ai_panel.ai_run_inflight:
            QMessageBox.warning(self, "Busy", "AI run is still in progress. Please stop it or wait.")
            event.ignore()
            return

        # Window geometry to QSettings (binary blob)
        self.settings.setValue("ui/geometry", self.saveGeometry())

        # Everything else to unified config
        self.gui_config["yaml_path"] = self.current_yaml_path
        self.gui_config["actor_id"] = self.current_actor_id
        self.gui_config["ai"] = {
            "model": self.ai_panel.ai_model.text().strip() or "deepseek-chat",
            "max_steps": self.ai_panel.ai_steps.value(),
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
