"""Contract tests for inventory position indexing semantics."""

import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import load_contract_block

ROOT = Path(__file__).resolve().parents[2]
INDEXING_RULES = load_contract_block(
    ROOT / "docs" / "01-系统架构总览.md",
    "inventory_position_indexing_rules",
)


def _rule(name: str) -> dict:
    rules = dict((INDEXING_RULES or {}).get("rules") or {})
    return dict(rules.get(name) or {})


class InventoryPositionIndexingContractTests(unittest.TestCase):
    def test_indexing_field_declares_display_only_mode(self):
        rule = _rule("indexing_field")
        self.assertEqual("meta.box_layout.indexing", rule.get("storage_path"))
        self.assertEqual("display_and_input_mode", rule.get("role"))
        self.assertEqual(["numeric", "alphanumeric"], list(rule.get("allowed_values") or []))
        self.assertEqual("numeric", rule.get("default_value"))

    def test_inventory_position_field_remains_integer_storage(self):
        rule = _rule("inventory_position_field")
        self.assertEqual("inventory[].position", rule.get("storage_path"))
        self.assertEqual("positive_integer", rule.get("value_type"))
        self.assertEqual("stable_internal_slot_identity", rule.get("role"))

    def test_indexing_switch_must_not_rewrite_inventory_positions(self):
        rule = _rule("indexing_switch_behavior")
        self.assertEqual(
            ["gui_display", "gui_input", "tool_input_parsing", "tool_output_formatting"],
            list(rule.get("affects_surfaces") or []),
        )
        self.assertEqual(["inventory[].position"], list(rule.get("must_not_rewrite_storage_path") or []))


if __name__ == "__main__":
    unittest.main()
