"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import sys
from contextlib import suppress
from PySide6.QtCore import Qt, QSettings, Slot, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter,
    QDialog, QLineEdit, QFileDialog, QTextEdit, QPlainTextEdit,
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
    DEFAULT_MAX_STEPS,
    load_gui_config,
    save_gui_config,
)
from agent.llm_client import PROVIDER_DEFAULTS
from app_gui.i18n import t, tr, set_language
from lib.config import YAML_PATH
from lib.plan_store import PlanStore
from app_gui.ui.theme import (
    apply_dark_theme, apply_light_theme,
    resolve_theme_token,
    LAYOUT_OVERVIEW_MIN_WIDTH,
    LAYOUT_OPS_MIN_WIDTH, LAYOUT_OPS_MAX_WIDTH, LAYOUT_OPS_DEFAULT_WIDTH,
    LAYOUT_AI_MIN_WIDTH, LAYOUT_AI_MAX_WIDTH, LAYOUT_AI_DEFAULT_WIDTH,
    LAYOUT_SPLITTER_HANDLE_WIDTH,
)
from app_gui.ui.overview_panel import OverviewPanel
from app_gui.ui.operations_panel import OperationsPanel
from app_gui.ui.ai_panel import AIPanel
from app_gui.ui.dialogs import (
    SettingsDialog,
    ExportTaskBundleDialog,
    ImportValidatedYamlDialog,
    NewDatasetDialog,
    CustomFieldsDialog,
)
from app_gui.ui.icons import get_icon, Icons, set_icon_color
from app_gui.main_window_flows import (
    StartupFlow,
    WindowStateFlow,
    SettingsFlow,
    DatasetFlow,
    ManageBoxesFlow,
)

APP_VERSION = "1.1.1"
APP_RELEASE_URL = "https://github.com/Eamon-fox/snowfox/releases"
_GITHUB_API_LATEST = "https://api.github.com/repos/Eamon-fox/snowfox/releases/latest"
_SETTINGS_EXPORTS = (PROVIDER_DEFAULTS,)


