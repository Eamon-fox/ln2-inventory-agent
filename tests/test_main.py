"""Tests for main-window startup semantics after Quick Start removal."""

import importlib.util
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_FILE = ROOT / "app_gui" / "main.py"


def _source_text() -> str:
    return MAIN_FILE.read_text(encoding="utf-8")


def test_quick_start_code_paths_removed():
    text = _source_text()

    assert "class QuickStartDialog" not in text
    assert "on_quick_start" not in text
    assert "QuickStartDialog" not in text


def test_main_keeps_settings_entry_and_missing_file_hint():
    text = _source_text()

    assert re.search(r"settings_btn.clicked.connect", text)
    assert "main.fileNotFound" in text


def test_main_enforces_canonical_inventory_filename():
    text = _source_text()

    assert 'INVENTORY_FILE_NAME = "ln2_inventory.yaml"' in text
    assert "def _normalize_inventory_yaml_path(" in text
    assert "force_canonical_file=False" in text


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
    text = _source_text()

    assert "APP_VERSION = " in text
    assert re.search(r'APP_VERSION\s*=\s*"[\d.]+"', text)
    assert re.search(r'v\{APP_VERSION\}', text)
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
    text = _source_text()

    assert "def _show_nonblocking_dialog(" in text
    assert "dialog.setWindowModality(Qt.NonModal)" in text
    assert "dialog.show()" in text
    assert 'msg_box.addButton(tr("main.importStartupAction"), QMessageBox.ActionRole)' in text
    assert 'msg_box.addButton(tr("main.importPromptNewInventory"), QMessageBox.ActionRole)' in text
    assert "QMessageBox.Close" in text
    assert '.lstrip("1.0.1")' not in text
    assert '.lstrip("vV")' in text
