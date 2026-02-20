"""Automatic update downloader and installer for SnowFox."""

import os
import sys
import urllib.request
import urllib.error
import json
import tempfile
import subprocess
import shutil
from pathlib import Path


class AutoUpdater:
    """Handle automatic downloading and installation of updates."""

    def __init__(self, latest_tag, release_notes, on_progress=None, on_complete=None, on_error=None):
        """
        Initialize auto updater.

        Args:
            latest_tag: Latest version tag (e.g., "1.2.0")
            release_notes: Release notes text
            on_progress: Callback(progress, message) for download progress
            on_complete: Callback(success, message) when download/install complete
            on_error: Callback(error_message) on error
        """
        self.latest_tag = latest_tag
        self.release_notes = release_notes
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.download_url = None
        self.temp_dir = None

    def find_installer_url(self):
        """Find the installer download URL from GitHub release assets."""
        try:
            api_url = "https://api.github.com/repos/Eamon-fox/snowfox/releases/latest"
            req = urllib.request.Request(
                api_url,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "SnowFox"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            assets = data.get("assets", [])
            installer_name = f"SnowFox-Setup-{self.latest_tag}.exe"

            # Look for the installer
            for asset in assets:
                if asset.get("name") == installer_name:
                    self.download_url = asset.get("browser_download_url")
                    return self.download_url

            # Fallback: try old naming convention
            installer_name_old = f"LN2InventoryAgent-Setup-{self.latest_tag}.exe"
            for asset in assets:
                if asset.get("name") == installer_name_old:
                    self.download_url = asset.get("browser_download_url")
                    return self.download_url

            # If not found, use the first .exe asset
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    self.download_url = asset.get("browser_download_url")
                    return self.download_url

            raise Exception(f"No installer found for version {self.latest_tag}")

        except Exception as e:
            if self.on_error:
                self.on_error(f"Failed to find installer: {str(e)}")
            raise

    def download_installer(self):
        """Download the installer to a temporary directory."""
        try:
            if not self.download_url:
                self.find_installer_url()

            # Create temp directory
            self.temp_dir = tempfile.mkdtemp(prefix="snowfox_update_")
            installer_path = os.path.join(self.temp_dir, f"SnowFox-Setup-{self.latest_tag}.exe")

            # Download with progress
            if self.on_progress:
                self.on_progress(0, "Connecting to download server...")

            request = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "SnowFox"},
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                total_size = int(response.getheader('Content-Length', 0))
                downloaded = 0
                chunk_size = 8192

                with open(installer_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if self.on_progress and total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            self.on_progress(
                                progress,
                                f"Downloading update... ({downloaded / 1024 / 1024:.1f} MB / {total_size / 1024 / 1024:.1f} MB)"
                            )

            if self.on_progress:
                self.on_progress(100, "Download complete")

            return installer_path

        except Exception as e:
            if self.on_error:
                self.on_error(f"Download failed: {str(e)}")
            raise

    def install_and_restart(self, installer_path):
        """Run the installer and restart the application."""
        try:
            if self.on_progress:
                self.on_progress(100, "Starting installer...")

            # Get the current executable path
            if getattr(sys, 'frozen', False):
                current_exe = sys.executable
            else:
                current_exe = os.path.abspath(sys.argv[0])

            # Run the installer silently with auto-upgrade
            # /SILENT - Silent installation
            # /DIR="path" - Installation directory
            # /NORESTART - Don't restart automatically
            # /UPDATE - Update existing installation
            installer_cmd = [
                installer_path,
                "/SILENT",
                "/UPDATE",
                "/NORESTART",
            ]

            # Try to install to the same directory as current installation
            if getattr(sys, 'frozen', False):
                install_dir = os.path.dirname(current_exe)
                installer_cmd.append(f'/DIR="{install_dir}"')

            # Start the installer as a separate process
            subprocess.Popen(
                installer_cmd,
                shell=True,
                close_fds=True
            )

            # Mark that we're updating
            if self.on_complete:
                self.on_complete(True, "Update installed. SnowFox will restart shortly.")

            # Exit the current application
            QTimer = __import__('PySide6.QtCore').QTimer
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()

            def _exit_app():
                app.quit()

            QTimer.singleShot(1000, _exit_app)

        except Exception as e:
            if self.on_error:
                self.on_error(f"Installation failed: {str(e)}")
            if self.on_complete:
                self.on_complete(False, str(e))
            raise

    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"[AutoUpdater] Cleanup failed: {e}")

    def start_update(self):
        """Start the full update process."""
        def _run():
            try:
                if self.on_progress:
                    self.on_progress(0, "Preparing update...")

                installer_path = self.download_installer()
                self.install_and_restart(installer_path)

            except Exception as e:
                print(f"[AutoUpdater] Update failed: {e}")
                self.cleanup()

        # Run in a separate thread to avoid blocking UI
        import threading
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
