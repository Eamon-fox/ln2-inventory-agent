"""
Module: test_main_ui_scale_policy
Layer: integration/gui
Covers: app_gui/main.py

UI 缩放策略与 4K 显示器检测测试
"""

import pytest

from app_gui.application.ui_scale_env import build_qt_scale_environment


try:
    import app_gui.main as main_module

    _MAIN_AVAILABLE = True
except Exception:
    main_module = None
    _MAIN_AVAILABLE = False


pytestmark = pytest.mark.skipif(not _MAIN_AVAILABLE, reason="main module dependencies unavailable")


def test_resolve_startup_ui_scale_keeps_existing_user_config(monkeypatch):
    monkeypatch.setattr(main_module, "_is_primary_screen_4k_windows", lambda: True)
    resolved = main_module._resolve_startup_ui_scale(config_exists=True, configured_scale=1.5)
    assert resolved == 1.5


def test_resolve_startup_ui_scale_first_run_4k_defaults_to_125(monkeypatch):
    monkeypatch.setattr(main_module, "_is_primary_screen_4k_windows", lambda: True)
    resolved = main_module._resolve_startup_ui_scale(config_exists=False, configured_scale=1.0)
    assert resolved == 1.25


def test_resolve_startup_ui_scale_first_run_non_4k_keeps_default(monkeypatch):
    monkeypatch.setattr(main_module, "_is_primary_screen_4k_windows", lambda: False)
    resolved = main_module._resolve_startup_ui_scale(config_exists=False, configured_scale=1.0)
    assert resolved == 1.0


def test_resolve_startup_ui_scale_handles_invalid_scale(monkeypatch):
    monkeypatch.setattr(main_module, "_is_primary_screen_4k_windows", lambda: False)
    resolved = main_module._resolve_startup_ui_scale(config_exists=False, configured_scale="invalid")
    assert resolved == 1.0


def test_qt_scale_environment_clears_inherited_scale_for_100_percent():
    env = build_qt_scale_environment(
        1.0,
        base_env={
            "QT_SCALE_FACTOR": "1.5",
            "QT_ENABLE_HIGHDPI_SCALING": "1",
            "QT_SCALE_FACTOR_ROUNDING_POLICY": "PassThrough",
            "OTHER_SETTING": "keep",
        },
    )

    assert "QT_SCALE_FACTOR" not in env
    assert "QT_ENABLE_HIGHDPI_SCALING" not in env
    assert "QT_SCALE_FACTOR_ROUNDING_POLICY" not in env
    assert env["OTHER_SETTING"] == "keep"


def test_qt_scale_environment_sets_requested_scale():
    env = build_qt_scale_environment(1.25, base_env={"OTHER_SETTING": "keep"})

    assert env["QT_SCALE_FACTOR"] == "1.25"
    assert env["QT_ENABLE_HIGHDPI_SCALING"] == "1"
    assert env["QT_SCALE_FACTOR_ROUNDING_POLICY"] == "PassThrough"
    assert env["OTHER_SETTING"] == "keep"
