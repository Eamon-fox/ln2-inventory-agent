"""
Module: test_render_release_artifacts
Layer: unit
Covers: scripts/render_release_artifacts.py
"""

import importlib.util
import sys
import unittest
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "render_release_artifacts.py"

spec = importlib.util.spec_from_file_location("render_release_artifacts", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("render_release_artifacts", module)
spec.loader.exec_module(module)


class TestRenderReleaseArtifacts(unittest.TestCase):
    def test_collect_download_entries_prefers_platform_table(self):
        payload = {
            "download_url": "https://example.com/SnowFox-Setup-1.3.5.exe",
            "platforms": {
                "windows": {
                    "download_url": "https://example.com/SnowFox-Setup-1.3.5.exe",
                },
                "macos": {
                    "download_url": "https://example.com/SnowFox-1.3.5-macOS.pkg",
                },
            },
        }

        self.assertEqual(
            module.collect_download_entries(payload),
            [
                ("Windows", "https://example.com/SnowFox-Setup-1.3.5.exe"),
                ("macOS", "https://example.com/SnowFox-1.3.5-macOS.pkg"),
            ],
        )

    def test_build_github_release_lists_both_platform_downloads(self):
        sections = OrderedDict(
            [
                ("Added", ["A"]),
                ("Fixed", ["B"]),
            ]
        )

        content = module.build_github_release(
            "1.3.5",
            "2026-03-21",
            [
                ("Windows", "https://example.com/SnowFox-Setup-1.3.5.exe"),
                ("macOS", "https://example.com/SnowFox-1.3.5-macOS.pkg"),
            ],
            sections,
        )

        self.assertIn("- Windows 安装包：`https://example.com/SnowFox-Setup-1.3.5.exe`", content)
        self.assertIn("- macOS 安装包：`https://example.com/SnowFox-1.3.5-macOS.pkg`", content)
        self.assertIn("### 新增", content)
        self.assertIn("### 修复", content)


if __name__ == "__main__":
    unittest.main()
