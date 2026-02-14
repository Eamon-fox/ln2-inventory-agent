"""Missing unit tests for app_gui/ layer modules.

Tests for:
- plan_model.py: validation and rendering
- workers.py: AgentRunWorker execution
- ui/utils.py: utility functions
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Try to import Qt components, skip if not available
try:
    from PySide6.QtCore import QObject, Signal
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

from app_gui.plan_model import validate_plan_item, render_operation_sheet


# ── plan_model.py Tests ───────────────────────────────────────


class PlanModelValidationTests(unittest.TestCase):
    """Test plan item validation."""

    def test_validate_plan_item_add_with_all_fields(self):
        """Test add operation with all required fields."""
        item = {
            "action": "add",
            "box": 1,
            "position": 5,
            "record_id": None,
            "label": "test-clone",
            "parent_cell_line": "K562",
            "short_name": "clone-new",
            "frozen_at": "2026-02-10",
        }
        error = validate_plan_item(item)
        self.assertIsNone(error)

    def test_validate_plan_item_add_missing_fields(self):
        """Test add operation passes plan validation (required checks at execution time)."""
        # Plan validation no longer checks required user fields — that happens at execution
        item = {
            "action": "add",
            "box": 1,
            "position": 5,
            "record_id": None,
            "label": "test-clone",
        }
        error = validate_plan_item(item)
        self.assertIsNone(error)

    def test_validate_plan_item_move_missing_to_position(self):
        """Test move operation missing to_position."""
        item = {
            "action": "move",
            "box": 1,
            "position": 5,
            "record_id": 1,
            "label": "test-clone",
        }
        error = validate_plan_item(item)
        self.assertIsNotNone(error)
        self.assertIn("to_position", error)

    def test_validate_plan_item_move_valid(self):
        """Test valid move operation."""
        item = {
            "action": "move",
            "box": 1,
            "position": 5,
            "to_position": 10,
            "record_id": 1,
            "label": "test-clone",
        }
        error = validate_plan_item(item)
        self.assertIsNone(error)

    def test_validate_plan_item_takeout_valid(self):
        """Test valid takeout operation."""
        item = {
            "action": "takeout",
            "box": 1,
            "position": 5,
            "record_id": 1,
            "label": "test-clone",
        }
        error = validate_plan_item(item)
        self.assertIsNone(error)

    def test_validate_plan_item_invalid_box(self):
        """Test invalid box number."""
        item = {
            "action": "add",
            "box": 99,
            "position": 5,
            "record_id": None,
            "label": "test-clone",
            "parent_cell_line": "K562",
            "short_name": "clone-new",
            "frozen_at": "2026-02-10",
        }
        error = validate_plan_item(item)
        self.assertIsNotNone(error)

    def test_validate_plan_item_invalid_position(self):
        """Test invalid position number."""
        item = {
            "action": "add",
            "box": 1,
            "position": 999,
            "record_id": None,
            "label": "test-clone",
            "parent_cell_line": "K562",
            "short_name": "clone-new",
            "frozen_at": "2026-02-10",
        }
        error = validate_plan_item(item)
        self.assertIsNotNone(error)

    def test_validate_plan_item_invalid_action(self):
        """Test invalid action type."""
        item = {
            "action": "invalid_action",
            "box": 1,
            "position": 5,
            "record_id": None,
            "label": "test-clone",
        }
        error = validate_plan_item(item)
        self.assertIsNotNone(error)


class PlanModelRenderingTests(unittest.TestCase):
    """Test plan sheet rendering."""

    def test_render_operation_sheet_basic(self):
        """Test basic operation sheet rendering."""
        items = [
            {
                "action": "takeout",
                "box": 1,
                "position": 5,
                "record_id": 1,
                "label": "K562-clone1",
                "parent_cell_line": "K562",
                "short_name": "clone1",
            },
        ]
        html = render_operation_sheet(items)
        self.assertIsInstance(html, str)
        self.assertIn("<html", html)
        self.assertIn("K562", html)
        self.assertIn("clone1", html)

    def test_render_operation_sheet_multiple_actions(self):
        """Test rendering multiple different actions."""
        items = [
            {"action": "takeout", "box": 1, "position": 5, "record_id": 1, "label": "rec1"},
            {"action": "move", "box": 1, "position": 10, "to_position": 20, "record_id": 2, "label": "rec2"},
            {"action": "thaw", "box": 2, "position": 3, "record_id": 3, "label": "rec3"},
        ]
        html = render_operation_sheet(items)
        self.assertIn("Takeout", html)
        self.assertIn("Move", html)
        self.assertIn("Thaw", html)

    def test_render_operation_sheet_empty_list(self):
        """Test rendering with empty items list."""
        html = render_operation_sheet([])
        self.assertIsInstance(html, str)
        # Should still produce valid HTML
        self.assertIn("<html", html)


# ── workers.py Tests ──────────────────────────────────────────


@unittest.skipIf(not QT_AVAILABLE, "PySide6 not available")
class WorkerTests(unittest.TestCase):
    """Test AgentRunWorker functionality."""

    def test_worker_basic_execution(self):
        """Test basic AgentRunWorker execution."""
        from app_gui.ui.workers import AgentRunWorker

        mock_bridge = Mock()
        mock_bridge.run_agent_query.return_value = {
            "ok": True,
            "final": "Test answer",
            "conversation_history": [],
        }

        worker = AgentRunWorker(
            bridge=mock_bridge,
            yaml_path="/tmp/test.yaml",
            query="test query",
            model="deepseek-chat",
            max_steps=8,
            history=None,
        )

        worker.run()

        mock_bridge.run_agent_query.assert_called_once()
        call_kwargs = mock_bridge.run_agent_query.call_args[1]
        self.assertEqual("test query", call_kwargs["query"])
        self.assertTrue(call_kwargs["thinking_enabled"])


# ── ui/utils.py Tests ───────────────────────────────────────────


class UiUtilsTests(unittest.TestCase):
    """Test ui/utils.py utility functions."""

    def test_positions_to_text_single(self):
        """Test positions_to_text with single position."""
        from app_gui.ui.utils import positions_to_text

        result = positions_to_text([5])
        self.assertEqual("5", result)

    def test_positions_to_text_multiple(self):
        """Test positions_to_text with multiple positions."""
        from app_gui.ui.utils import positions_to_text

        result = positions_to_text([1, 2, 3])
        self.assertEqual("1, 2, 3", result)

    def test_positions_to_text_empty(self):
        """Test positions_to_text with empty list."""
        from app_gui.ui.utils import positions_to_text

        result = positions_to_text([])
        self.assertEqual("", result)

    def test_positions_to_text_sorted(self):
        """Test positions_to_text sorts the positions."""
        from app_gui.ui.utils import positions_to_text

        result = positions_to_text([10, 5, 3, 8])
        self.assertEqual("3, 5, 8, 10", result)

    def test_positions_to_text_range(self):
        """Test positions_to_text handles consecutive positions."""
        from app_gui.ui.utils import positions_to_text

        result = positions_to_text([1, 2, 3])
        self.assertEqual("1, 2, 3", result)


# ===========================================================================
# Unit tests: build_color_palette / cell_color
# ===========================================================================

class TestColorPalette(unittest.TestCase):
    """Unit tests for build_color_palette() and cell_color()."""

    def test_build_palette_assigns_unique_colors(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette(["K562", "HeLa", "NCCIT"])
        self.assertEqual(3, len(_utils._dynamic_palette))
        # Each option gets a different color
        colors = list(_utils._dynamic_palette.values())
        self.assertEqual(len(set(colors)), len(colors))

    def test_build_palette_cycles_on_overflow(self):
        from app_gui.ui import utils as _utils
        # More options than colors in cycle
        options = [f"opt_{i}" for i in range(len(_utils._COLOR_CYCLE) + 3)]
        _utils.build_color_palette(options)
        self.assertEqual(len(options), len(_utils._dynamic_palette))
        # First and (first + cycle_len) should share the same color
        self.assertEqual(
            _utils._dynamic_palette["opt_0"],
            _utils._dynamic_palette[f"opt_{len(_utils._COLOR_CYCLE)}"],
        )

    def test_cell_color_uses_dynamic_palette(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette(["K562", "HeLa"])
        color = _utils.cell_color("K562")
        self.assertTrue(color.startswith("#"))
        # Known value should not be the fallback gray
        self.assertNotEqual("#7f8c8d", _utils.cell_color("K562"))

    def test_cell_color_unknown_value_returns_fallback(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette(["K562"])
        self.assertEqual("#7f8c8d", _utils.cell_color("UnknownLine"))

    def test_cell_color_empty_returns_gray(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette(["K562"])
        self.assertEqual("#7f8c8d", _utils.cell_color(""))
        self.assertEqual("#7f8c8d", _utils.cell_color(None))

    def test_cell_color_no_palette_uses_hash_fallback(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette([])  # empty palette
        color = _utils.cell_color("SomeValue")
        self.assertIn(color, _utils._COLOR_CYCLE)

    def test_build_palette_empty_list_clears(self):
        from app_gui.ui import utils as _utils
        _utils.build_color_palette(["K562"])
        self.assertEqual(1, len(_utils._dynamic_palette))
        _utils.build_color_palette([])
        self.assertEqual(0, len(_utils._dynamic_palette))


if __name__ == "__main__":
    unittest.main()
