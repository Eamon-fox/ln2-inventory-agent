"""Automatic update downloader and installer for SnowFox."""

import os
import shlex
import sys
import urllib.request
import urllib.error
import tempfile
import subprocess
import shutil
from urllib.parse import unquote, urlparse


class AutoUpdater:
    """Handle automatic downloading and installation of updates."""

    def __init__(self, latest_tag, release_notes, download_url="",
                 on_progress=None, on_complete=None, on_error=None):
        self.latest_tag = latest_tag
        self.release_notes = release_notes
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.download_url = download_url
        self.temp_dir = None

    @staticmethod
    def _platform_key():
        if sys.platform.startswith("win"):
            return "windows"
        if sys.platform == "darwin":
            return "macos"
        raise RuntimeError("Automatic installation is only supported on Windows and macOS.")

    def _download_filename(self):
        parsed = urlparse(str(self.download_url or ""))
        candidate = os.path.basename(unquote(parsed.path))
        if candidate:
            return candidate
        if self._platform_key() == "windows":
            return f"SnowFox-Setup-{self.latest_tag}.exe"
        return f"SnowFox-{self.latest_tag}-macOS.pkg"

    def download_installer(self):
        """Download the installer to a temporary directory."""
        try:
            self._platform_key()
            if not self.download_url:
                raise Exception("No download URL provided")

            self.temp_dir = tempfile.mkdtemp(prefix="snowfox_update_")
            installer_path = os.path.join(self.temp_dir, self._download_filename())

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
        """Create an update script and signal ready to exit.

        A batch script is spawned as a detached process that:
        1. Waits for the current app process to exit (file locks released)
        2. Runs the Inno Setup installer silently
        3. Launches the newly installed executable
        4. Cleans up the temporary download directory
        The caller (main_window_flows) is responsible for quitting the app.
        """
        try:
            platform_key = self._platform_key()
            if platform_key == "windows":
                self._install_and_restart_windows(installer_path)
                return
            if platform_key == "macos":
                self._install_and_restart_macos(installer_path)
                return
            raise RuntimeError("Automatic installation is only supported on Windows and macOS.")

        except Exception as e:
            if self.on_error:
                self.on_error(f"Installation failed: {str(e)}")
            raise

    def _install_and_restart_windows(self, installer_path):
        if self.on_progress:
            self.on_progress(100, "Preparing update...")

        current_pid = os.getpid()

        if getattr(sys, 'frozen', False):
            install_dir = os.path.dirname(sys.executable)
        else:
            install_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

        new_exe = f"SnowFox-{self.latest_tag}.exe"
        script_path = os.path.join(self.temp_dir, "snowfox_update.bat")

        script_content = (
            '@echo off\r\n'
            ':wait\r\n'
            f'tasklist /FI "PID eq {current_pid}" 2>NUL | find /I "{current_pid}" >NUL\r\n'
            'if "%ERRORLEVEL%"=="0" (\r\n'
            '    timeout /t 1 /nobreak >nul\r\n'
            '    goto wait\r\n'
            ')\r\n'
            'timeout /t 1 /nobreak >nul\r\n'
            f'"{installer_path}" /SILENT /UPDATE /NORESTART /DIR="{install_dir}"\r\n'
            f'if exist "{os.path.join(install_dir, new_exe)}" (\r\n'
            f'    start "" "{os.path.join(install_dir, new_exe)}"\r\n'
            ')\r\n'
            'timeout /t 2 /nobreak >nul\r\n'
            f'cd /d "%TEMP%"\r\n'
            f'rmdir /s /q "{self.temp_dir}" 2>nul\r\n'
        )

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            ['cmd', '/c', script_path],
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.temp_dir = None

        if self.on_complete:
            self.on_complete(True, "Update ready. Application will restart.")

    def _install_and_restart_macos(self, installer_path):
        if self.on_progress:
            self.on_progress(100, "Preparing macOS installer...")

        current_pid = os.getpid()
        script_path = os.path.join(self.temp_dir, "snowfox_update.sh")
        app_path = "/Applications/SnowFox.app"

        installer_quoted = shlex.quote(installer_path)
        app_quoted = shlex.quote(app_path)
        temp_dir_quoted = shlex.quote(str(self.temp_dir))
        script_content = (
            "#!/bin/bash\n"
            "set -e\n"
            f"while kill -0 {current_pid} 2>/dev/null; do\n"
            "  sleep 1\n"
            "done\n"
            "sleep 1\n"
            f"open -W {installer_quoted}\n"
            f"if [ -d {app_quoted} ]; then\n"
            f"  open -a {app_quoted}\n"
            "fi\n"
            f"rm -rf {temp_dir_quoted}\n"
        )

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(script_path, 0o755)

        subprocess.Popen(
            ["/bin/bash", script_path],
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.temp_dir = None

        if self.on_complete:
            self.on_complete(
                True,
                "Installer is ready. SnowFox will quit and open the macOS installer.",
            )

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
