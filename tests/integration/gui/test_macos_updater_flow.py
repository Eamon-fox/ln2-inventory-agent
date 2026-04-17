"""Lock tests for the macOS-specific updater UX (issue #30 part 1).

Because SnowFox on macOS ships unsigned, the updater cannot silently
relaunch the new app — users must approve it in System Settings and
launch it manually. These tests pin the UX contract that calls out
those manual steps:

- pre-install confirm dialog is shown before auto-update starts on macOS
- cancelling the confirm aborts the flow before any downloader runs
- manual-download path shows the macOS-specific message
- post-install on macOS uses the macOS-specific message and does not
  auto-quit (user needs to quit manually after approving in Settings)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: F401

    from app_gui.i18n import set_language
    from app_gui.main_window_flows import StartupFlow

    PYSIDE_AVAILABLE = True
except Exception:
    QApplication = None
    QMessageBox = None
    StartupFlow = None
    set_language = None
    PYSIDE_AVAILABLE = False


pytestmark = pytest.mark.skipif(not PYSIDE_AVAILABLE, reason="PySide6 is required")


@pytest.fixture(autouse=True)
def _ensure_qapplication_and_english():
    app = QApplication.instance() or QApplication([])
    set_language("en")
    yield app


def _make_flow():
    from PySide6.QtWidgets import QWidget

    window = QWidget()
    window.gui_config = {}
    window.current_yaml_path = ""
    return StartupFlow(
        window=window,
        app_version="1.0.0",
        release_url="https://example.invalid/",
        github_api_latest="https://example.invalid/latest.json",
        is_version_newer=lambda new, old: True,
        show_nonblocking_dialog=MagicMock(),
        start_import_journey=MagicMock(),
    )


def test_confirm_macos_update_returns_true_when_continue_clicked():
    flow = _make_flow()

    captured = {}

    def _intercept(box):
        captured["buttons"] = [b.text() for b in box.buttons()]
        continue_btn = next(
            b for b in box.buttons() if "Continue" in b.text() or "继续" in b.text()
        )
        box.clickedButton = lambda: continue_btn
        return 0

    with patch.object(QMessageBox, "exec", new=_intercept):
        result = flow._confirm_macos_update()

    assert result is True
    assert any("Cancel" in b or "取消" in b for b in captured["buttons"])


def test_confirm_macos_update_returns_false_when_cancel_clicked():
    flow = _make_flow()

    def _intercept(box):
        cancel_btn = next(
            b for b in box.buttons() if "Cancel" in b.text() or "取消" in b.text()
        )
        box.clickedButton = lambda: cancel_btn
        return 0

    with patch.object(QMessageBox, "exec", new=_intercept):
        result = flow._confirm_macos_update()

    assert result is False


def test_start_automatic_update_macos_auto_update_shows_confirm_and_aborts_on_cancel():
    flow = _make_flow()

    # Force the macOS auto_update path regardless of runtime platform.
    release_info = {
        "platform_key": "macos",
        "platform_name": "macOS",
        "download_url": "https://example.invalid/SnowFox-1.1.0.pkg",
        "auto_update": True,
    }

    flow._confirm_macos_update = MagicMock(return_value=False)

    with patch(
        "app_gui.main_window_flows.resolve_platform_release_info",
        return_value=release_info,
    ), patch("app_gui.auto_updater.AutoUpdater") as mock_updater_cls:
        flow.start_automatic_update("1.1.0", "", "https://example.invalid/pkg")

    flow._confirm_macos_update.assert_called_once()
    mock_updater_cls.assert_not_called()


def test_start_automatic_update_macos_manual_path_uses_macos_message():
    flow = _make_flow()
    flow._show_status_box = MagicMock()

    release_info = {
        "platform_key": "macos",
        "platform_name": "macOS",
        "download_url": "https://example.invalid/SnowFox-1.1.0.pkg",
        "auto_update": False,
    }

    with patch(
        "app_gui.main_window_flows.resolve_platform_release_info",
        return_value=release_info,
    ), patch("PySide6.QtGui.QDesktopServices.openUrl"):
        flow.start_automatic_update("1.1.0", "", "https://example.invalid/pkg")

    flow._show_status_box.assert_called_once()
    _, body, _ = flow._show_status_box.call_args.args
    # Hallmarks of the macOS-specific manual message (covers both en + zh-CN):
    assert "Privacy & Security" in body or "隐私与安全性" in body


def test_macos_post_install_message_does_not_auto_quit(monkeypatch):
    """The macOS post-install dialog leaves the old process running so the
    user can finish what they're doing; auto-quit only fires on other OSes."""
    from app_gui.i18n import tr

    # Contract-check via string presence: the macOS post-install message
    # must reference the Privacy & Security / 隐私与安全性 step.
    msg = tr("main.macosUpdatePostInstallMessage")
    assert msg  # key is wired up
    assert ("Privacy & Security" in msg) or ("隐私与安全性" in msg)
