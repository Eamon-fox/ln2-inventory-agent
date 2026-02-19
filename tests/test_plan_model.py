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
            "fields": {
                "parent_cell_line": "K562",
                "short_name": "clone-1",
            },
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


def _rollback_item(**overrides):
    """Construct a minimal valid PlanItem for rollback."""
    base = {
        "action": "rollback",
        "box": 0,
        "position": 1,
        "record_id": None,
        "label": "Rollback",
        "source": "human",
        "payload": {
            "backup_path": "/tmp/fake_backup.bak",
        },
    }
    base.update(overrides)
    return base


# ── validate_plan_item ──────────────────────────────────────────────


class ValidateActionTests(unittest.TestCase):
    def test_all_valid_actions(self):
        for action in ("takeout", "thaw", "discard", "move", "add", "rollback"):
            if action == "rollback":
                item = _rollback_item()
            else:
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

    def test_rollback_does_not_require_record_id(self):
        item = _rollback_item()
        self.assertIsNone(validate_plan_item(item))


class ValidateAddPayloadTests(unittest.TestCase):
    def test_valid_add(self):
        self.assertIsNone(validate_plan_item(_add_item()))

    def test_missing_fields_passes_plan_validation(self):
        """Required field checks happen at execution time, not plan validation."""
        item = _add_item()
        item["payload"]["fields"] = {}
        self.assertIsNone(validate_plan_item(item))

    def test_null_payload_passes(self):
        """Null payload is acceptable at plan validation time."""
        self.assertIsNone(validate_plan_item(_add_item(payload=None)))

    def test_empty_payload_passes(self):
        """Empty payload is acceptable at plan validation time."""
        self.assertIsNone(validate_plan_item(_add_item(payload={})))

    def test_add_does_not_require_record_id(self):
        item = _add_item()
        self.assertNotIn("record_id", item)
        self.assertIsNone(validate_plan_item(item))


# ── render_operation_sheet ──────────────────────────────────────────


class RenderOperationSheetTests(unittest.TestCase):
    def test_empty_items(self):
        html = render_operation_sheet([])
        self.assertIn("No operations", html)
        self.assertIn("<!DOCTYPE html>", html)

    def test_single_item(self):
        html = render_operation_sheet([_base_item()])
        self.assertIn("Box1:", html)
        self.assertIn("TAKEOUT", html)
        self.assertIn("ID: 1", html)
        self.assertIn("1 operations", html)

    def test_groups_by_action(self):
        items = [
            _base_item(box=2, position=10),
            _base_item(box=1, position=5),
            _base_item(box=2, position=20),
        ]
        html = render_operation_sheet(items)
        self.assertIn("TAKEOUT", html)
        self.assertIn("3 operations", html)

    def test_sorts_by_position(self):
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
        self.assertIn("NEW", html)

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
        """Move from Box1 pos 5 to Box2 pos 10 should show 'Box2:B1' (coord)."""
        item = _move_item(box=1, position=5, to_position=10, to_box=2)
        html = render_operation_sheet([item])
        self.assertIn("Box2:", html)

    def test_same_box_move_shows_only_position(self):
        """Move within same box should show arrow without [CROSS-BOX] warning."""
        item = _move_item(box=1, position=5, to_position=10, to_box=1)
        html = render_operation_sheet([item])
        self.assertIn("&rarr;", html)
        self.assertNotIn("[CROSS-BOX]", html)

    def test_move_without_to_box_shows_only_position(self):
        """Move without explicit to_box should show arrow."""
        item = _move_item(box=1, position=5, to_position=10)
        html = render_operation_sheet([item])
        self.assertIn("&rarr;", html)

    def test_cross_box_move_from_box2_to_box5(self):
        """Cross-box move should work for any box combination."""
        item = _move_item(box=2, position=30, to_position=50, to_box=5, label="cross-test")
        html = render_operation_sheet([item])
        self.assertIn("Box5:", html)
        self.assertIn("[CROSS-BOX]", html)
        self.assertIn("cross-test", html)


# ── edit action validation ─────────────────────────────────────────


def _edit_item(**overrides):
    """Construct a minimal valid PlanItem for edit."""
    base = {
        "action": "edit",
        "box": 1,
        "position": 5,
        "record_id": 1,
        "label": "test",
        "source": "human",
        "payload": {
            "record_id": 1,
            "fields": {"note": "updated"},
        },
    }
    base.update(overrides)
    return base


class ValidateEditTests(unittest.TestCase):
    def test_valid_edit(self):
        self.assertIsNone(validate_plan_item(_edit_item()))

    def test_edit_requires_record_id(self):
        item = _edit_item(record_id=None)
        self.assertIn("record_id", validate_plan_item(item))

    def test_edit_zero_record_id(self):
        self.assertIn("record_id", validate_plan_item(_edit_item(record_id=0)))

    def test_edit_requires_valid_position(self):
        self.assertIn("position", validate_plan_item(_edit_item(position=0)))

    def test_edit_requires_valid_box(self):
        self.assertIn("box", validate_plan_item(_edit_item(box=-1)))

    def test_edit_in_all_valid_actions(self):
        item = _edit_item()
        self.assertIsNone(validate_plan_item(item))


