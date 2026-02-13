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
