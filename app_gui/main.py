"""Desktop GUI for LN2 inventory operations (Refactored)."""

import os
import sys
from contextlib import suppress
from PySide6.QtCore import Qt, QSettings, Slot, QTimer, QSize, QSignalBlocker
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSplitter, QComboBox,
    QDialog, QFileDialog, QLineEdit, QInputDialog, QMessageBox, QTextEdit, QPlainTextEdit, QCheckBox,
)

if getattr(sys, "frozen", False):
    ROOT = sys._MEIPASS
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from app_gui.single_instance import SingleInstanceLock
from app_gui.tool_bridge import GuiToolBridge
from app_gui.agent_session import AgentSessionService
from app_gui.application import (
    apply_qt_scale_environment,
    BoxLayoutMutationUseCase,
    coerce_ui_scale,
    DataRootUseCase,
    DatasetLifecycleUseCase,
    DatasetUseCase,
    EventBus,
    MigrationModeUseCase,
    PlanExecutionUseCase,
)
from app_gui.application.ai_provider_catalog import AI_PROVIDER_DEFAULTS, DEFAULT_AI_PROVIDER, default_ai_model
from app_gui.application.manage_boxes_flow import ManageBoxesFlow
from app_gui.application.open_api import (
    LOCAL_OPEN_API_DEFAULT_PORT,
    LocalOpenApiController,
    LocalOpenApiService,
    MainThreadDispatcher,
)
from app_gui.gui_config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_MAX_STEPS,
    config_file_exists,
    load_gui_config,
    save_gui_config,
)
from app_gui.i18n import t, tr, set_language
from lib.inventory_paths import (
    assert_allowed_inventory_yaml_path,
    build_dataset_combo_items,
    create_managed_dataset_yaml_path,
    list_managed_datasets,
    normalize_inventory_yaml_path as _normalize_inventory_yaml_path,
    sanitize_dataset_name,
)
from lib.app_storage import (
    get_legacy_data_root,
    get_legacy_inventories_root,
    get_legacy_migrate_root,
    has_any_legacy_data,
    normalize_data_root,
    set_session_data_root,
)
from lib.plan_store import PlanStore
from app_gui.ui.theme import (
    apply_dark_theme, apply_light_theme,
    resolve_theme_token,
    SPACE_1, SPACE_2, SPACE_4,
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
    HelpDialog,
    NewDatasetDialog,
    CustomFieldsDialog,
)
from app_gui.ui.dialogs.common import create_message_box, show_info_message, show_warning_message
from app_gui.ui.icons import get_icon, Icons, set_icon_color
from app_gui.system_notice import build_system_notice
from app_gui.main_window_flows import (
    StartupFlow,
    WindowStateFlow,
    SettingsFlow,
    DatasetFlow,
)
from app_gui.dataset_session import DatasetSessionController
from app_gui.import_journey import ImportJourneyService
from app_gui.migration_workspace import MigrationWorkspaceService
from app_gui.version import APP_VERSION, APP_RELEASE_URL, UPDATE_CHECK_URL, is_version_newer
from lib.domain.events import DatasetSwitched, MigrationModeChanged, OperationExecuted

PROVIDER_DEFAULTS = AI_PROVIDER_DEFAULTS
_SETTINGS_EXPORTS = (PROVIDER_DEFAULTS,)


def _coerce_ui_scale(value, default=1.0) -> float:
    """Parse UI scale as positive float with a safe fallback."""
    return coerce_ui_scale(value, default=default)


