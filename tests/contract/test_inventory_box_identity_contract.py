"""Contract tests for inventory box identity semantics."""

import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import load_contract_block

ROOT = Path(__file__).resolve().parents[2]
BOX_RULES = load_contract_block(ROOT / "docs" / "01-系统架构总览.md", "inventory_box_identity_rules")


def _rule(name: str) -> dict:
    rules = dict((BOX_RULES or {}).get("rules") or {})
    return dict(rules.get(name) or {})


class InventoryBoxIdentityContractTests(unittest.TestCase):
    def test_box_numbers_declares_stable_numeric_identity(self):
        rule = _rule("box_numbers")
        self.assertEqual("meta.box_layout.box_numbers", rule.get("storage_path"))
        self.assertEqual("positive_integer_list", rule.get("value_type"))
        self.assertEqual("stable_numeric_identity", rule.get("role"))

    def test_inventory_box_field_declares_numeric_reference(self):
        rule = _rule("inventory_box_field")
        self.assertEqual("inventory[].box", rule.get("storage_path"))
        self.assertEqual("positive_integer", rule.get("value_type"))
        self.assertEqual("numeric_identity_reference", rule.get("role"))
        self.assertEqual("stable_numeric_identity", rule.get("must_reference_role"))

    def test_box_tags_declares_optional_tag_only(self):
        rule = _rule("box_tags")
        self.assertEqual("meta.box_layout.box_tags", rule.get("storage_path"))
        self.assertEqual("positive_integer_string", rule.get("key_type"))
        self.assertEqual("single_line_string_max_80", rule.get("value_type"))
        self.assertEqual("optional_tag", rule.get("role"))
        self.assertTrue(rule.get("must_not_be_used_as_identity"))

    def test_display_surfaces_require_numeric_identity_visibility(self):
        rule = _rule("display_surfaces")
        self.assertEqual(["gui", "print", "export"], list(rule.get("surfaces") or []))
        self.assertEqual("meta.box_layout.box_tags", rule.get("tag_source"))
        self.assertTrue(rule.get("must_show_numeric_identity"))
        self.assertTrue(rule.get("may_show_tag"))


if __name__ == "__main__":
    unittest.main()
