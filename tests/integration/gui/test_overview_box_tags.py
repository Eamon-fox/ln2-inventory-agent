"""
Module: test_overview_box_tags
Layer: integration/gui
Covers: app_gui/ui/overview_panel.py

概览网格 box 标签显示与更新测试
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication

    from app_gui.ui.overview_panel import OverviewPanel

    PYSIDE_AVAILABLE = True
except Exception:
    QApplication = None
    OverviewPanel = None
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is required")
class OverviewBoxTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _new_panel(self):
        bridge = SimpleNamespace(
            set_box_tag=lambda **_kwargs: {"ok": True},
            generate_stats=lambda *_args, **_kwargs: {"ok": False},
        )
        return OverviewPanel(bridge=bridge, yaml_path_getter=lambda: "/tmp/inventory.yaml")

    def test_rebuild_boxes_title_includes_short_box_tag(self):
        panel = self._new_panel()
        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": "virus stock"}}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        group = panel.overview_box_groups[1]
        self.assertIn("virus stock", group.title())
        self.assertIn("virus stock", group.toolTip())

    def test_rebuild_boxes_title_truncates_long_box_tag(self):
        panel = self._new_panel()
        long_tag = "freezer-room-row-02-slot-alpha"
        expected_tag = f"{long_tag[:18]}..."
        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": long_tag}}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        group = panel.overview_box_groups[1]

        self.assertIn(expected_tag, group.title())
        self.assertNotIn(long_tag, group.title())
        self.assertIn(long_tag, group.toolTip())

    def test_update_box_titles_reflects_latest_layout_tags(self):
        panel = self._new_panel()
        panel._current_layout = {"rows": 1, "cols": 1}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        self.assertNotIn("freezer-b2", panel.overview_box_groups[1].title())

        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": "freezer-b2"}}
        panel._update_box_titles([1])
        group = panel.overview_box_groups[1]
        self.assertIn("freezer-b2", group.title())
        self.assertIn("freezer-b2", group.toolTip())

    def test_update_box_titles_keeps_full_tag_in_tooltip_with_truncated_title(self):
        panel = self._new_panel()
        panel._current_layout = {"rows": 1, "cols": 1}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        long_tag = "very-long-storage-tag-for-box-one"
        expected_tag = f"{long_tag[:18]}..."

        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": long_tag}}
        panel._update_box_titles([1])
        group = panel.overview_box_groups[1]

        self.assertIn(expected_tag, group.title())
        self.assertNotIn(long_tag, group.title())
        self.assertIn(long_tag, group.toolTip())


if __name__ == "__main__":
    unittest.main()