def _parse_version(v: str) -> tuple:
    """Parse version string like '1.0.2' to tuple (1, 0, 2) for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _is_version_newer(new_version: str, old_version: str) -> bool:
    """Return True if new_version > old_version using semver comparison."""
    return _parse_version(new_version) > _parse_version(old_version)


def _normalize_inventory_yaml_path(path_text) -> str:
    """Normalize inventory YAML path.

    - Empty input -> ""
    - Directory input -> keep as-is
    - File input -> keep as-is
    - Special case: demo path with .demo. suffix -> keep as-is (don't rename)
    """
    raw = str(path_text or "").strip()
    if not raw:
        return ""

    abs_path = os.path.abspath(raw)

    # Preserve demo/default inventory paths that have .demo. suffix
    if ".demo." in os.path.basename(abs_path).lower():
        return abs_path

    return abs_path


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

        # One-time migration from legacy QSettings if unified config file does not exist yet.
        # Guarded by a dedicated marker to avoid re-importing stale paths after users
        # intentionally remove ~/.ln2agent/config.yaml.
        migrated_once = self.settings.value("migration/unified_config_done", False, type=bool)
        if (not os.path.isfile(DEFAULT_CONFIG_FILE)) and (not migrated_once):
            migrated_model = self.settings.value("ai/model", "", type=str)
            migrated_steps = self.settings.value("ai/max_steps", DEFAULT_MAX_STEPS, type=int)
            self.gui_config["ai"] = {
                "model": migrated_model or "deepseek-chat",
                "max_steps": migrated_steps,
                "thinking_enabled": True,
            }
            save_gui_config(self.gui_config)
            self.settings.setValue("migration/unified_config_done", True)

        configured_yaml = _normalize_inventory_yaml_path(self.gui_config.get("yaml_path") or "")
        self.current_yaml_path = configured_yaml or YAML_PATH

        self.setup_ui()
        self._state_flow = WindowStateFlow(self)
        self._startup_flow = StartupFlow(
            self,
            app_version=APP_VERSION,
            release_url=APP_RELEASE_URL,
            github_api_latest=_GITHUB_API_LATEST,
            is_version_newer=_is_version_newer,
            show_nonblocking_dialog=self._show_nonblocking_dialog,
            export_task_bundle_dialog_cls=ExportTaskBundleDialog,
            import_validated_yaml_dialog_cls=ImportValidatedYamlDialog,
        )
        self._settings_flow = SettingsFlow(self, normalize_yaml_path=_normalize_inventory_yaml_path)
        self._dataset_flow = DatasetFlow(self)
        self._boxes_flow = ManageBoxesFlow(self)
        self.connect_signals()
        self._setup_shortcuts()
        self.restore_ui_settings()
        self._startup_checks_scheduled = False
        self._floating_dialog_refs = []

        self.statusBar().showMessage(tr("app.ready"), 2000)
        self.overview_panel.refresh()
        if not os.path.isfile(self.current_yaml_path):
            self.statusBar().showMessage(
                t("main.fileNotFound", path=self.current_yaml_path),
                6000,
            )

    def showEvent(self, event):
        super().showEvent(event)
        if self._startup_checks_scheduled:
            return
        self._startup_checks_scheduled = True
        # Run startup dialogs after the main window is visible to avoid
        # modal deadlock perception when the dialog is not foregrounded.
        QTimer.singleShot(150, self._run_startup_checks)

    def _run_startup_checks(self):
        self._check_release_notice_once()
        self._check_empty_inventory_onboarding()

    def setup_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        # Top Bar
        top = QHBoxLayout()
        self.dataset_label = QLabel()
        self._update_dataset_label()
        top.addWidget(self.dataset_label, 1)

        new_dataset_btn = QPushButton(tr("main.new"))
        new_dataset_btn.setIcon(get_icon(Icons.FILE_PLUS))
        new_dataset_btn.clicked.connect(self.on_create_new_dataset)
        top.addWidget(new_dataset_btn)

        audit_log_btn = QPushButton(tr("main.auditLog"))
        audit_log_btn.setIcon(get_icon(Icons.FILE_TEXT))
        audit_log_btn.clicked.connect(self.on_open_audit_log)
        top.addWidget(audit_log_btn)

        settings_btn = QPushButton(tr("main.settings"))
        settings_btn.setIcon(get_icon(Icons.SETTINGS))
        settings_btn.clicked.connect(self.on_open_settings)
        top.addWidget(settings_btn)

        root.addLayout(top)

        # Panels
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(LAYOUT_SPLITTER_HANDLE_WIDTH)

        self.overview_panel = OverviewPanel(self.bridge, lambda: self.current_yaml_path)
        self.plan_store = PlanStore()
        self.operations_panel = OperationsPanel(
            self.bridge,
            lambda: self.current_yaml_path,
            self.plan_store,
            overview_panel=self.overview_panel
        )
        self.ai_panel = AIPanel(
            self.bridge,
            lambda: self.current_yaml_path,
            plan_store=self.plan_store,
            manage_boxes_request_handler=self.handle_manage_boxes_request,
        )

        # Apply layout constraints from theme.py
        self.operations_panel.setMinimumWidth(LAYOUT_OPS_MIN_WIDTH)
        self.operations_panel.setMaximumWidth(LAYOUT_OPS_MAX_WIDTH)
        self.ai_panel.setMinimumWidth(LAYOUT_AI_MIN_WIDTH)
        self.ai_panel.setMaximumWidth(LAYOUT_AI_MAX_WIDTH)
        self.overview_panel.setMinimumWidth(LAYOUT_OVERVIEW_MIN_WIDTH)

        splitter.addWidget(self.overview_panel)
        splitter.addWidget(self.operations_panel)
        splitter.addWidget(self.ai_panel)

        # Set initial sizes: give side panels their preferred widths,
        # let overview take the remaining space
        screen = QApplication.primaryScreen()
        sw = screen.availableGeometry().width() if screen else 1920
        overview_width = sw - LAYOUT_OPS_DEFAULT_WIDTH - LAYOUT_AI_DEFAULT_WIDTH - 40

        splitter.setSizes([overview_width, LAYOUT_OPS_DEFAULT_WIDTH, LAYOUT_AI_DEFAULT_WIDTH])

        # Stretch factor: overview grows, side panels stay fixed
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter, 1)

        # Status bar for statistics (Excel-like bottom bar)
        self.stats_bar = QLabel()
        self.stats_bar.setObjectName("mainStatsBar")
        self.stats_bar.setMinimumHeight(16)  # Compact height
        root.addWidget(self.stats_bar)

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
        self.overview_panel.data_loaded.connect(self.operations_panel.update_records_cache)

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

        # Overview stats -> status bar
        self.overview_panel.stats_changed.connect(self._update_stats_bar)
        self.overview_panel.hover_stats_changed.connect(self._update_hover_stats)

        # Hide summary cards (stats shown in status bar instead)
        self.overview_panel.set_summary_cards_visible(False)

    def _setup_shortcuts(self):
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.setContext(Qt.WindowShortcut)
        self._find_shortcut.activated.connect(self._focus_overview_search)

    def _focus_overview_search(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return

        overview = getattr(self, "overview_panel", None)
        if overview is None:
            return

        search = getattr(overview, "ov_filter_keyword", None)
        if search is None:
            return

        search.setFocus(Qt.ShortcutFocusReason)
        search.selectAll()

    def show_status(self, msg, timeout=2000, level="info"):
        self.statusBar().showMessage(msg, timeout)

    def _update_stats_bar(self, stats):
        self._state_flow.update_stats_bar(stats)

    def _update_hover_stats(self, hover_text):
        self._state_flow.update_hover_stats(hover_text)

    def _show_nonblocking_dialog(self, dialog):
        """Show dialog without modal lock and keep Python reference alive."""
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setModal(False)
        self._floating_dialog_refs.append(dialog)

        def _release_ref(_result=0):
            with suppress(ValueError):
                self._floating_dialog_refs.remove(dialog)

        dialog.finished.connect(_release_ref)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _check_release_notice_once(self):
        self._startup_flow.check_release_notice_once()

    @Slot(str, str)
    def _show_update_dialog(self, latest_tag, release_notes):
        self._startup_flow.show_update_dialog(latest_tag, release_notes)

    def _check_empty_inventory_onboarding(self):
        self._startup_flow.check_empty_inventory_onboarding()

    def _wire_plan_store(self):
        self._state_flow.wire_plan_store()

    def on_operation_completed(self, success):
        self._state_flow.on_operation_completed(success)

    def _update_dataset_label(self):
        if hasattr(self, "_state_flow"):
            self._state_flow.update_dataset_label()
            return
        self.dataset_label.setText(self.current_yaml_path)

    def on_open_settings(self):
        previous_yaml_abs = os.path.abspath(str(self.current_yaml_path or ""))
        dialog = SettingsDialog(
            self,
            config={
                "yaml_path": self.current_yaml_path,
                "api_keys": self.gui_config.get("api_keys", {}),
                "ai": self.gui_config.get("ai", {}),
                "language": self.gui_config.get("language", "en"),
                "theme": self.gui_config.get("theme", "dark"),
                "ui_scale": self.gui_config.get("ui_scale", 1.0),
            },
            on_create_new_dataset=self.on_create_new_dataset,
            on_manage_boxes=self.on_manage_boxes,
            on_data_changed=self._on_settings_data_changed,
            app_version=APP_VERSION,
            app_release_url=APP_RELEASE_URL,
            github_api_latest=_GITHUB_API_LATEST,
            root_dir=ROOT,
            export_task_bundle_dialog_cls=ExportTaskBundleDialog,
            import_validated_yaml_dialog_cls=ImportValidatedYamlDialog,
            custom_fields_dialog_cls=CustomFieldsDialog,
            normalize_yaml_path=_normalize_inventory_yaml_path,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.get_values()
        selected_yaml = _normalize_inventory_yaml_path(values["yaml_path"])
        self.current_yaml_path = selected_yaml or self.current_yaml_path or YAML_PATH
        self._settings_flow.apply_dialog_values(values)

        new_yaml_abs = os.path.abspath(str(self.current_yaml_path or ""))
        if previous_yaml_abs != new_yaml_abs:
            self.operations_panel.reset_for_dataset_switch()

        self._settings_flow.finalize_after_settings()

    def _on_settings_data_changed(self, *, yaml_path=None, meta=None):
        self._settings_flow.handle_data_changed(yaml_path=yaml_path, meta=meta)

    def on_open_audit_log(self):
        """Open audit log dialog."""
        from app_gui.ui.audit_dialog import AuditLogDialog

        dialog = AuditLogDialog(
            self,
            yaml_path_getter=lambda: self.current_yaml_path,
            bridge=self.bridge
        )
        dialog.exec()  # Modal dialog

    def on_manage_boxes(self, yaml_path_override=None):
        self._boxes_flow.manage_boxes(yaml_path_override=yaml_path_override)

    def handle_manage_boxes_request(self, request, from_ai=True, yaml_path_override=None):
        return self._boxes_flow.handle_request(
            request,
            from_ai=from_ai,
            yaml_path_override=yaml_path_override,
        )

    def on_create_new_dataset(self, update_window=True):
        previous_yaml_abs = os.path.abspath(str(self.current_yaml_path or ""))
        layout_dlg = NewDatasetDialog(self)
        if layout_dlg.exec() != QDialog.Accepted:
            return
        box_layout = layout_dlg.get_layout()

        default_path = str(self.current_yaml_path or "").strip()
        if not default_path:
            default_path = os.getcwd()
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("main.new"),
            default_path,
            "YAML Files (*.yaml *.yml)",
        )
        if not target_path:
            return

        target_path = _normalize_inventory_yaml_path(target_path)
        created_path = self._dataset_flow.create_dataset_file(
            target_path=target_path,
            box_layout=box_layout,
            custom_fields_dialog_cls=CustomFieldsDialog,
        )
        if not created_path:
            return

        if not update_window:
            return created_path

        self.current_yaml_path = created_path
        if previous_yaml_abs != os.path.abspath(str(self.current_yaml_path or "")):
            self.operations_panel.reset_for_dataset_switch()
        self._update_dataset_label()
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)
        self.overview_panel.refresh()
        self.statusBar().showMessage(
            t("main.fileCreated", path=self.current_yaml_path),
            4000,
        )
        return created_path

    def restore_ui_settings(self):
        self._state_flow.restore_ui_settings()

    def closeEvent(self, event):
        if not self._state_flow.handle_close_event(event):
            return
        super().closeEvent(event)

def main():
    # Load GUI config BEFORE creating QApplication to set scale factor
    gui_config = load_gui_config()
    ui_scale = gui_config.get("ui_scale", 1.0)

    # Set scale factor BEFORE creating QApplication (Qt 6 method)
    if ui_scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(ui_scale)
        # Also set Qt 6 specific environment variables
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

    # Enable high DPI scaling for Qt 6
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)

    # Set application icon (taskbar, window title bar, etc.)
    icon_candidates = [
        os.path.join(ROOT, "app_gui", "assets", "snowfox-icon-v3.png"),
        os.path.join(ROOT, "app_gui", "assets", "snowfox-icon-v2.png"),
        os.path.join(ROOT, "app_gui", "assets", "snowfox-icon-v1.png"),
        os.path.join(ROOT, "app_gui", "assets", "icon.png"),
    ]
    for icon_path in icon_candidates:
        if os.path.isfile(icon_path):
            from PySide6.QtGui import QIcon
            app.setWindowIcon(QIcon(icon_path))
            break

    theme = gui_config.get("theme", "dark")

    # Set icon color based on theme
    if theme == "light":
        set_icon_color(resolve_theme_token("icon-default", mode="light", fallback="#000000"))
        apply_light_theme(app)
    else:
        set_icon_color(resolve_theme_token("icon-default", mode="dark", fallback="#ffffff"))
        apply_dark_theme(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

