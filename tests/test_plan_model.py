"""Unit tests for app_gui/plan_model.py — validation edge cases, rendering."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.plan_model import render_operation_sheet, validate_plan_item


def _base_item(**overrides):
    """Construct a minimal valid PlanItem for takeout."""
    base = {
        "action": "takeout",
        "box": 1,
        "position": 1,
        "record_id": 1,
        "label": "test",
        "source": "human",
        "payload": {},
    }
    base.update(overrides)
    return base


def _add_item(**overrides):
    """Construct a minimal valid PlanItem for add."""
    base = {
        "action": "add",
        "box": 1,
        "position": 1,
        "label": "new-entry",
        "source": "human",
        "payload": {
            "parent_cell_line": "K562",
            "short_name": "clone-1",
        },
    }
    base.update(overrides)
    return base


def _move_item(**overrides):
    """Construct a minimal valid PlanItem for move."""
    base = {
        "action": "move",
        "box": 1,
        "position": 1,
        "to_position": 2,
        "record_id": 1,
        "label": "test",
        "source": "human",
        "payload": {},
    }
    base.update(overrides)
    return base


# ── validate_plan_item ──────────────────────────────────────────────


class ValidateActionTests(unittest.TestCase):
    def test_all_valid_actions(self):
        for action in ("takeout", "thaw", "discard", "move", "add"):
            item = _base_item(action=action)
            if action == "move":
                item["to_position"] = 2
            if action == "add":
                item.pop("record_id", None)
                item["payload"] = {"parent_cell_line": "A", "short_name": "B"}
            self.assertIsNone(validate_plan_item(item), f"{action} should be valid")

    def test_unknown_action(self):
        self.assertIn("Unknown action", validate_plan_item(_base_item(action="delete")))
        self.assertIn("Unknown action", validate_plan_item(_base_item(action="")))

    def test_action_case_insensitive(self):
        self.assertIsNone(validate_plan_item(_base_item(action="Takeout")))
        self.assertIsNone(validate_plan_item(_base_item(action="THAW")))

    def test_missing_action(self):
        item = _base_item()
        del item["action"]
        self.assertIn("Unknown action", validate_plan_item(item))


class ValidateBoxFieldTests(unittest.TestCase):
    def test_valid_box(self):
        self.assertIsNone(validate_plan_item(_base_item(box=0)))
        self.assertIsNone(validate_plan_item(_base_item(box=5)))

    def test_negative_box(self):
        self.assertIn("box", validate_plan_item(_base_item(box=-1)))

    def test_non_int_box(self):
        self.assertIn("box", validate_plan_item(_base_item(box="abc")))
        self.assertIn("box", validate_plan_item(_base_item(box=1.5)))

    def test_missing_box(self):
        item = _base_item()
        del item["box"]
        self.assertIn("box", validate_plan_item(item))


class ValidatePositionFieldTests(unittest.TestCase):
    def test_valid_position(self):
        self.assertIsNone(validate_plan_item(_base_item(position=1)))
        self.assertIsNone(validate_plan_item(_base_item(position=81)))

    def test_zero_position(self):
        self.assertIn("position", validate_plan_item(_base_item(position=0)))

    def test_negative_position(self):
        self.assertIn("position", validate_plan_item(_base_item(position=-1)))

    def test_non_int_position(self):
        self.assertIn("position", validate_plan_item(_base_item(position="abc")))


class ValidateMoveTests(unittest.TestCase):
    def test_valid_move(self):
        self.assertIsNone(validate_plan_item(_move_item()))

    def test_missing_to_position(self):
        item = _move_item()
        del item["to_position"]
        self.assertIn("to_position", validate_plan_item(item))

    def test_to_position_equals_position(self):
        self.assertIn("differ", validate_plan_item(_move_item(to_position=1)))

    def test_to_position_zero(self):
        self.assertIn("to_position", validate_plan_item(_move_item(to_position=0)))

    def test_to_position_non_int(self):
        self.assertIn("to_position", validate_plan_item(_move_item(to_position="x")))


class ValidateRecordIdTests(unittest.TestCase):
    def test_non_add_requires_record_id(self):
        for action in ("takeout", "thaw", "discard"):
            item = _base_item(action=action)
            del item["record_id"]
            result = validate_plan_item(item)
            self.assertIn("record_id", result, f"{action} without record_id should fail")

    def test_zero_record_id(self):
        self.assertIn("record_id", validate_plan_item(_base_item(record_id=0)))

    def test_negative_record_id(self):
        self.assertIn("record_id", validate_plan_item(_base_item(record_id=-1)))


class ValidateAddPayloadTests(unittest.TestCase):
    def test_valid_add(self):
        self.assertIsNone(validate_plan_item(_add_item()))

    def test_missing_parent_cell_line(self):
        item = _add_item()
        del item["payload"]["parent_cell_line"]
        self.assertIn("parent_cell_line", validate_plan_item(item))

    def test_missing_short_name(self):
        item = _add_item()
        del item["payload"]["short_name"]
        self.assertIn("short_name", validate_plan_item(item))

    def test_null_payload(self):
        self.assertIn("parent_cell_line", validate_plan_item(_add_item(payload=None)))

    def test_empty_payload(self):
        self.assertIn("parent_cell_line", validate_plan_item(_add_item(payload={})))

    def test_add_does_not_require_record_id(self):
        item = _add_item()
        self.assertNotIn("record_id", item)
        self.assertIsNone(validate_plan_item(item))


# ── render_operation_sheet ──────────────────────────────────────────


class RenderOperationSheetTests(unittest.TestCase):
    def test_empty_items(self):
        html = render_operation_sheet([])
        self.assertIn("Total: 0 operation(s)", html)
        self.assertIn("<!DOCTYPE html>", html)

    def test_single_item(self):
        html = render_operation_sheet([_base_item()])
        self.assertIn("Box 1", html)
        self.assertIn("Takeout", html)
        self.assertIn("ID 1", html)
        self.assertIn("Total: 1 operation(s)", html)

    def test_groups_by_box(self):
        items = [
            _base_item(box=2, position=10),
            _base_item(box=1, position=5),
            _base_item(box=2, position=20),
        ]
        html = render_operation_sheet(items)
        self.assertIn("Box 1", html)
        self.assertIn("Box 2", html)
        # Box 1 should appear before Box 2
        self.assertLess(html.index("Box 1"), html.index("Box 2"))

    def test_sorts_by_position_within_box(self):
        items = [
            _base_item(box=1, position=20, label="second"),
            _base_item(box=1, position=10, label="first"),
        ]
        html = render_operation_sheet(items)
        self.assertLess(html.index("first"), html.index("second"))

    def test_move_shows_arrow(self):
        html = render_operation_sheet([_move_item()])
        self.assertIn("&rarr;", html)

    def test_add_shows_new(self):
        html = render_operation_sheet([_add_item()])
        self.assertIn("new", html)

    def test_note_from_payload(self):
        item = _base_item(payload={"note": "my special note"})
        html = render_operation_sheet([item])
        self.assertIn("my special note", html)


# ── to_box validation for move ────────────────────────────────────


class ValidateToBoxTests(unittest.TestCase):
    def test_move_with_valid_to_box(self):
        item = _move_item(to_box=2)
        self.assertIsNone(validate_plan_item(item))

    def test_move_with_invalid_to_box_string(self):
        item = _move_item(to_box="abc")
        self.assertIn("to_box", validate_plan_item(item))

    def test_move_with_to_box_zero(self):
        item = _move_item(to_box=0)
        self.assertIn("to_box", validate_plan_item(item))

    def test_move_with_to_box_negative(self):
        item = _move_item(to_box=-1)
        self.assertIn("to_box", validate_plan_item(item))

    def test_move_without_to_box_ok(self):
        """to_box is optional for move."""
        item = _move_item()
        self.assertIsNone(validate_plan_item(item))

    def test_non_move_ignores_to_box(self):
        """to_box on a non-move action should not cause validation error."""
        item = _base_item(to_box=2)
        self.assertIsNone(validate_plan_item(item))


# ── cross-box move rendering ────────────────────────────────────────


class CrossBoxMoveRenderTests(unittest.TestCase):
    def test_cross_box_move_shows_target_box(self):
        """Move from Box1 pos 5 to Box2 pos 10 should show '5 → Box2:10'."""
        item = _move_item(box=1, position=5, to_position=10, to_box=2)
        html = render_operation_sheet([item])
        self.assertIn("Box2:10", html)

    def test_same_box_move_shows_only_position(self):
        """Move within same box should show '5 → 10' without box prefix."""
        item = _move_item(box=1, position=5, to_position=10, to_box=1)
        html = render_operation_sheet([item])
        self.assertIn("5 &rarr; 10", html)
        self.assertNotIn("Box1:10", html)

    def test_move_without_to_box_shows_only_position(self):
        """Move without explicit to_box should show '5 → 10'."""
        item = _move_item(box=1, position=5, to_position=10)
        html = render_operation_sheet([item])
        self.assertIn("5 &rarr; 10", html)

    def test_cross_box_move_from_box2_to_box5(self):
        """Cross-box move should work for any box combination."""
        item = _move_item(box=2, position=30, to_position=50, to_box=5, label="cross-test")
        html = render_operation_sheet([item])
        self.assertIn("Box5:50", html)
        self.assertIn("cross-test", html)


if __name__ == "__main__":
    unittest.main()
