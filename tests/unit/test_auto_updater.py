"""
Module: test_auto_updater
Layer: unit
Covers: app_gui/auto_updater.py

Tests for the update batch-script generation logic.
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.auto_updater import AutoUpdater  # noqa: E402


class TestInstallAndRestart(unittest.TestCase):
    """Verify that install_and_restart creates a correct update script."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_updater_")
        self.installer_path = os.path.join(self.temp_dir, "SnowFox-Setup-1.3.0.exe")
        with open(self.installer_path, "wb") as f:
            f.write(b"fake")

        self.progress_calls = []
        self.complete_calls = []
        self.error_calls = []

        self.updater = AutoUpdater(
            latest_tag="1.3.0",
            release_notes="test notes",
            download_url="https://example.com/SnowFox-Setup-1.3.0.exe",
            on_progress=lambda p, m: self.progress_calls.append((p, m)),
            on_complete=lambda s, m: self.complete_calls.append((s, m)),
            on_error=lambda e: self.error_calls.append(e),
        )
        self.updater.temp_dir = self.temp_dir
        self.platform_patcher = patch("app_gui.auto_updater.sys.platform", "win32")
        self.platform_patcher.start()

    def tearDown(self):
        if self.platform_patcher is not None:
            self.platform_patcher.stop()
        if self.updater.temp_dir and os.path.exists(self.updater.temp_dir):
            shutil.rmtree(self.updater.temp_dir)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("subprocess.Popen")
    def test_creates_bat_script(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")
        self.assertTrue(os.path.isfile(script_path))

    @patch("subprocess.Popen")
    def test_bat_contains_pid_wait_loop(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")
        content = open(script_path, encoding="utf-8").read()

        current_pid = str(os.getpid())
        self.assertIn(current_pid, content)
        self.assertIn(":wait", content)
        self.assertIn("tasklist", content)
        self.assertIn("goto wait", content)

    @patch("subprocess.Popen")
    def test_bat_contains_installer_command(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")
        content = open(script_path, encoding="utf-8").read()

        self.assertIn(self.installer_path, content)
        self.assertIn("/SILENT", content)
        self.assertIn("/UPDATE", content)
        self.assertIn("/NORESTART", content)

    @patch("subprocess.Popen")
    def test_bat_launches_new_exe(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")
        content = open(script_path, encoding="utf-8").read()

        self.assertIn("SnowFox-1.3.0.exe", content)
        self.assertIn("start", content)

    @patch("subprocess.Popen")
    def test_bat_cleans_up_temp_dir(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")
        content = open(script_path, encoding="utf-8").read()

        self.assertIn("rmdir /s /q", content)
        self.assertIn(self.temp_dir, content)

    @patch("subprocess.Popen")
    def test_popen_called_detached(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args
        flags = call_kwargs.kwargs.get("creationflags", 0)
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        self.assertTrue(flags & CREATE_NO_WINDOW)
        self.assertTrue(flags & CREATE_NEW_PROCESS_GROUP)

    @patch("subprocess.Popen")
    def test_on_complete_called_with_success(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        self.assertEqual(len(self.complete_calls), 1)
        self.assertTrue(self.complete_calls[0][0])

    @patch("subprocess.Popen")
    def test_temp_dir_set_to_none(self, mock_popen):
        """After success, temp_dir is None so cleanup() won't delete it."""
        self.updater.install_and_restart(self.installer_path)

        self.assertIsNone(self.updater.temp_dir)

    @patch("subprocess.Popen")
    def test_no_error_on_success(self, mock_popen):
        self.updater.install_and_restart(self.installer_path)

        self.assertEqual(len(self.error_calls), 0)

    def test_install_and_restart_rejects_non_windows_platforms(self):
        self.platform_patcher.stop()
        self.platform_patcher = None
        with patch("app_gui.auto_updater.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "only supported on Windows"):
                self.updater.install_and_restart(self.installer_path)

        self.assertTrue(self.error_calls)
        self.assertIn("only supported on Windows", self.error_calls[-1])

    @patch("subprocess.Popen")
    def test_macos_install_and_restart_creates_shell_script(self, mock_popen):
        self.platform_patcher.stop()
        self.platform_patcher = None

        pkg_path = os.path.join(self.temp_dir, "SnowFox-1.3.0-macOS.pkg")
        with open(pkg_path, "wb") as f:
            f.write(b"fake-pkg")

        with patch("app_gui.auto_updater.sys.platform", "darwin"):
            self.updater.install_and_restart(pkg_path)

        script_path = os.path.join(self.temp_dir, "snowfox_update.sh")
        self.assertTrue(os.path.isfile(script_path))
        content = open(script_path, encoding="utf-8").read()
        self.assertIn("open ", content)
        self.assertIn(pkg_path, content)
        # Unsigned macOS builds trip Gatekeeper on first launch, so the
        # script must NOT attempt to auto-relaunch the app. The caller
        # surfaces a dialog telling the user to approve and launch it
        # manually. See docs/modules/11-界面应用层.md "macOS 更新 UX 契约".
        self.assertNotIn("/Applications/SnowFox.app", content)
        self.assertEqual(len(self.complete_calls), 1)
        self.assertIn("Installer", self.complete_calls[0][1])

        mock_popen.assert_called_once()
        kwargs = mock_popen.call_args.kwargs
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertNotIn("creationflags", kwargs)


if __name__ == "__main__":
    unittest.main()