class ValidateRollbackSkipsBoxPositionTests(unittest.TestCase):
    def test_rollback_box_zero_ok(self):
        self.assertIsNone(validate_plan_item(_rollback_item(box=0)))

    def test_rollback_position_any_ok(self):
        """Rollback skips position validation entirely."""
        self.assertIsNone(validate_plan_item(_rollback_item(position=0)))

    def test_rollback_no_record_id_ok(self):
        self.assertIsNone(validate_plan_item(_rollback_item(record_id=None)))


# ── edit/rollback rendering ────────────────────────────────────────


class RenderEditRollbackTests(unittest.TestCase):
    def test_edit_appears_in_operation_sheet(self):
        html = render_operation_sheet([_edit_item()])
        self.assertIn("EDIT", html)
        self.assertIn("ID: 1", html)

    def test_rollback_appears_in_operation_sheet(self):
        html = render_operation_sheet([_rollback_item()])
        self.assertIn("ROLLBACK", html)

    def test_summary_includes_edit_count(self):
        items = [_edit_item(), _edit_item(record_id=2)]
        html = render_operation_sheet(items)
        self.assertIn("Edit: 2", html)

    def test_summary_includes_rollback_count(self):
        html = render_operation_sheet([_rollback_item()])
        self.assertIn("Rollback: 1", html)

    def test_mixed_actions_all_rendered(self):
        items = [
            _base_item(),
            _add_item(),
            _move_item(),
            _edit_item(),
            _rollback_item(),
        ]
        html = render_operation_sheet(items)
        for action_name in ("TAKEOUT", "ADD", "MOVE", "EDIT", "ROLLBACK"):
            self.assertIn(action_name, html)


# ── factory → validate round-trip ──────────────────────────────────


class FactoryValidateRoundTripTests(unittest.TestCase):
    """Verify that plan_item_factory outputs pass validate_plan_item."""

    def test_build_edit_plan_item_passes_validation(self):
        from lib.plan_item_factory import build_edit_plan_item
        item = build_edit_plan_item(
            record_id=3, fields={"note": "x"}, box=2, position=10,
        )
        self.assertIsNone(validate_plan_item(item))

    def test_build_edit_plan_item_default_position_passes(self):
        from lib.plan_item_factory import build_edit_plan_item
        item = build_edit_plan_item(record_id=1, fields={"note": "x"})
        self.assertIsNone(validate_plan_item(item))

    def test_build_rollback_plan_item_passes_validation(self):
        from lib.plan_item_factory import build_rollback_plan_item
        item = build_rollback_plan_item(backup_path="/tmp/backup.bak")
        self.assertIsNone(validate_plan_item(item))

    def test_build_rollback_plan_item_keeps_source_event(self):
        from lib.plan_item_factory import build_rollback_plan_item

        item = build_rollback_plan_item(
            backup_path="/tmp/backup.bak",
            source_event={"timestamp": "2026-02-12T09:00:00", "trace_id": "trace-audit-1"},
        )
        self.assertEqual("trace-audit-1", (item.get("payload") or {}).get("source_event", {}).get("trace_id"))
        self.assertIsNone(validate_plan_item(item))

    def test_build_record_plan_item_passes_validation(self):
        from lib.plan_item_factory import build_record_plan_item
        for action in ("Takeout", "Thaw", "Discard"):
            item = build_record_plan_item(
                action=action, record_id=1, position=5, box=1,
                date_str="2026-01-01",
            )
            self.assertIsNone(validate_plan_item(item), f"{action} should pass")

    def test_build_record_plan_item_canonicalizes_legacy_out_actions(self):
        from lib.plan_item_factory import build_record_plan_item

        thaw_item = build_record_plan_item(
            action="Thaw", record_id=1, position=5, box=1, date_str="2026-01-01"
        )
        discard_item = build_record_plan_item(
            action="Discard", record_id=2, position=6, box=1, date_str="2026-01-01"
        )

        self.assertEqual("takeout", thaw_item.get("action"))
        self.assertEqual("takeout", discard_item.get("action"))

    def test_build_add_plan_item_passes_validation(self):
        from lib.plan_item_factory import build_add_plan_item
        item = build_add_plan_item(
            box=1, positions=[5], frozen_at="2026-01-01",
            fields={"parent_cell_line": "K562", "short_name": "clone-1"},
        )
        self.assertIsNone(validate_plan_item(item))


if __name__ == "__main__":
    unittest.main()
