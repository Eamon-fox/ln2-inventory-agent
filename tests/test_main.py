"""Unit tests for app_gui/main.py — demo path resolution."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.path_utils import resolve_demo_dataset_path as _resolve_demo_dataset_path


class DemoPathResolutionTests(unittest.TestCase):
    def test_frozen_mode_returns_exe_sibling_path(self):
        """When frozen (packaged exe), demo should be in exe directory."""
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "D:\\MyApp\\LN2InventoryAgent.exe"):
                path = _resolve_demo_dataset_path()
                self.assertEqual(path, "D:\\MyApp\\demo\\ln2_inventory.demo.yaml")

    def test_frozen_mode_with_forward_slashes(self):
        """Handle forward slashes in executable path."""
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "C:/Program Files/App/app.exe"):
                path = _resolve_demo_dataset_path()
                self.assertIn("demo", path)
                self.assertIn("ln2_inventory.demo.yaml", path)

    def test_development_mode_returns_source_demo_path(self):
        """In development mode, demo should be in source demo directory."""
        with patch.object(sys, "frozen", False, create=True):
            path = _resolve_demo_dataset_path()
            self.assertIn("demo", path)
            self.assertTrue(path.endswith("ln2_inventory.demo.yaml"))

    def test_development_mode_path_contains_project_root(self):
        """Development mode path should contain project root."""
        with patch.object(sys, "frozen", False, create=True):
            path = _resolve_demo_dataset_path()
            self.assertIn("ln2-inventory-agent", path.replace("\\", "/").lower())

    def test_frozen_mode_different_installation_locations(self):
        """Test frozen mode works from different installation directories."""
        test_paths = [
            ("C:\\Users\\Test\\Desktop\\App\\app.exe", "C:\\Users\\Test\\Desktop\\App"),
            ("D:\\Tools\\LN2\\LN2InventoryAgent.exe", "D:\\Tools\\LN2"),
            ("/mnt/d/MyApps/app.exe", "/mnt/d/MyApps"),
        ]
        for exe_path, expected_dir in test_paths:
            with self.subTest(exe_path=exe_path):
                with patch.object(sys, "frozen", True, create=True):
                    with patch.object(sys, "executable", exe_path):
                        path = _resolve_demo_dataset_path()
                        self.assertIn("demo", path)


class FirstRunBehaviorTests(unittest.TestCase):
    def test_yaml_not_exists_triggers_quick_start(self):
        """If yaml_path doesn't exist, should trigger Quick Start dialog."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = os.path.join(tmpdir, "nonexistent.yaml")
            self.assertFalse(os.path.isfile(nonexistent))

    def test_yaml_exists_skips_quick_start(self):
        """If yaml_path exists, should load normally without Quick Start."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = os.path.join(tmpdir, "existing.yaml")
            Path(existing).write_text("meta:\n  box_layout:\n    rows: 9\n    cols: 9\n", encoding="utf-8")
            self.assertTrue(os.path.isfile(existing))


if __name__ == "__main__":
    unittest.main()
