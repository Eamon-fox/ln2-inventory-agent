"""Lock tests for the macOS-specific updater UX.

macOS distribution uses .pkg + Installer.app to /Applications. Because
Installer.app-installed payloads don't carry com.apple.quarantine,
auto-relaunch of /Applications/SnowFox.app is safe. These tests pin the
UX contract (see docs/modules/11-界面应用层.md "macOS 更新 UX 契约"):

- pre-install confirm dialog is shown before auto-update starts on macOS
- cancelling the confirm aborts the flow before any downloader runs
- manual-download path shows the macOS-specific message
- post-install on macOS uses the macOS-specific message and auto-quits
  the old process (installer handles relaunch)
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


def test_start_automatic_update_reports_default_source_before_downloader_starts():
    flow = _make_flow()

    release_info = {
        "platform_key": "windows",
        "platform_name": "Windows",
        "download_url": "https://oss.example.invalid/SnowFox-Setup-1.1.0.exe",
        "auto_update": True,
    }

    with patch(
        "app_gui.main_window_flows.resolve_platform_release_info",
        return_value=release_info,
    ), patch(
        "app_gui.main_window_flows.report_update_get"
    ) as mock_report, patch(
        "app_gui.auto_updater.AutoUpdater"
    ) as mock_updater_cls:
        mock_updater_cls.return_value.start_update = MagicMock(
            side_effect=lambda: mock_report.assert_called_once_with(
                "v1.1.0",
                "auto_update_start",
            )
        )

        flow.start_automatic_update(
            "v1.1.0",
            "notes",
            "https://oss.example.invalid/SnowFox-Setup-1.1.0.exe",
        )

    assert mock_updater_cls.call_args.kwargs["download_url"] == release_info["download_url"]


def test_start_automatic_update_reports_manual_source_when_requested():
    flow = _make_flow()

    release_info = {
        "platform_key": "windows",
        "platform_name": "Windows",
        "download_url": "https://oss.example.invalid/SnowFox-Setup-1.1.0.exe",
        "auto_update": True,
    }

    with patch(
        "app_gui.main_window_flows.resolve_platform_release_info",
        return_value=release_info,
    ), patch(
        "app_gui.main_window_flows.report_update_get"
    ) as mock_report, patch("app_gui.auto_updater.AutoUpdater") as mock_updater_cls:
        mock_updater_cls.return_value.start_update = MagicMock()
        flow.start_automatic_update(
            "1.1.0",
            "notes",
            "https://oss.example.invalid/SnowFox-Setup-1.1.0.exe",
            source="manual_update_start",
        )

    mock_report.assert_called_once_with("1.1.0", "manual_update_start")


def test_macos_post_install_message_promises_auto_quit_and_relaunch():
    """The macOS post-install message must tell the user the old window
    will close itself and the new version will launch automatically."""
    from app_gui.i18n import set_language, tr

    set_language("en")
    msg_en = tr("main.macosUpdatePostInstallMessage")
    assert msg_en
    assert "automatically" in msg_en.lower()

    set_language("zh-CN")
    msg_zh = tr("main.macosUpdatePostInstallMessage")
    assert msg_zh
    assert "自动" in msg_zh

    set_language("en")


def test_macos_post_install_auto_quits():
    """On macOS auto-update success, _on_complete must schedule app.quit()
    via QTimer.singleShot, mirroring the Windows branch. See the macOS
    update UX contract in docs/modules/11-界面应用层.md."""
    flow = _make_flow()
    flow._show_status_box = MagicMock()

    release_info = {
        "platform_key": "macos",
        "platform_name": "macOS",
        "download_url": "https://example.invalid/SnowFox-1.1.0.pkg",
        "auto_update": True,
    }

    flow._confirm_macos_update = MagicMock(return_value=True)

    with patch(
        "app_gui.main_window_flows.resolve_platform_release_info",
        return_value=release_info,
    ), patch("app_gui.auto_updater.AutoUpdater") as mock_updater_cls, patch(
        "app_gui.main_window_flows.QTimer"
    ) as mock_qtimer:
        mock_updater_cls.return_value.start_update = MagicMock()
        flow.start_automatic_update(
            "1.1.0", "notes", "https://example.invalid/pkg"
        )

        # AutoUpdater(...) was called with on_complete=<bridge.sig_complete.emit>.
        # Invoking it synchronously emits the signal, which triggers the
        # connected _on_complete slot under the current thread.
        on_complete_emit = mock_updater_cls.call_args.kwargs["on_complete"]
        on_complete_emit(True, "Installer opened.")

        QApplication.instance().processEvents()

        mock_qtimer.singleShot.assert_called_once()
        args, _ = mock_qtimer.singleShot.call_args
        assert args[0] == 300
