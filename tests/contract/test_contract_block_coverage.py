"""
Module: test_contract_block_coverage
Layer: contract
Covers: docs/**/*.md (排除 docs/reviews/**) 的所有 machine-readable 契约块

元测试：防止"有契约无锁"。扫描全部文档里的 `<!-- contract:NAME -->` 块名，
断言每个块名都至少被 tests/contract/*.py 中一次 load_contract_block(..., "NAME")
调用引用。新增契约块却没写锁测试时，本测试会失败。
"""

import ast
import re
import unittest
from pathlib import Path

from tests.contract.doc_contract_loader import ROOT

DOCS_DIR = ROOT / "docs"
CONTRACT_TESTS_DIR = ROOT / "tests" / "contract"
EXCLUDED_DOC_DIRS = (DOCS_DIR / "reviews",)

_CONTRACT_NAME_RE = re.compile(r"<!--\s*contract:(?P<name>[a-zA-Z0-9_-]+)\s*-->")


def _iter_doc_files():
    for path in DOCS_DIR.rglob("*.md"):
        if any(str(path).startswith(str(excluded)) for excluded in EXCLUDED_DOC_DIRS):
            continue
        yield path


def _declared_contract_blocks() -> dict[str, list[str]]:
    """Map contract block name -> list of docs declaring it."""
    declared: dict[str, list[str]] = {}
    for path in _iter_doc_files():
        text = path.read_text(encoding="utf-8-sig")
        for match in _CONTRACT_NAME_RE.finditer(text):
            name = match.group("name")
            declared.setdefault(name, []).append(str(path.relative_to(ROOT)))
    return declared


def _referenced_block_names() -> set[str]:
    """Collect every string literal passed to load_contract_block(...) in contract tests."""
    referenced: set[str] = set()
    for path in CONTRACT_TESTS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = (
                func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            )
            if func_name != "load_contract_block":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    referenced.add(arg.value)
    return referenced


class ContractBlockCoverageTests(unittest.TestCase):
    def test_every_declared_contract_block_is_locked_by_a_test(self):
        declared = _declared_contract_blocks()
        self.assertTrue(declared, "no contract blocks discovered under docs/")

        referenced = _referenced_block_names()
        unlocked = sorted(name for name in declared if name not in referenced)
        self.assertEqual(
            [],
            unlocked,
            "contract blocks without any load_contract_block lock in tests/contract/: "
            + ", ".join(f"{name} ({', '.join(declared[name])})" for name in unlocked),
        )


if __name__ == "__main__":
    unittest.main()
