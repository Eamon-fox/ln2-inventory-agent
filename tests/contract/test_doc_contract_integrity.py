"""Integrity checks for machine-readable architecture contracts in docs."""

import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import ROOT, load_contract_block, parse_contract_blocks


ARCH_DOC = ROOT / "docs" / "01-系统架构总览.md"
MODULE_MAP_DOC = ROOT / "docs" / "02-模块地图.md"
CHOKEPOINT_DOC = ROOT / "docs" / "03-共享瓶颈点.md"
POLICY_DOC = ROOT / "docs" / "00-约束模型.md"


class DocContractIntegrityTests(unittest.TestCase):
    def test_required_contract_blocks_exist(self):
        expected = {
            ARCH_DOC: {
                "layer_rules",
                "agent_context_checkpointing",
                "agent_builtin_skills",
                "local_open_api_boundary",
                "inventory_position_indexing_rules",
            },
            MODULE_MAP_DOC: {"module_map"},
            CHOKEPOINT_DOC: {"shared_chokepoints"},
        }
        for path, required_names in expected.items():
            self.assertTrue(path.exists(), f"Contract doc missing: {path}")
            blocks = parse_contract_blocks(path)
            self.assertTrue(required_names <= set(blocks.keys()), f"{path} missing contract blocks: {required_names - set(blocks.keys())}")

    def test_constraint_policy_doc_exists(self):
        self.assertTrue(POLICY_DOC.exists(), f"Constraint policy doc missing: {POLICY_DOC}")

    def test_layer_rule_paths_exist(self):
        layer_rules = load_contract_block(ARCH_DOC, "layer_rules")
        for rule_name, rule in dict(layer_rules.get("rules") or {}).items():
            paths = list((rule or {}).get("paths") or [])
            self.assertTrue(paths, f"{rule_name} should declare paths")
            for rel_path in paths:
                self.assertTrue((ROOT / rel_path).exists(), f"{rule_name} path missing: {rel_path}")

    def test_shared_chokepoints_exist(self):
        chokepoints = load_contract_block(CHOKEPOINT_DOC, "shared_chokepoints")
        for rel_path in list(chokepoints.get("paths") or []):
            self.assertTrue((ROOT / rel_path).exists(), f"Shared chokepoint path missing: {rel_path}")

    def test_module_map_references_existing_docs_and_runbooks(self):
        module_map = load_contract_block(MODULE_MAP_DOC, "module_map")
        modules = dict(module_map.get("modules") or {})
        self.assertTrue(modules, "module_map.modules must not be empty")
        for module_id, spec in modules.items():
            module_doc = str((spec or {}).get("module_doc") or "").strip()
            self.assertTrue(module_doc, f"{module_id} missing module_doc")
            self.assertTrue((ROOT / module_doc).exists(), f"{module_id} module_doc missing on disk: {module_doc}")
            for rel_path in list((spec or {}).get("owned_paths") or []):
                if "*" in str(rel_path):
                    continue
                self.assertTrue((ROOT / rel_path).exists(), f"{module_id} owned path missing: {rel_path}")


if __name__ == "__main__":
    unittest.main()
