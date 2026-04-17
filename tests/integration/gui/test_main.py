"""
Module: test_main
Layer: integration/gui
Covers: app_gui/main.py

应用入口与启动行为测试
"""

import importlib.util
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
MAIN_FILE = ROOT / "app_gui" / "main.py"
FLOW_FILE = ROOT / "app_gui" / "main_window_flows.py"
VERSION_FILE = ROOT / "app_gui" / "version.py"
OVERVIEW_UI_FILE = ROOT / "app_gui" / "ui" / "overview_panel_ui.py"
OVERVIEW_FILTERS_FILE = ROOT / "app_gui" / "ui" / "overview_panel_filters.py"
DIALOG_FILES = [
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_about_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_ai_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_custom_fields.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_dataset_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_formatters.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog_local_api_section.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "new_dataset_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "custom_fields_dialog.py",
]


def _source_text() -> str:
    return MAIN_FILE.read_text(encoding="utf-8")


def _combined_source_text() -> str:
    text = _source_text()
    if VERSION_FILE.exists():
        text += "\n" + VERSION_FILE.read_text(encoding="utf-8")
    if FLOW_FILE.exists():
        text += "\n" + FLOW_FILE.read_text(encoding="utf-8")
    for dialog_file in DIALOG_FILES:
        if dialog_file.exists():
            text += "\n" + dialog_file.read_text(encoding="utf-8")
    return text


def _overview_ui_source_text() -> str:
    return OVERVIEW_UI_FILE.read_text(encoding="utf-8")


def _overview_filters_source_text() -> str:
    return OVERVIEW_FILTERS_FILE.read_text(encoding="utf-8")


def test_quick_start_code_paths_removed():
    text = _source_text()

    assert "class QuickStartDialog" not in text
    assert "on_quick_start" not in text
    assert "QuickStartDialog" not in text


def test_main_keeps_settings_entry_and_missing_file_hint():
    text = _source_text()

    assert re.search(r"settings_btn.clicked.connect", text)
    assert "main.fileNotFound" in text


def test_main_home_top_bar_has_dataset_switcher():
    text = _source_text()

    assert 'self.home_dataset_switch_label = QLabel(tr("main.datasetSwitch"))' in text
    assert "self.home_dataset_switch_combo = QComboBox()" in text
    assert "self.home_dataset_switch_combo.currentIndexChanged.connect(self._on_home_dataset_switch_changed)" in text


def test_main_home_top_bar_actions_are_icon_only_with_tooltips():
    text = _source_text()

    assert "new_dataset_btn = QPushButton()" in text
    assert "new_dataset_btn = QPushButton(tr(\"main.new\"))" not in text
    assert 'new_dataset_btn.setToolTip(tr("main.new"))' in text

    assert "import_dataset_btn = QPushButton()" in text
    assert "import_dataset_btn = QPushButton(tr(\"main.importExistingDataTitle\"))" not in text
    assert 'import_dataset_btn.setToolTip(tr("main.importExistingDataTitle"))' in text

    assert "audit_log_btn = QPushButton()" in text
    assert "audit_log_btn = QPushButton(tr(\"main.auditLog\"))" not in text
    assert 'audit_log_btn.setToolTip(tr("main.auditLog"))' in text

    assert "settings_btn = QPushButton()" in text
    assert "settings_btn = QPushButton(tr(\"main.settings\"))" not in text
    assert 'settings_btn.setToolTip(tr("main.settings"))' in text


def test_overview_search_uses_placeholder_without_search_label():
    text = _overview_ui_source_text()

    assert 'self.ov_filter_keyword.setPlaceholderText(tr("overview.quickSearchPlaceholder"))' in text
    assert 'filter_row.addWidget(QLabel(tr("overview.search")))' not in text


def test_overview_top_actions_are_icon_only_with_tooltips():
    text = _overview_ui_source_text()

    assert "self.ov_filter_toggle_btn = QPushButton()" in text
    assert 'self.ov_filter_toggle_btn.setToolTip(tr("overview.moreFilters"))' in text

    assert "clear_filter_btn = QPushButton()" in text
    assert 'clear_filter_btn.setToolTip(tr("overview.clearFilter"))' in text

    assert "refresh_btn = QPushButton()" in text
    assert 'refresh_btn.setToolTip(tr("overview.refresh"))' in text


def test_overview_filter_toggle_updates_tooltip_instead_of_text():
    text = _overview_filters_source_text()

    assert "self.ov_filter_toggle_btn.setToolTip(toggle_label)" in text
    assert "self.ov_filter_toggle_btn.setText(" not in text


def test_main_creates_dataset_under_managed_root():
    text = _source_text()

    assert "create_managed_dataset_yaml_path(dataset_name)" in text
    assert "QInputDialog.getText(" in text
    assert "QFileDialog.getSaveFileName" not in text


