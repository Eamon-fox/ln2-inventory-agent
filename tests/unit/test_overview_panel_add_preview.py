"""
Module: test_overview_panel_add_preview
Layer: unit
Covers: app_gui/ui/overview_panel_grid.py::_build_operation_marker_map

Pending add ops should attach a display_key preview label to the marker so
the live overview grid can show the staged value in place of the position
number (issue #31).
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.ui.overview_panel_grid import _build_operation_marker_map


def _add_item(box, position, positions, fields):
    return {
        "action": "add",
        "box": box,
        "position": position,
        "payload": {"positions": list(positions), "fields": dict(fields)},
    }


class BuildOperationMarkerMapPreviewTests(unittest.TestCase):
    def test_add_marker_carries_preview_label_for_display_key(self):
        items = [_add_item(1, 1, [1, 2], {"short_name": "clone-A"})]
        markers = _build_operation_marker_map(items, display_key="short_name")
        self.assertEqual("clone-A", markers[(1, 1)].get("preview_label"))
        self.assertEqual("clone-A", markers[(1, 2)].get("preview_label"))

    def test_add_marker_has_no_preview_without_display_key(self):
        items = [_add_item(1, 1, [1], {"short_name": "clone-A"})]
        markers = _build_operation_marker_map(items, display_key=None)
        self.assertEqual({"type": "add"}, markers[(1, 1)])

    def test_add_marker_has_no_preview_when_field_missing(self):
        items = [_add_item(1, 1, [1], {"parent_cell_line": "K562"})]
        markers = _build_operation_marker_map(items, display_key="short_name")
        self.assertEqual({"type": "add"}, markers[(1, 1)])

    def test_add_marker_has_no_preview_when_field_is_blank(self):
        items = [_add_item(1, 1, [1], {"short_name": "   "})]
        markers = _build_operation_marker_map(items, display_key="short_name")
        self.assertEqual({"type": "add"}, markers[(1, 1)])

    def test_takeout_marker_ignores_display_key(self):
        items = [{"action": "takeout", "box": 1, "position": 3, "payload": {}}]
        markers = _build_operation_marker_map(items, display_key="short_name")
        self.assertEqual({"type": "takeout"}, markers[(1, 3)])


if __name__ == "__main__":
    unittest.main()
