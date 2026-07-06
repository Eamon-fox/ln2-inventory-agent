"""
Module: test_dependency_sync
Layer: contract
Covers: pyproject.toml vs requirements.txt / requirements-dev.txt

依赖声明双源一致性门禁：pyproject 与 requirements*.txt 靠注释声明"同源"，
这里用测试把声明变成契约，防止两边静默漂移。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_pyproject_array(text: str, key: str) -> set[str]:
    """Extract a `key = [ "..." ]` string array from pyproject text.

    避免依赖 tomllib（3.11+）；本仓库 pyproject 的依赖数组格式受控，
    用正则提取引号内条目足够且对注释健壮。
    """
    match = re.search(rf"^{re.escape(key)}\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"pyproject.toml 中找不到数组: {key}")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _read_requirements(path: Path) -> set[str]:
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        entries.add(text)
    return entries


def _normalize(entries) -> set[str]:
    # 大小写与空格无关地比较 "name==version" 声明。
    return {re.sub(r"\s+", "", str(item)).lower() for item in entries}


class DependencySyncContractTests(unittest.TestCase):
    def setUp(self):
        self.pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def test_runtime_dependencies_match_requirements_txt(self):
        declared = _normalize(_read_pyproject_array(self.pyproject_text, "dependencies"))
        locked = _normalize(_read_requirements(ROOT / "requirements.txt"))
        self.assertEqual(
            declared,
            locked,
            "pyproject [project].dependencies 与 requirements.txt 漂移，两边需同步修改",
        )

    def test_dev_dependencies_match_requirements_dev_txt(self):
        declared = _normalize(_read_pyproject_array(self.pyproject_text, "dev"))
        locked = _normalize(_read_requirements(ROOT / "requirements-dev.txt"))
        self.assertEqual(
            declared,
            locked,
            "pyproject dev extras 与 requirements-dev.txt 漂移，两边需同步修改",
        )


if __name__ == "__main__":
    unittest.main()
