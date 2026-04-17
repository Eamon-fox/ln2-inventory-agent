"""
Module: test_incremental_validation
Layer: integration/inventory
Covers: lib/validators.py, lib/tool_api_support.py

锁定 validate_inventory / _validate_data_or_error 的 `changed_ids` 增量契约
（详见 docs/modules/13-库存核心.md「校验错误输出契约」）：

- 不传 changed_ids：全量校验，行为与历史一致。
- 传 changed_ids：
  - 按 record id 过滤 per-record 检查 (validate_record)；
  - cross-record 检查 (duplicate_id / position_conflict) 仍扫全量，
    因为其约束本身是全局的。
- 这样调用方（write_edit_entry / write_add_entry / write_takeout_*）
  可以把「只改了 N 条里某一条」的 per-record 成本降到 O(1)，同时保留
  跨记录冲突检测的正确性。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api_support import _validate_data_or_error
from lib.validators import validate_inventory


def _data_with(inventory):
    return {
        "meta": {"box_layout": {"box_numbers": [1, 2, 3, 4, 5], "rows": 9, "cols": 9}},
        "inventory": inventory,
    }


class IncrementalValidationTests(unittest.TestCase):
    def test_full_validation_reports_all_bad_records(self):
        data = _data_with(
            [
                {"id": 1, "box": 99, "position": 1, "stored_at": "2026-02-01"},
                {"id": 2, "box": 98, "position": 2, "stored_at": "2026-02-01"},
                {"id": 3, "box": 97, "position": 3, "stored_at": "2026-02-01"},
            ]
        )
        errors, _warnings = validate_inventory(data)
        bad_records = {
            d.get("record_id")
            for d in (getattr(e, "detail", {}) for e in errors)
            if d.get("rule") == "box_out_of_range"
        }
        self.assertEqual(bad_records, {1, 2, 3})

    def test_changed_ids_skips_unchanged_per_record_errors(self):
        data = _data_with(
            [
                {"id": 1, "box": 99, "position": 1, "stored_at": "2026-02-01"},
                {"id": 2, "box": 98, "position": 2, "stored_at": "2026-02-01"},
                {"id": 3, "box": 1, "position": 3, "stored_at": "2026-02-01"},
            ]
        )
        errors, _warnings = validate_inventory(data, changed_ids=[3])
        bad_records = {
            d.get("record_id")
            for d in (getattr(e, "detail", {}) for e in errors)
            if d.get("rule") == "box_out_of_range"
        }
        self.assertEqual(bad_records, set())

    def test_changed_ids_still_surfaces_global_conflicts_from_untouched_records(self):
        """Cross-record rules keep scanning everything even with changed_ids."""
        data = _data_with(
            [
                {"id": 1, "box": 1, "position": 5, "stored_at": "2026-02-01"},
                {"id": 2, "box": 1, "position": 5, "stored_at": "2026-02-01"},
                {"id": 3, "box": 2, "position": 7, "stored_at": "2026-02-01"},
            ]
        )
        errors, _warnings = validate_inventory(data, changed_ids=[3])
        rules = {
            getattr(e, "detail", {}).get("rule") for e in errors
        }
        self.assertIn("position_conflict", rules)

    def test_validate_data_or_error_threads_changed_ids(self):
        data = _data_with(
            [
                {"id": 1, "box": 99, "position": 1, "stored_at": "2026-02-01"},
                {"id": 2, "box": 1, "position": 2, "stored_at": "2026-02-01"},
            ]
        )
        full = _validate_data_or_error(data)
        self.assertIsNotNone(full)
        self.assertTrue(
            any(
                d.get("rule") == "box_out_of_range" and d.get("record_id") == 1
                for d in full["errors_detail"]
            )
        )
        incremental = _validate_data_or_error(data, changed_ids=[2])
        self.assertIsNone(incremental)

    def test_changed_ids_none_preserves_full_behavior(self):
        data = _data_with(
            [
                {"id": 1, "box": 1, "position": 1, "stored_at": "2026-02-01"},
                {"id": 2, "box": 99, "position": 2, "stored_at": "2026-02-01"},
            ]
        )
        with_none = validate_inventory(data, changed_ids=None)
        without_kwarg = validate_inventory(data)
        self.assertEqual(
            [str(e) for e in with_none[0]],
            [str(e) for e in without_kwarg[0]],
        )

    def test_empty_changed_ids_skips_all_per_record_checks(self):
        """Empty set = 'no records changed' ⇒ per-record errors all suppressed."""
        data = _data_with(
            [
                {"id": 1, "box": 99, "position": 1, "stored_at": "2026-02-01"},
            ]
        )
        errors, _warnings = validate_inventory(data, changed_ids=[])
        per_record_rules = {
            getattr(e, "detail", {}).get("rule")
            for e in errors
            if getattr(e, "detail", {}).get("rule") == "box_out_of_range"
        }
        self.assertEqual(per_record_rules, set())


if __name__ == "__main__":
    unittest.main()
