"""Tests for main-window startup semantics after Quick Start removal."""

import importlib.util
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_FILE = ROOT / "app_gui" / "main.py"
FLOW_FILE = ROOT / "app_gui" / "main_window_flows.py"
DIALOG_FILES = [
    ROOT / "app_gui" / "ui" / "dialogs" / "settings_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "new_dataset_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "custom_fields_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "export_task_bundle_dialog.py",
    ROOT / "app_gui" / "ui" / "dialogs" / "import_validated_yaml_dialog.py",
]


def _source_text() -> str:
    return MAIN_FILE.read_text(encoding="utf-8")


def _combined_source_text() -> str:
    text = _source_text()
    if FLOW_FILE.exists():
        text += "\n" + FLOW_FILE.read_text(encoding="utf-8")
    for dialog_file in DIALOG_FILES:
        if dialog_file.exists():
            text += "\n" + dialog_file.read_text(encoding="utf-8")
    return text


def test_quick_start_code_paths_removed():
    text = _source_text()

    assert "class QuickStartDialog" not in text
    assert "on_quick_start" not in text
    assert "QuickStartDialog" not in text


def test_main_keeps_settings_entry_and_missing_file_hint():
    text = _source_text()

    assert re.search(r"settings_btn.clicked.connect", text)
    assert "main.fileNotFound" in text


def test_main_preserves_user_selected_inventory_filename_on_create():
    text = _source_text()

    assert 'INVENTORY_FILE_NAME = "ln2_inventory.yaml"' not in text
    assert "target_path = _normalize_inventory_yaml_path(target_path)" in text
    assert "default_path = os.getcwd()" in text
    assert "_normalize_inventory_yaml_path(target_path, force_canonical_file=True)" not in text
    assert "return os.path.join(abs_path, INVENTORY_FILE_NAME)" not in text


def test_settings_new_dataset_switches_immediately():
    text = _combined_source_text()

    assert "self._on_create_new_dataset(update_window=True)" in text


def test_settings_dialog_enforces_existing_yaml_file_before_ok():
    text = _combined_source_text()

    assert "def _is_valid_inventory_file_path(path_text):" in text
    assert "suffix not in {\".yaml\", \".yml\"}" in text
    assert "return os.path.isfile(path)" in text
    assert "self._ok_button = buttons.button(QDialogButtonBox.Ok)" in text
    assert "self.yaml_edit.textChanged.connect(self._refresh_yaml_path_validity)" in text
    assert "self._ok_button.setEnabled(self._is_valid_inventory_file_path(self.yaml_edit.text().strip()))" in text


def test_dataset_switch_resets_plan_and_undo_state():
    text = _source_text()

    assert text.count("self.operations_panel.reset_for_dataset_switch()") >= 2


def test_qsettings_migration_is_guarded_by_marker():
    text = _source_text()

    assert 'migration/unified_config_done' in text
    assert 'self.settings.setValue("migration/unified_config_done", True)' in text
    assert 'ui/current_yaml_path' not in text


def test_settings_accept_does_not_force_rename_existing_yaml_filename():
    text = _source_text()

    assert 'selected_yaml = _normalize_inventory_yaml_path(values["yaml_path"])' in text


def test_demo_yaml_path_is_preserved():
    text = _source_text()

    assert '".demo." in os.path.basename(abs_path).lower()' in text


def test_path_utils_module_is_not_imported_by_main():
    spec = importlib.util.spec_from_file_location("_main", str(MAIN_FILE))
    assert spec is not None
    assert "resolve_demo_dataset_path" not in (MAIN_FILE.read_text(encoding="utf-8") )


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

    assert "APP_VERSION = " in text
    assert re.search(r'APP_VERSION\s*=\s*"[\d.]+"', text)
    assert re.search(r'v\{APP_VERSION\}', text) or re.search(r'v\{self\._app_version\}', text)
    assert "APP_RELEASE_URL" in text
    assert "_check_release_notice_once" in text
    assert "_is_version_newer" in text or "_parse_version" in text


def test_startup_checks_are_deferred_until_window_show():
    text = _source_text()

    assert "def showEvent(self, event):" in text
    assert "self._startup_checks_scheduled = True" in text
    assert "QTimer.singleShot(150, self._run_startup_checks)" in text
    assert "def _run_startup_checks(self):" in text


def test_startup_dialogs_use_non_blocking_open_and_fixed_tag_parsing():
    text = _combined_source_text()

    assert "def _show_nonblocking_dialog(" in text
    assert "dialog.setWindowModality(Qt.NonModal)" in text
    assert "dialog.show()" in text
    assert 'msg_box.addButton(tr("main.exportTaskBundleTitle"), QMessageBox.ActionRole)' in text
    assert 'msg_box.addButton(tr("main.importValidatedTitle"), QMessageBox.ActionRole)' in text
    assert 'msg_box.addButton(tr("main.new"), QMessageBox.ActionRole)' in text
    assert "QMessageBox.Close" in text
    assert '.lstrip("1.0.1")' not in text
    assert '.lstrip("vV")' in text
