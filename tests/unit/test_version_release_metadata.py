"""
Module: test_version_release_metadata
Layer: unit
Covers: app_gui/version.py
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.version import current_release_platform, resolve_platform_release_info  # noqa: E402


class TestReleaseMetadata(unittest.TestCase):
    def test_current_release_platform_normalizes_supported_systems(self):
        self.assertEqual(current_release_platform("win32"), "windows")
        self.assertEqual(current_release_platform("darwin"), "macos")

    def test_current_release_platform_falls_back_to_windows_for_unknown_system(self):
        self.assertEqual(current_release_platform("linux"), "windows")

    def test_resolve_platform_release_info_prefers_platform_specific_url(self):
        payload = {
            "download_url": "https://example.com/SnowFox-Setup-1.3.5.exe",
            "platforms": {
                "windows": {
                    "download_url": "https://example.com/SnowFox-Setup-1.3.5.exe",
                    "auto_update": True,
                },
                "macos": {
                    "download_url": "https://example.com/SnowFox-1.3.5-macOS.pkg",
                    "auto_update": True,
                },
            },
        }

        result = resolve_platform_release_info(payload, system_platform="darwin")

        self.assertEqual(result["platform_key"], "macos")
        self.assertEqual(result["platform_name"], "macOS")
        self.assertEqual(
            result["download_url"],
            "https://example.com/SnowFox-1.3.5-macOS.pkg",
        )
        self.assertTrue(result["auto_update"])

    def test_resolve_platform_release_info_falls_back_to_legacy_download_url(self):
        payload = {
            "download_url": "https://example.com/SnowFox-Setup-1.3.5.exe",
        }

        result = resolve_platform_release_info(payload, system_platform="darwin")

        self.assertEqual(
            result["download_url"],
            "https://example.com/SnowFox-Setup-1.3.5.exe",
        )
        self.assertFalse(result["auto_update"])


if __name__ == "__main__":
    unittest.main()