def _detect_primary_screen_pixels_windows():
    """Return primary-screen physical pixels on Windows, otherwise None."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
    except Exception:
        return None

    # Best effort: request DPI awareness before probing metrics.
    with suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    with suppress(Exception):
        user32.SetProcessDPIAware()

    # Prefer physical desktop resolution from GDI device caps.
    dc = 0
    try:
        dc = user32.GetDC(0)
        if dc:
            width = int(gdi32.GetDeviceCaps(dc, 118))   # DESKTOPHORZRES
            height = int(gdi32.GetDeviceCaps(dc, 117))  # DESKTOPVERTRES
            if width > 0 and height > 0:
                return (width, height)
    except Exception:
        pass
    finally:
        if dc:
            with suppress(Exception):
                user32.ReleaseDC(0, dc)

    # Fallback metrics (may be logical when DPI virtualization applies).
    with suppress(Exception):
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        if width > 0 and height > 0:
            return (width, height)
    return None


def _is_primary_screen_4k_windows() -> bool:
    """Check whether Windows primary screen is at least 3840x2160."""
    pixels = _detect_primary_screen_pixels_windows()
    if not pixels:
        return False
    width, height = pixels
    return int(width) >= 3840 and int(height) >= 2160


def _resolve_startup_ui_scale(*, config_exists: bool, configured_scale) -> float:
    """Resolve startup UI scale without overriding existing user settings."""
    scale = _coerce_ui_scale(configured_scale, default=1.0)
    if bool(config_exists):
        return scale
    if _is_primary_screen_4k_windows():
        return 1.25
    return scale


def _default_inventory_payload():
    return DatasetLifecycleUseCase().default_inventory_payload()


def _write_inventory_yaml(path, payload=None):
    return DatasetLifecycleUseCase().write_inventory_yaml(path, payload)


def _resolve_managed_startup_yaml_path(configured_yaml_path):
    """Resolve active YAML path under managed-inventories lock mode."""
    return DatasetLifecycleUseCase().resolve_startup_yaml_path(
        configured_yaml_path=configured_yaml_path,
    )


def _choose_data_root(parent=None, *, title="", initial_dir="") -> str:
    return normalize_data_root(
        QFileDialog.getExistingDirectory(
            parent,
            str(title or tr("settings.changeDataRoot")),
            str(initial_dir or os.path.expanduser("~")),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
    )


def _bootstrap_data_root(app, gui_config: dict) -> bool:
    del app
    data_root = normalize_data_root(gui_config.get("data_root"))
    if data_root:
        set_session_data_root(data_root)
        return True

    use_case = DataRootUseCase()
    legacy_root = get_legacy_data_root()
    initial_dir = legacy_root if has_any_legacy_data() else os.path.expanduser("~")

    if has_any_legacy_data():
        intro_text = tr("main.dataRootSetupLegacyText")
        intro_detail = tr("main.dataRootSetupLegacyDetail")
    else:
        intro_text = tr("main.dataRootSetupText")
        intro_detail = tr("main.dataRootSetupDetail")

    intro = create_message_box(
        None,
        title=tr("main.dataRootSetupTitle"),
        text=intro_text,
        informative_text=intro_detail,
        icon=QMessageBox.Information,
        message_box_cls=QMessageBox,
    )
    choose_btn = intro.addButton(tr("main.dataRootChooseAction"), QMessageBox.AcceptRole)
    intro.addButton(tr("common.cancel"), QMessageBox.RejectRole)
    intro.setDefaultButton(choose_btn)
    intro.exec()
    if intro.clickedButton() != choose_btn:
        return False

    selected_root = _choose_data_root(
        None,
        title=tr("main.dataRootChooseTitle"),
        initial_dir=initial_dir,
    )
    if not selected_root:
        return False

    try:
        if has_any_legacy_data():
            result = use_case.migrate_root(
                source_root=legacy_root,
                target_root=selected_root,
                current_yaml_path=gui_config.get("yaml_path") or "",
            )
        else:
            result = use_case.initialize_root(target_root=selected_root)
    except Exception as exc:
        show_warning_message(
            None,
            title=tr("main.dataRootSetupTitle"),
            text=t("main.dataRootSetupFailed", error=str(exc)),
            message_box_cls=QMessageBox,
        )
        return False

    gui_config["data_root"] = result.data_root
    if result.yaml_path:
        gui_config["yaml_path"] = result.yaml_path
    save_gui_config(gui_config)
    set_session_data_root(result.data_root)
    return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("EamonFox", "LN2InventoryAgent")
        config_exists = config_file_exists(DEFAULT_CONFIG_FILE)
        self.gui_config = load_gui_config()
        self.gui_config["data_root"] = normalize_data_root(self.gui_config.get("data_root"))
        set_session_data_root(self.gui_config.get("data_root"))
        self._data_root_use_case = DataRootUseCase()
        if not config_exists:
            self.gui_config["ui_scale"] = _resolve_startup_ui_scale(
                config_exists=False,
                configured_scale=self.gui_config.get("ui_scale", 1.0),
            )
        set_language(self.gui_config.get("language") or "zh-CN")

        self.setWindowTitle(tr("app.title"))
        self.resize(1300, 900)

        self.bridge = GuiToolBridge()
        self.agent_session = AgentSessionService()
        self.agent_session.set_api_keys(self.gui_config.get("api_keys", {}))
        self._dataset_lifecycle = DatasetLifecycleUseCase()

        # One-time migration from legacy QSettings if unified config file does not exist yet.
        # Guarded by a dedicated marker to avoid re-importing stale paths after users
        # intentionally remove managed config.yaml.
        migrated_once = self.settings.value("migration/unified_config_done", False, type=bool)
        if (not config_exists) and (not migrated_once):
            migrated_model = self.settings.value("ai/model", "", type=str)
            migrated_steps = self.settings.value("ai/max_steps", DEFAULT_MAX_STEPS, type=int)
            self.gui_config["ai"] = {
                "provider": DEFAULT_AI_PROVIDER,
                "model": migrated_model or default_ai_model(DEFAULT_AI_PROVIDER),
                "max_steps": migrated_steps,
                "thinking_enabled": True,
            }
            save_gui_config(self.gui_config)
            self.settings.setValue("migration/unified_config_done", True)

        configured_yaml = _normalize_inventory_yaml_path(self.gui_config.get("yaml_path") or "")
        self.current_yaml_path = self._dataset_lifecycle.resolve_startup_yaml_path(
            configured_yaml_path=configured_yaml,
        )
        self._migration_mode_enabled = False
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)

        self.setup_ui()
        self._app_event_bus = EventBus()
        self._dataset_use_case = DatasetUseCase(
            normalize_yaml_path=_normalize_inventory_yaml_path,
            assert_allowed_path=assert_allowed_inventory_yaml_path,
            save_gui_config=save_gui_config,
            ensure_runtime_ready=lambda yaml_path: self._dataset_lifecycle.prepare_runtime_yaml_path(
                yaml_path,
                source="app_gui.dataset_switch",
            ),
            event_bus=self._app_event_bus,
        )
        self._migration_mode_use_case = MigrationModeUseCase(
            event_bus=self._app_event_bus,
        )
        self._plan_execution_use_case = PlanExecutionUseCase(
            event_bus=self._app_event_bus,
        )
        self._dataset_session = DatasetSessionController(
            self,
            dataset_use_case=self._dataset_use_case,
        )
        self._app_event_bus.subscribe(DatasetSwitched, self._on_dataset_switched_event)
        self._app_event_bus.subscribe(
            MigrationModeChanged,
            lambda event: self._apply_migration_mode_enabled(bool(getattr(event, "enabled", False))),
        )
        self._app_event_bus.subscribe(
            OperationExecuted,
            lambda event: self.on_operation_completed(bool(getattr(event, "success", False))),
        )
        self._import_journey = ImportJourneyService(
            workspace_service=MigrationWorkspaceService(),
        )
        self._state_flow = WindowStateFlow(self)
        self._startup_flow = StartupFlow(
            self,
            app_version=APP_VERSION,
            release_url=APP_RELEASE_URL,
            github_api_latest=UPDATE_CHECK_URL,
            is_version_newer=is_version_newer,
            show_nonblocking_dialog=self._show_nonblocking_dialog,
            start_import_journey=self.on_import_existing_data,
        )
        self._settings_flow = SettingsFlow(self, normalize_yaml_path=_normalize_inventory_yaml_path)
        self._dataset_flow = DatasetFlow(
            self,
            dataset_lifecycle_use_case=self._dataset_lifecycle,
        )
        self._box_layout_mutation_use_case = BoxLayoutMutationUseCase(
            bridge=self.bridge,
            current_yaml_path_getter=lambda: self.current_yaml_path,
        )
        self._boxes_flow = ManageBoxesFlow(
            self,
            mutation_use_case=self._box_layout_mutation_use_case,
        )
        self._local_open_api_dispatcher = MainThreadDispatcher(self)
        self._local_open_api_controller = LocalOpenApiController(
            yaml_path_getter=lambda: self.current_yaml_path,
            bridge=self.bridge,
            plan_store=self.plan_store,
            gui_dispatcher=self._local_open_api_dispatcher,
            list_datasets_fn=list_managed_datasets,
            switch_dataset_fn=lambda yaml_path, reason: self._dataset_session.switch_to(
                yaml_path,
                reason=reason,
            ),
            focus_window_fn=self._focus_main_window_for_external_api,
            prefill_takeout_fn=self.operations_panel.set_prefill,
            prefill_add_fn=self.operations_panel.set_add_prefill,
            prefill_ai_prompt_fn=lambda prompt, focus: self.ai_panel.prepare_external_prompt(
                prompt,
                focus=focus,
                clear_plan=False,
            ),
        )
        self._local_open_api_service = LocalOpenApiService(
            self._local_open_api_controller,
            port=int((self.gui_config.get("open_api") or {}).get("port", LOCAL_OPEN_API_DEFAULT_PORT) or LOCAL_OPEN_API_DEFAULT_PORT),
        )
        self.connect_signals()
        self._setup_shortcuts()
        self.restore_ui_settings()
        self._startup_checks_scheduled = False
        self._floating_dialog_refs = []
        self._migration_status_indicator = QLabel(tr("main.migrationModeStatus"))
        self._migration_status_indicator.setObjectName("mainMigrationStatusIndicator")
        self._migration_status_indicator.setVisible(False)
        self.statusBar().addPermanentWidget(self._migration_status_indicator)

        self.statusBar().showMessage(tr("app.ready"), 2000)
        self._apply_local_open_api_settings(show_feedback=False)
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

    def _ensure_dataset_lifecycle(self):
        lifecycle = getattr(self, "_dataset_lifecycle", None)
        if lifecycle is None:
            lifecycle = DatasetLifecycleUseCase()
            self._dataset_lifecycle = lifecycle
        return lifecycle

    def setup_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_1)
        root.setSpacing(SPACE_1)

        # Top Bar
        top = QHBoxLayout()
        self.home_dataset_switch_label = QLabel(tr("main.datasetSwitch"))
        top.addWidget(self.home_dataset_switch_label)

        self.home_dataset_switch_combo = QComboBox()
        self.home_dataset_switch_combo.setMinimumWidth(180)
        self.home_dataset_switch_combo.currentIndexChanged.connect(self._on_home_dataset_switch_changed)
        top.addWidget(self.home_dataset_switch_combo)

        top.addStretch(1)

        self.migration_mode_badge = QLabel(tr("main.migrationModeBadge"))
        self.migration_mode_badge.setObjectName("mainMigrationModeBadge")
        self.migration_mode_badge.setVisible(False)
        top.addWidget(self.migration_mode_badge)

        new_dataset_btn = QPushButton()
        new_dataset_btn.setObjectName("mainToolbarIconBtn")
        new_dataset_btn.setIcon(get_icon(Icons.FILE_PLUS))
        new_dataset_btn.setIconSize(QSize(16, 16))
        new_dataset_btn.setFixedSize(28, 28)
        new_dataset_btn.setToolTip(tr("main.new"))
        new_dataset_btn.setAccessibleName(tr("main.new"))
        new_dataset_btn.clicked.connect(self.on_create_new_dataset)
        top.addWidget(new_dataset_btn)

        audit_log_btn = QPushButton()
        audit_log_btn.setObjectName("mainToolbarIconBtn")
        audit_log_btn.setIcon(get_icon(Icons.FILE_TEXT))
        audit_log_btn.setIconSize(QSize(16, 16))
        audit_log_btn.setFixedSize(28, 28)
        audit_log_btn.setToolTip(tr("main.auditLog"))
        audit_log_btn.setAccessibleName(tr("main.auditLog"))
        audit_log_btn.clicked.connect(self.on_open_audit_log)
        top.addWidget(audit_log_btn)

        help_btn = QPushButton()
        help_btn.setObjectName("mainToolbarIconBtn")
        help_btn.setIcon(get_icon(Icons.HELP_CIRCLE))
        help_btn.setIconSize(QSize(16, 16))
        help_btn.setFixedSize(28, 28)
        help_btn.setToolTip(tr("main.help"))
        help_btn.setAccessibleName(tr("main.help"))
        help_btn.clicked.connect(self.on_open_help)
        top.addWidget(help_btn)

        settings_btn = QPushButton()
        settings_btn.setObjectName("mainToolbarIconBtn")
        settings_btn.setIcon(get_icon(Icons.SETTINGS))
        settings_btn.setIconSize(QSize(16, 16))
        settings_btn.setFixedSize(28, 28)
        settings_btn.setToolTip(tr("main.settings"))
        settings_btn.setAccessibleName(tr("main.settings"))
        settings_btn.clicked.connect(self.on_open_settings)
        top.addWidget(settings_btn)

        self._refresh_home_dataset_choices(selected_yaml=self.current_yaml_path)

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
            import_dataset_handler=self._handle_ai_imported_dataset,
            agent_session=self.agent_session,
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
        self.stats_bar.setMinimumHeight(SPACE_4)  # Compact height
        root.addWidget(self.stats_bar)

        self.setCentralWidget(container)

    def connect_signals(self):
        # Overview -> Operations (Plan staging)
        self.overview_panel.plan_items_requested.connect(
            self.operations_panel.add_plan_items)
        self.overview_panel.plan_item_removal_requested.connect(
            self.operations_panel.remove_plan_items_by_payload)

        # Overview -> Operations (prefill)
        self.overview_panel.request_prefill.connect(self.operations_panel.set_prefill)
        self.overview_panel.request_prefill_background.connect(self.operations_panel.set_prefill_background)
        self.overview_panel.request_add_prefill.connect(self.operations_panel.set_add_prefill)
        self.overview_panel.request_add_prefill_background.connect(self.operations_panel.set_add_prefill_background)
        self.overview_panel.request_export_inventory_csv.connect(self.operations_panel.on_export_inventory_csv)
        self.overview_panel.data_loaded.connect(self.operations_panel.update_records_cache)
        self.overview_panel.operation_event.connect(self.operations_panel.emit_external_operation_event)

        # Operations -> Overview (refresh after execution)
        self.operations_panel.operation_completed.connect(
            lambda success: self._dispatch_operation_completed(
                success,
                operation="plan_execute",
                source="operations_panel",
            )
        )

        # Operations -> AI (operation events for context)
        self.operations_panel.operation_event.connect(self.ai_panel.on_operation_event)

        # AI -> Operations: agent writes to plan_store directly;
        # on_change callback triggers GUI refresh (see _wire_plan_store below).
        self.ai_panel.operation_completed.connect(
            lambda success: self._dispatch_operation_completed(
                success,
                operation="ai_operation",
                source="ai_panel",
            )
        )
        self.ai_panel.migration_mode_changed.connect(
            lambda enabled: self._request_migration_mode_change(
                enabled,
                reason="ai_panel",
            )
        )

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

    def _emit_system_notice(
        self,
        *,
        code,
        text,
        level="info",
        source="main_window",
        timeout_ms=2000,
        details=None,
        data=None,
    ):
        notice = build_system_notice(
            code=str(code or "notice"),
            text=str(text or ""),
            level=str(level or "info"),
            source=str(source or "main_window"),
            timeout_ms=int(timeout_ms or 0),
            details=str(details) if details else None,
            data=data if isinstance(data, dict) else None,
        )
        self.operations_panel.emit_external_operation_event(notice)
        return notice

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

    @Slot(str, str, str)
    def _show_update_dialog(self, latest_tag, release_notes, download_url):
        self._startup_flow.show_update_dialog(latest_tag, release_notes, download_url)

    def _check_empty_inventory_onboarding(self):
        self._startup_flow.check_empty_inventory_onboarding()

    def _wire_plan_store(self):
        self._state_flow.wire_plan_store()

    def on_operation_completed(self, success):
        self._state_flow.on_operation_completed(success)

    def _on_dataset_switched_event(self, event):
        target = str(getattr(event, "new_path", "") or getattr(self, "current_yaml_path", "") or "")
        old_abs = os.path.abspath(str(getattr(event, "old_path", "") or ""))
        new_abs = os.path.abspath(target) if target else ""

        for owner, method_name in (
            (getattr(self, "operations_panel", None), "reset_for_dataset_switch"),
            (self, "_update_dataset_label"),
            (getattr(self, "overview_panel", None), "refresh"),
        ):
            callback = getattr(owner, method_name, None) if owner is not None else None
            if callable(callback):
                callback()

        self._emit_system_notice(
            code="dataset.switch",
            text=f"{tr('settings.datasetSwitch')} {target}",
            level="info",
            source="main_window",
            timeout_ms=3000,
            data={
                "reason": str(getattr(event, "reason", "manual_switch") or "manual_switch"),
                "from_path": old_abs,
                "to_path": new_abs,
            },
        )

    def _dispatch_operation_completed(self, success, *, operation, source):
        use_case = getattr(self, "_plan_execution_use_case", None)
        if use_case is None:
            self.on_operation_completed(success)
            return
        use_case.report_operation_completed(
            success=bool(success),
            operation=str(operation or "plan_execute"),
            source=str(source or "ui"),
        )

    def _request_migration_mode_change(self, enabled, *, reason):
        use_case = getattr(self, "_migration_mode_use_case", None)
        if use_case is None:
            self._apply_migration_mode_enabled(enabled)
            return
        use_case.set_mode(
            enabled=bool(enabled),
            reason=str(reason or "ai_panel"),
        )

    def _apply_migration_mode_enabled(self, enabled):
        locked = bool(enabled)
        if bool(getattr(self, "_migration_mode_enabled", False)) == locked:
            return
        self._migration_mode_enabled = locked
        badge = getattr(self, "migration_mode_badge", None)
        if badge is not None:
            badge.setVisible(locked)
        status_indicator = getattr(self, "_migration_status_indicator", None)
        if status_indicator is not None:
            status_indicator.setVisible(locked)
        operations_panel = getattr(self, "operations_panel", None)
        if operations_panel is not None and hasattr(operations_panel, "set_migration_mode_enabled"):
            operations_panel.set_migration_mode_enabled(locked)

    def _show_migration_mode_entry_notice(self):
        cfg = self.gui_config if isinstance(getattr(self, "gui_config", None), dict) else {}
        if bool(cfg.get("migration_mode_notice_suppressed", False)):
            return

        msg_box = create_message_box(
            self,
            title=tr("main.migrationModeDialogTitle"),
            text=tr("main.migrationModeDialogText"),
            icon=QMessageBox.Information,
            message_box_cls=QMessageBox,
        )

        dont_show_cb = QCheckBox(tr("main.doNotShowAgain"), msg_box)
        msg_box.setCheckBox(dont_show_cb)
        ok_btn = msg_box.addButton(tr("common.ok"), QMessageBox.AcceptRole)
        msg_box.setDefaultButton(ok_btn)

        def _persist_notice_choice(_result=0):
            cb = msg_box.checkBox()
            if cb is None or not cb.isChecked():
                return
            cfg["migration_mode_notice_suppressed"] = True
            self.gui_config = cfg
            save_gui_config(cfg)

        msg_box.finished.connect(_persist_notice_choice)
        self._show_nonblocking_dialog(msg_box)

    def _update_dataset_label(self):
        if hasattr(self, "_state_flow"):
            self._state_flow.update_dataset_label()
        else:
            label = getattr(self, "dataset_label", None)
            if label is not None and hasattr(label, "setText"):
                current_path = str(self.current_yaml_path or "")
                dataset_name = os.path.basename(os.path.dirname(current_path)) or os.path.basename(current_path) or "-"
                label.setText(dataset_name)
                if hasattr(label, "setToolTip"):
                    label.setToolTip(current_path)
        self._refresh_home_dataset_choices(selected_yaml=self.current_yaml_path)

    def _refresh_home_dataset_choices(self, selected_yaml=""):
        combo = getattr(self, "home_dataset_switch_combo", None)
        if combo is None:
            return

        rows = list_managed_datasets()
        current_yaml = _normalize_inventory_yaml_path(selected_yaml or self.current_yaml_path)
        items, selected_idx = build_dataset_combo_items(rows, current_yaml)

        with QSignalBlocker(combo):
            combo.clear()
            for name, yaml_path in items:
                combo.addItem(name, yaml_path)

            combo.setEnabled(bool(items))
            tooltip_text = ""
            if items:
                combo.setCurrentIndex(selected_idx)
                selected_path = combo.currentData()
                tooltip_text = str(selected_path or "")
            combo.setToolTip(tooltip_text)

    def _current_data_root(self) -> str:
        return normalize_data_root(self.gui_config.get("data_root"))

    def on_change_data_root(self, current_data_root=""):
        source_root = normalize_data_root(current_data_root) or self._current_data_root()
        target_root = _choose_data_root(
            self,
            title=tr("settings.changeDataRoot"),
            initial_dir=source_root or os.path.expanduser("~"),
        )
        if not target_root:
            return {}

        try:
            result = self._data_root_use_case.migrate_root(
                source_root=source_root,
                target_root=target_root,
                current_yaml_path=self.current_yaml_path,
            )
        except Exception as exc:
            show_warning_message(
                self,
                title=tr("settings.changeDataRoot"),
                text=t("settings.changeDataRootFailed", error=str(exc)),
                message_box_cls=QMessageBox,
            )
            return {}

        self.gui_config["data_root"] = result.data_root
        set_session_data_root(result.data_root)
        self.current_yaml_path = self._dataset_lifecycle.resolve_startup_yaml_path(
            configured_yaml_path=result.yaml_path or self.current_yaml_path,
        )
        self.gui_config["yaml_path"] = self.current_yaml_path
        save_gui_config(self.gui_config)
        self._import_journey = ImportJourneyService(
            workspace_service=MigrationWorkspaceService(),
        )
        self._refresh_home_dataset_choices(selected_yaml=self.current_yaml_path)
        self.overview_panel.refresh()
        self.operations_panel.apply_meta_update()
        self.statusBar().showMessage(
            t("settings.changeDataRootSuccess", path=result.data_root),
            5000,
        )
        return {
            "data_root": result.data_root,
            "yaml_path": self.current_yaml_path,
        }

    def _on_home_dataset_switch_changed(self):
        combo = getattr(self, "home_dataset_switch_combo", None)
        if combo is None:
            return

        selected_path = _normalize_inventory_yaml_path(combo.currentData())
        if not selected_path:
            return
        try:
            switched_path = self._dataset_session.switch_to(
                selected_path,
                reason="manual_switch",
            )
        except Exception as exc:
            self.statusBar().showMessage(str(exc), 5000)
            self._refresh_home_dataset_choices(selected_yaml=self.current_yaml_path)
            return
        self._refresh_home_dataset_choices(selected_yaml=switched_path)

    def on_open_settings(self):
        dialog = SettingsDialog(
            self,
            config={
                "data_root": self.gui_config.get("data_root", ""),
                "yaml_path": self.current_yaml_path,
                "api_keys": self.gui_config.get("api_keys", {}),
                "ai": self.gui_config.get("ai", {}),
                "open_api": self.gui_config.get("open_api", {}),
                "language": self.gui_config.get("language", "en"),
                "theme": self.gui_config.get("theme", "dark"),
                "ui_scale": self.gui_config.get("ui_scale", 1.0),
            },
            on_create_new_dataset=self.on_create_new_dataset,
            on_rename_dataset=self.on_rename_dataset,
            on_delete_dataset=self.on_delete_dataset,
            on_manage_boxes=self.on_manage_boxes,
            on_data_changed=self._on_settings_data_changed,
            on_change_data_root=self.on_change_data_root,
            app_version=APP_VERSION,
            app_release_url=APP_RELEASE_URL,
            github_api_latest=UPDATE_CHECK_URL,
            root_dir=ROOT,
            on_import_existing_data=self.on_import_existing_data,
            on_export_inventory_csv=self.operations_panel.on_export_inventory_csv,
            custom_fields_dialog_cls=CustomFieldsDialog,
            normalize_yaml_path=_normalize_inventory_yaml_path,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        submission = dialog.get_submission()
        selected_yaml = _normalize_inventory_yaml_path(submission.yaml_path)
        try:
            self._dataset_session.switch_to(selected_yaml, reason="manual_switch")
        except Exception as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self._settings_flow.apply_dialog_values(submission)
        self._settings_flow.finalize_after_settings()
        self._refresh_home_dataset_choices(selected_yaml=self.current_yaml_path)

    def on_open_help(self):
        dialog = HelpDialog(
            self,
            app_version=APP_VERSION,
            app_release_url=APP_RELEASE_URL,
            github_api_latest=UPDATE_CHECK_URL,
            root_dir=ROOT,
        )
        dialog.exec()

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

    def handle_manage_boxes_request(self, request, from_ai=True, yaml_path_override=None, on_result=None):
        if callable(on_result):
            return self._boxes_flow.handle_request_async(
                request,
                on_result=on_result,
                from_ai=from_ai,
                yaml_path_override=yaml_path_override,
            )
        return self._boxes_flow.handle_request(
            request,
            from_ai=from_ai,
            yaml_path_override=yaml_path_override,
        )

    def on_import_existing_data(self, checked=False, *, parent=None):
        _ = checked
        result = self._import_journey.run(
            parent=parent or self,
        )
        if result.ok:
            self._handoff_import_journey_to_ai(result)
            staged_text = tr("main.importJourneyStaged")
            self.statusBar().showMessage(
                staged_text,
                4000,
            )
            self._emit_system_notice(
                code="import.journey.staged",
                text=staged_text,
                level="info",
                source="import_journey",
                timeout_ms=4000,
                data={
                    "stage": str(result.stage or ""),
                },
            )
            return result.stage
        if result.error_code == "user_cancelled":
            return ""
        show_warning_message(
            self,
            title=tr("main.importExistingDataTitle"),
            text=result.message or tr("main.importValidatedFailed"),
            message_box_cls=QMessageBox,
        )
        failed_text = result.message or tr("main.importValidatedFailed")
        self.statusBar().showMessage(failed_text, 6000)
        self._emit_system_notice(
            code="import.journey.failed",
            text=failed_text,
            level="error",
            source="import_journey",
            timeout_ms=6000,
            data={
                "stage": str(result.stage or ""),
                "error_code": str(result.error_code or ""),
            },
        )
        return ""

    def _handoff_import_journey_to_ai(self, result):
        prompt_text = str(getattr(result, "ai_prompt", "") or "").strip()
        if not prompt_text:
            prompt_text = tr("main.importAiPromptFallback")
        self.ai_panel.prepare_import_migration(prompt_text, focus=True)

    def _handle_ai_imported_dataset(self, imported_yaml_path):
        switched_path = self._dataset_session.switch_to(
            imported_yaml_path,
            reason="import_success",
        )
        opened_text = t("main.importOpened", path=switched_path)
        self._refresh_home_dataset_choices(selected_yaml=switched_path)
        self.statusBar().showMessage(
            opened_text,
            4000,
        )
        self._emit_system_notice(
            code="import.journey.opened",
            text=opened_text,
            level="success",
            source="import_journey",
            timeout_ms=4000,
            data={"yaml_path": switched_path},
        )
        return switched_path

    def on_rename_dataset(self, current_yaml_path, new_dataset_name):
        result = self._ensure_dataset_lifecycle().rename_dataset(
            current_yaml_path=current_yaml_path or self.current_yaml_path,
            new_dataset_name=new_dataset_name,
        )
        switched = self._dataset_session.switch_to(
            result.target_path,
            reason="dataset_rename",
        )
        self._refresh_home_dataset_choices(selected_yaml=switched)
        if result.audit_error:
            self.statusBar().showMessage(
                t("settings.renameDatasetSuccessWithAuditWarning", path=switched, error=result.audit_error),
                6000,
            )
        else:
            self.statusBar().showMessage(
                t("settings.renameDatasetSuccess", path=switched),
                4000,
            )
        return switched

    def on_delete_dataset(self, current_yaml_path):
        result = self._ensure_dataset_lifecycle().delete_dataset(
            current_yaml_path=current_yaml_path or self.current_yaml_path,
        )
        switched = self._dataset_session.switch_to(
            result.target_path,
            reason="dataset_delete",
        )
        self._refresh_home_dataset_choices(selected_yaml=switched)
        if result.audit_error:
            self.statusBar().showMessage(
                t("settings.deleteDatasetSuccessWithAuditWarning", path=switched, error=result.audit_error),
                6000,
            )
        else:
            self.statusBar().showMessage(
                t("settings.deleteDatasetSuccess", path=switched),
                4000,
            )
        return switched

    def on_create_new_dataset(self, update_window=True):
        layout_dlg = NewDatasetDialog(self)
        dialog_result = layout_dlg.exec()
        if dialog_result == NewDatasetDialog.RESULT_IMPORT_EXISTING:
            self.on_import_existing_data(parent=self)
            return
        if dialog_result != QDialog.Accepted:
            return
        box_layout = layout_dlg.get_layout()

        suggested = sanitize_dataset_name("", fallback="inventory")
        dataset_name, ok = QInputDialog.getText(
            self,
            tr("main.new"),
            tr("main.newDatasetNamePrompt"),
            text=suggested,
        )
        if not ok:
            return
        dataset_name = sanitize_dataset_name(dataset_name, fallback="inventory")
        try:
            target_path = create_managed_dataset_yaml_path(dataset_name)
        except Exception as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return

        created_path = self._dataset_flow.create_dataset_file(
            target_path=target_path,
            box_layout=box_layout,
            custom_fields_dialog_cls=CustomFieldsDialog,
        )
        if not created_path:
            with suppress(OSError):
                os.rmdir(os.path.dirname(target_path))
            return

        if not update_window:
            return created_path

        try:
            switched_path = self._dataset_session.switch_to(created_path, reason="new_dataset")
        except Exception as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self._refresh_home_dataset_choices(selected_yaml=switched_path)
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

    def _focus_main_window_for_external_api(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        return True

    def _current_local_open_api_config(self):
        config = self.gui_config.get("open_api", {})
        try:
            port = int(config.get("port", LOCAL_OPEN_API_DEFAULT_PORT))
        except Exception:
            port = LOCAL_OPEN_API_DEFAULT_PORT
        if port <= 0:
            port = LOCAL_OPEN_API_DEFAULT_PORT
        return {
            "enabled": bool(config.get("enabled", False)),
            "port": port,
        }

    def _apply_local_open_api_settings(self, *, show_feedback=False):
        service = getattr(self, "_local_open_api_service", None)
        if service is None or not hasattr(service, "configure"):
            return {
                "ok": False,
                "running": False,
                "changed": False,
                "message": "Local Open API service is unavailable.",
            }

        config = self._current_local_open_api_config()
        result = service.configure(
            enabled=bool(config.get("enabled", False)),
            port=int(config.get("port", LOCAL_OPEN_API_DEFAULT_PORT)),
        )
        if result.get("ok"):
            if show_feedback:
                if result.get("running"):
                    self.statusBar().showMessage(
                        t("main.localApiStarted", port=result.get("port")),
                        3000,
                    )
                else:
                    self.statusBar().showMessage(tr("main.localApiStopped"), 3000)
            return result

        message = t(
            "main.localApiStartFailed",
            error=result.get("message") or "unknown error",
        )
        self.statusBar().showMessage(message, 6000)
        if show_feedback:
            self._emit_system_notice(
                code="local_api.start_failed",
                text=message,
                level="error",
                source="settings_dialog",
                timeout_ms=6000,
                data={
                    "requested_port": int(config.get("port", LOCAL_OPEN_API_DEFAULT_PORT)),
                    "error_code": result.get("error_code"),
                },
            )
        return result

def main():
    # Load GUI config BEFORE creating QApplication to set scale factor
    config_exists = config_file_exists(DEFAULT_CONFIG_FILE)
    gui_config = load_gui_config()
    set_language(gui_config.get("language") or "zh-CN")
    ui_scale = _resolve_startup_ui_scale(
        config_exists=config_exists,
        configured_scale=gui_config.get("ui_scale", 1.0),
    )
    gui_config["ui_scale"] = ui_scale

    # Set scale factor BEFORE creating QApplication (Qt 6 method).
    apply_qt_scale_environment(ui_scale)

    # Enable high DPI scaling for Qt 6
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)

    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        show_info_message(
            None,
            title=tr("main.singleInstanceTitle"),
            text=tr("main.singleInstanceMessage"),
            message_box_cls=QMessageBox,
        )
        return 0

    if not _bootstrap_data_root(app, gui_config):
        instance_lock.release()
        return 0

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
    window._release_single_instance_lock = instance_lock.release
    window.show()
    try:
        exit_code = app.exec()
    finally:
        instance_lock.release()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
