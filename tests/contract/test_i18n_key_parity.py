"""
Module: test_i18n_key_parity
Layer: contract
Covers: app_gui/i18n/translations/en.json, app_gui/i18n/translations/zh-CN.json

锁定中英文翻译键完全对齐：扁平化后两份文件的键集合必须完全一致，
防止任一语言漏键/多键导致运行时缺失翻译。
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
I18N_DIR = ROOT / "app_gui" / "i18n" / "translations"


def _flatten(obj, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            child = _flatten(value, path)
            if child:
                keys |= child
            else:
                keys.add(path)
    return keys


def _flat_keys(locale_file: str) -> set[str]:
    data = json.loads((I18N_DIR / locale_file).read_text(encoding="utf-8"))
    return _flatten(data)


class I18nKeyParityTests(unittest.TestCase):
    def test_en_and_zh_have_identical_flat_key_sets(self):
        en_keys = _flat_keys("en.json")
        zh_keys = _flat_keys("zh-CN.json")

        missing_in_zh = sorted(en_keys - zh_keys)
        missing_in_en = sorted(zh_keys - en_keys)

        self.assertEqual([], missing_in_zh, f"keys present in en.json but missing in zh-CN.json: {missing_in_zh}")
        self.assertEqual([], missing_in_en, f"keys present in zh-CN.json but missing in en.json: {missing_in_en}")


if __name__ == "__main__":
    unittest.main()
