"""
Module: test_box_layout_mutation_boundary_contract
Layer: contract
Covers: docs/01-系统架构总览.md :: contract:box_layout_mutation_boundary

锁定 box 布局变更（manage_boxes / set_box_tag / set_box_layout_indexing）的
真相源边界：规范化、校验、dry-run 预览、写执行全部归 inventory_core，
GUI/Agent 侧只允许收集输入与确认，不得自定义写校验规则。

除了校验契约块本身结构完整外，还用 AST 静态检查 GUI 应用层与 agent 运行时
不得 import inventory_core 的写校验实现（能结构性校验多少就校验多少）。
"""

import ast
import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import ROOT, load_contract_block

ARCH_DOC = ROOT / "docs" / "01-系统架构总览.md"

# GUI/Agent 侧不得直接依赖 inventory_core 的写/写校验实现。
_FORBIDDEN_WRITE_IMPORT_PREFIXES = (
    "lib.tool_api_write",
    "lib.tool_api_write_validation",
)
_CONSUMER_ROOTS = (
    ROOT / "app_gui" / "application",
    ROOT / "agent",
)


def _import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name or ""))
        elif isinstance(node, ast.ImportFrom):
            modules.add(str(node.module or ""))
    return modules


class BoxLayoutMutationBoundaryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_block(ARCH_DOC, "box_layout_mutation_boundary")
        cls.rules = dict((cls.contract or {}).get("rules") or {})

    def test_block_parses_and_declares_inventory_core_owner(self):
        self.assertTrue(self.rules, "box_layout_mutation_boundary.rules must not be empty")
        self.assertEqual(self.rules.get("owner"), "inventory_core")

    def test_declares_all_box_layout_operations(self):
        operations = list(self.rules.get("operations") or [])
        self.assertEqual(
            {"manage_boxes", "set_box_tag", "set_box_layout_indexing"},
            set(operations),
            "box layout operations set drifted from contract",
        )

    def test_all_truth_source_phases_owned_by_inventory_core(self):
        truth_source = dict(self.rules.get("truth_source") or {})
        expected_phases = {
            "request_normalization",
            "request_validation",
            "dry_run_preview",
            "write_execution",
        }
        self.assertTrue(
            expected_phases <= set(truth_source.keys()),
            f"truth_source missing phases: {expected_phases - set(truth_source.keys())}",
        )
        for phase, owner in truth_source.items():
            with self.subTest(phase=phase):
                self.assertEqual(owner, "inventory_core", f"{phase} must be owned by inventory_core")

    def test_consumers_must_not_define_write_validation_rules(self):
        for consumer in ("gui_application", "agent_runtime"):
            with self.subTest(consumer=consumer):
                spec = dict(self.rules.get(consumer) or {})
                self.assertTrue(spec, f"{consumer} boundary spec must be present")
                self.assertTrue(
                    spec.get("must_not_define_write_validation_rules") is True,
                    f"{consumer} must_not_define_write_validation_rules must be true",
                )

    def test_consumer_code_does_not_import_write_validation_impl(self):
        for consumer_root in _CONSUMER_ROOTS:
            self.assertTrue(consumer_root.exists(), f"consumer root missing: {consumer_root}")
            for file_path in consumer_root.rglob("*.py"):
                modules = _import_modules(file_path)
                offenders = sorted(
                    mod
                    for mod in modules
                    if any(mod.startswith(prefix) for prefix in _FORBIDDEN_WRITE_IMPORT_PREFIXES)
                )
                self.assertEqual(
                    [],
                    offenders,
                    f"{file_path} imports inventory_core write impl, violating box layout boundary: {offenders}",
                )


if __name__ == "__main__":
    unittest.main()
