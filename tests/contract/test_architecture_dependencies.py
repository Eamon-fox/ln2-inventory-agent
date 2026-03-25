"""Contract tests for architecture dependency boundaries."""

import ast
import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import load_contract_block

ROOT = Path(__file__).resolve().parents[2]
LAYER_RULES = load_contract_block(ROOT / "docs" / "01-系统架构总览.md", "layer_rules")


def _layer_rule(rule_name: str) -> dict:
    rules = dict((LAYER_RULES or {}).get("rules") or {})
    return dict(rules.get(rule_name) or {})


def _parse_ast(path: Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _import_modules(path: Path):
    tree = _parse_ast(path)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name or ""))
        elif isinstance(node, ast.ImportFrom):
            modules.add(str(node.module or ""))
    return modules


class ArchitectureDependencyTests(unittest.TestCase):
    def test_layer_rules_forbid_declared_import_prefixes(self):
        rules = dict((LAYER_RULES or {}).get("rules") or {})
        self.assertTrue(rules, "layer_rules.rules must not be empty")

        for rule_name, raw_rule in rules.items():
            with self.subTest(rule=rule_name):
                rule = dict(raw_rule or {})
                target_paths = [ROOT / rel_path for rel_path in list(rule.get("paths") or [])]
                forbidden_prefixes = tuple(
                    str(item) for item in list(rule.get("forbidden_import_prefixes") or [])
                )
                self.assertTrue(target_paths, f"{rule_name} paths must not be empty")
                self.assertTrue(
                    forbidden_prefixes,
                    f"{rule_name} forbidden imports must not be empty",
                )

                for target_root in target_paths:
                    self.assertTrue(target_root.exists(), f"{target_root} should exist")
                    for file_path in target_root.rglob("*.py"):
                        modules = _import_modules(file_path)
                        offenders = sorted(
                            mod
                            for mod in modules
                            if any(mod.startswith(prefix) for prefix in forbidden_prefixes)
                        )
                        self.assertEqual(
                            [],
                            offenders,
                            f"{file_path} violates {rule_name}: {offenders}",
                        )


if __name__ == "__main__":
    unittest.main()