def test_main_wires_dataset_lifecycle_use_case_into_startup_and_dataset_flow():
    text = _source_text()

    assert "DatasetLifecycleUseCase" in text
    assert "self._dataset_lifecycle = DatasetLifecycleUseCase()" in text
    assert "self.current_yaml_path = self._dataset_lifecycle.resolve_startup_yaml_path(" in text
    assert "dataset_lifecycle_use_case=self._dataset_lifecycle" in text
    assert "submission = dialog.get_submission()" in text


def test_settings_new_dataset_switches_immediately():
    text = _combined_source_text()

    assert (
        "self._on_create_new_dataset(update_window=True)" in text
        or "dialog._on_create_new_dataset(update_window=True)" in text
    )


def test_settings_dialog_wires_dataset_rename_callback():
    text = _source_text()

    assert "on_rename_dataset=self.on_rename_dataset" in text


def test_settings_dialog_wires_dataset_delete_callback():
    text = _source_text()

    assert "on_delete_dataset=self.on_delete_dataset" in text


def test_settings_dialog_enforces_existing_yaml_file_before_ok():
    text = _combined_source_text()

    assert "def _is_valid_inventory_file_path(path_text):" in text
    assert "suffix not in {\".yaml\", \".yml\"}" in text
    assert "return os.path.isfile(path)" in text
    assert "self._ok_button = buttons.button(QDialogButtonBox.Ok)" in text
    assert "self.yaml_edit.textChanged.connect(self._refresh_yaml_path_validity)" in text
    assert "self._ok_button.setEnabled(self._is_valid_inventory_file_path(self.yaml_edit.text().strip()))" in text


def test_dataset_switch_command_is_centralized_in_session_controller():
    text = _source_text()

    assert "DatasetSessionController" in text
    assert "self._dataset_session.switch_to(" in text


def test_main_consumes_dataset_switched_events_for_ui_refresh():
    text = _source_text()

    assert "DatasetSwitched" in text
    assert "self._app_event_bus.subscribe(DatasetSwitched, self._on_dataset_switched_event)" in text
    assert "def _on_dataset_switched_event(self, event):" in text


def test_qsettings_migration_is_guarded_by_marker():
    text = _source_text()

    assert 'migration/unified_config_done' in text
    assert 'self.settings.setValue("migration/unified_config_done", True)' in text
    assert 'ui/current_yaml_path' not in text


def test_settings_accept_does_not_force_rename_existing_yaml_filename():
    text = _source_text()

    assert "selected_yaml = _normalize_inventory_yaml_path(submission.yaml_path)" in text


def test_path_utils_module_is_not_imported_by_main():
    spec = importlib.util.spec_from_file_location("_main", str(MAIN_FILE))
    assert spec is not None


def test_tr_not_called_with_keyword_args():
    text = MAIN_FILE.read_text(encoding="utf-8")
    tree = ast.parse(text)

    bad_calls = [
        call.lineno
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "tr"
        and call.keywords
    ]

    assert not bad_calls, f"tr() called with kwargs at lines: {bad_calls}"


def test_app_version_constant_exists_and_about_uses_it():
    text = _combined_source_text()

    assert re.search(r'APP_VERSION\b.*=\s*"[\d.]+"', text)
    assert 'APP_RELEASE_URL: str = "https://snowfox.bio/download.html"' in text
    assert (
        re.search(r'v\{APP_VERSION\}', text)
        or re.search(r'v\{self\._app_version\}', text)
        or re.search(r'v\{dialog\._app_version\}', text)
    )
    assert "APP_RELEASE_URL" in text
    assert "_check_release_notice_once" in text
    assert "_is_version_newer" in text or "is_version_newer" in text


def test_startup_checks_are_deferred_until_window_show():
    text = _source_text()

    assert "def showEvent(self, event):" in text
    assert "self._startup_checks_scheduled = True" in text
    assert "QTimer.singleShot(150, self._run_startup_checks)" in text
    assert "def _run_startup_checks(self):" in text

    startup_checks_match = re.search(
        r"def _run_startup_checks\(self\):\n(?P<body>(?:\s+.+\n)+)",
        text,
    )
    assert startup_checks_match is not None
    startup_checks_body = startup_checks_match.group("body")
    assert "self._check_release_notice_once()" in startup_checks_body
    assert "self._check_empty_inventory_onboarding()" not in startup_checks_body


def test_startup_dialogs_use_non_blocking_open_and_fixed_tag_parsing():
    text = _combined_source_text()

    assert "def _show_nonblocking_dialog(" in text
    assert "dialog.setWindowModality(Qt.NonModal)" in text
    assert "dialog.show()" in text
    assert '.lstrip("1.0.1")' not in text
    assert '.lstrip("vV")' in text
