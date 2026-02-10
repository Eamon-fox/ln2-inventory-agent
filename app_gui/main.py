"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import shutil
import sys
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFileDialog
)

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from app_gui.tool_bridge import GuiToolBridge
from app_gui.gui_config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    load_gui_config,
    save_gui_config,
)
from lib.config import YAML_PATH
from app_gui.ui.theme import apply_dark_theme
from app_gui.ui.overview_panel import OverviewPanel
from app_gui.ui.operations_panel import OperationsPanel
from app_gui.ui.ai_panel import AIPanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LN2 Inventory Agent")
        self.resize(1300, 900)

        self.settings = QSettings("EamonFox", "LN2InventoryAgent")  # kept for geometry only
        self.gui_config = load_gui_config()

        # One-time migration from QSettings if unified config file does not exist yet
        if not os.path.isfile(DEFAULT_CONFIG_FILE):
            migrated_yaml = self.settings.value("ui/current_yaml_path", "", type=str)
            migrated_actor = self.settings.value("ui/current_actor_id", "", type=str)
            migrated_model = self.settings.value("ai/model", "", type=str)
            migrated_mock = self.settings.value("ai/mock", True, type=bool)
            migrated_steps = self.settings.value("ai/max_steps", 8, type=int)
            if migrated_yaml:
                self.gui_config["yaml_path"] = migrated_yaml
            if migrated_actor:
                self.gui_config["actor_id"] = migrated_actor
            self.gui_config["ai"] = {
                "model": migrated_model or "deepseek-chat",
                "mock": migrated_mock,
                "max_steps": migrated_steps,
            }
            save_gui_config(self.gui_config)

        self.current_yaml_path = self.gui_config.get("yaml_path") or YAML_PATH
        self.current_actor_id = self.gui_config.get("actor_id") or "gui-user"

        self.bridge = GuiToolBridge(actor_id=self.current_actor_id)

        self.setup_ui()
        self.connect_signals()
        self.restore_ui_settings()

        self.statusBar().showMessage("Ready", 2000)
        # Initial load
        self.overview_panel.refresh()

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

        quick_start_btn = QPushButton("Quick Start")
        quick_start_btn.clicked.connect(self.on_quick_start)
        top.addWidget(quick_start_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.on_open_settings)
        top.addWidget(settings_btn)
        root.addLayout(top)

        # Panels
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.overview_panel = OverviewPanel(self.bridge, lambda: self.current_yaml_path)
        self.operations_panel = OperationsPanel(self.bridge, lambda: self.current_yaml_path)
        self.ai_panel = AIPanel(self.bridge, lambda: self.current_yaml_path)

        # Keep middle operations column from becoming overly wide on large screens.
        self.operations_panel.setMaximumWidth(560)

        splitter.addWidget(self.overview_panel)
        splitter.addWidget(self.operations_panel)
        splitter.addWidget(self.ai_panel)

        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 4)
        root.addWidget(splitter, 1)

        self.setCentralWidget(container)

    def connect_signals(self):
        # Overview -> Operations (Plan staging)
        self.overview_panel.plan_items_requested.connect(
            self.operations_panel.add_plan_items)

        # Overview -> Operations (prefill)
        self.overview_panel.request_prefill.connect(self.operations_panel.set_prefill)
        self.overview_panel.request_add_prefill.connect(self.operations_panel.set_add_prefill)
        self.overview_panel.request_quick_add.connect(lambda: self.operations_panel.set_mode("add"))
        self.overview_panel.request_quick_thaw.connect(lambda: self.operations_panel.set_mode("thaw"))
        self.overview_panel.data_loaded.connect(self.operations_panel.update_records_cache)

        # Operations -> Overview (refresh after execution)
        self.operations_panel.operation_completed.connect(self.on_operation_completed)

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
        """Resolve a stable demo dataset path for both source and frozen builds."""
        embedded_demo = os.path.join(ROOT, "demo", "ln2_inventory.demo.yaml")
        if not os.path.isfile(embedded_demo):
            sibling_demo = os.path.join(os.path.dirname(sys.executable), "demo", "ln2_inventory.demo.yaml")
            if os.path.isfile(sibling_demo):
                return os.path.abspath(sibling_demo)
            return os.path.abspath(embedded_demo)

        # In one-file bundles, _MEIPASS is temporary. Copy demo yaml to user config dir
        # so users can see and edit the file path from the GUI.
        if getattr(sys, "frozen", False):
            stable_demo_dir = os.path.join(DEFAULT_CONFIG_DIR, "demo")
            stable_demo = os.path.join(stable_demo_dir, "ln2_inventory.demo.yaml")
            try:
                os.makedirs(stable_demo_dir, exist_ok=True)
                if not os.path.isfile(stable_demo):
                    shutil.copy2(embedded_demo, stable_demo)
                return os.path.abspath(stable_demo)
            except Exception:
                return os.path.abspath(embedded_demo)

        return os.path.abspath(embedded_demo)

    def on_quick_start(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Quick Start")
        msg.setText("Choose a data source to start:")
        btn_current = msg.addButton("Use Current", QMessageBox.AcceptRole)
        btn_demo = msg.addButton("Use Demo", QMessageBox.AcceptRole)
        btn_custom = msg.addButton("Select File...", QMessageBox.ActionRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked is btn_current:
            chosen = self.current_yaml_path
        elif clicked is btn_demo:
            chosen = self._resolve_demo_dataset_path()
        elif clicked is btn_custom:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Select YAML", os.path.dirname(self.current_yaml_path) or ROOT, "YAML Files (*.yaml *.yml)"
            )
            if not chosen: return
        else:
            return

        if not os.path.exists(chosen):
            QMessageBox.warning(
                self,
                "Error",
                (
                    f"YAML file not found: {chosen}\n\n"
                    "If this is a packaged EXE, build with `pyinstaller ln2_inventory.spec` "
                    "to include the demo dataset."
                ),
            )
            return

        self.current_yaml_path = os.path.abspath(chosen)
        self._update_dataset_label()
        self.overview_panel.refresh()
        self.statusBar().showMessage(f"Loaded dataset: {self.current_yaml_path}", 5000)

    def on_open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        yaml_edit = QLineEdit(self.current_yaml_path)
        browse_btn = QPushButton("Browse")

        row = QHBoxLayout()
        row.addWidget(yaml_edit, 1)
        row.addWidget(browse_btn)
        row_widget = QWidget()
        row_widget.setLayout(row)
        form.addRow("YAML Path", row_widget)

        actor_edit = QLineEdit(self.current_actor_id)
        form.addRow("Actor ID", actor_edit)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        browse_btn.clicked.connect(lambda: yaml_edit.setText(
            QFileDialog.getOpenFileName(dialog, "Select YAML", "", "YAML (*.yaml *.yml)")[0] or yaml_edit.text()
        ))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            self.current_yaml_path = yaml_edit.text().strip()
            self.current_actor_id = actor_edit.text().strip()
            self.bridge.set_actor(self.current_actor_id)
            self._update_dataset_label()
            self.overview_panel.refresh()
            # Persist immediately
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
        self.ai_panel.ai_mock.setChecked(ai_cfg.get("mock", True))
        self.ai_panel.ai_steps.setValue(ai_cfg.get("max_steps", 8))
        self.ai_panel.on_mode_changed()

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
            "mock": self.ai_panel.ai_mock.isChecked(),
            "max_steps": self.ai_panel.ai_steps.value(),
        }
        save_gui_config(self.gui_config)

        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
