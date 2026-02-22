"""Overview box tag rendering tests."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
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

    def test_rebuild_boxes_title_includes_box_tag(self):
        panel = self._new_panel()
        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": "virus stock"}}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        self.assertIn("virus stock", panel.overview_box_groups[1].title())

    def test_update_box_titles_reflects_latest_layout_tags(self):
        panel = self._new_panel()
        panel._current_layout = {"rows": 1, "cols": 1}
        panel._rebuild_boxes(rows=1, cols=1, box_numbers=[1])
        self.assertNotIn("freezer-b2", panel.overview_box_groups[1].title())

        panel._current_layout = {"rows": 1, "cols": 1, "box_tags": {"1": "freezer-b2"}}
        panel._update_box_titles([1])
        self.assertIn("freezer-b2", panel.overview_box_groups[1].title())


if __name__ == "__main__":
    unittest.main()
