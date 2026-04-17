"""
Module: test_strict_legacy_validation
Layer: integration/inventory
Covers: lib/config.py, lib/tool_api_support.py, lib/validators.py

锁定「历史脏数据不阻断新写入」契约（详见 docs/modules/13-库存核心.md
「校验错误输出契约」）：

- 选项字段违规（option_field_* 规则族）默认进入 warnings，不出现在
  `_validate_data_or_error` 返回的 errors/errors_detail 中。
- ``LN2_STRICT_LEGACY_VALIDATION=true`` / ``validation.strict_legacy_validation``
  打开时，这些 warnings 会被提升为 errors，并带 structured detail。
- ``_collect_legacy_warnings`` 暴露给上层用于提示「数据集还有 N 条历史
  数据问题」的非阻塞统计。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import config as _config
from lib.tool_api_support import _collect_legacy_warnings, _validate_data_or_error


def _make_data(inventory, option_fields=None):
    meta = {
        "box_layout": {"box_numbers": [1, 2, 3, 4, 5], "rows": 9, "cols": 9},
    }
    if option_fields:
        meta["custom_fields"] = option_fields
    return {"meta": meta, "inventory": inventory}


_OPTION_FIELDS = [
    {"key": "cell_line", "options": ["K562", "HeLa"], "required": False},
]


_LEGACY_INVENTORY = [
    {
        "id": 1,
        "box": 1,
        "position": 1,
        "stored_at": "2026-02-01",
        "cell_line": "NOT_IN_LIST",
    }
]


class StrictLegacyValidationTests(unittest.TestCase):
    def setUp(self):
        self._prev_env = os.environ.pop("LN2_STRICT_LEGACY_VALIDATION", None)

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("LN2_STRICT_LEGACY_VALIDATION", None)
        else:
            os.environ["LN2_STRICT_LEGACY_VALIDATION"] = self._prev_env

    def test_default_permissive_does_not_block_on_option_violation(self):
        data = _make_data(_LEGACY_INVENTORY, option_fields=_OPTION_FIELDS)
        self.assertFalse(_config.strict_legacy_validation())
        self.assertIsNone(_validate_data_or_error(data))

    def test_legacy_warnings_surface_structured_detail(self):
        data = _make_data(_LEGACY_INVENTORY, option_fields=_OPTION_FIELDS)
        details = _collect_legacy_warnings(data)
        self.assertTrue(details)
        rules = {d.get("rule") for d in details}
        self.assertIn("option_field_not_in_options", rules)
        bad = next(d for d in details if d.get("rule") == "option_field_not_in_options")
        self.assertEqual(bad.get("field"), "cell_line")
        self.assertEqual(bad.get("value"), "NOT_IN_LIST")
        self.assertIn("K562", bad.get("expected") or [])

    def test_env_toggle_promotes_warnings_to_blocking_errors(self):
        os.environ["LN2_STRICT_LEGACY_VALIDATION"] = "true"
        self.assertTrue(_config.strict_legacy_validation())
        data = _make_data(_LEGACY_INVENTORY, option_fields=_OPTION_FIELDS)
        payload = _validate_data_or_error(data)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["error_code"], "integrity_validation_failed")
        rules = {d.get("rule") for d in payload["errors_detail"]}
        self.assertIn("option_field_not_in_options", rules)

    def test_clean_data_has_no_legacy_warnings(self):
        data = _make_data(
            [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "stored_at": "2026-02-01",
                    "cell_line": "K562",
                }
            ],
            option_fields=_OPTION_FIELDS,
        )
        self.assertEqual(_collect_legacy_warnings(data), [])


if __name__ == "__main__":
    unittest.main()
