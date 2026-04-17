"""
Module: test_structured_validation_errors
Layer: integration/inventory
Covers: lib/validation_primitives.py, lib/validators.py, lib/tool_api_support.py

锁定校验链路的结构化错误契约（详见 docs/modules/13-库存核心.md「校验错误输出契约」）：
- validate_inventory 产出的每条错误都是 ValidationMessage（str 子类）且 .detail 带 rule/field 等键。
- _validate_data_or_error 把结构化详情以 errors_detail: list[dict] 形式透出。
- 工具调用失败时，tool_api 返回值同时含 errors（字符串列表）与 errors_detail（字典列表）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api_support import _validate_data_or_error
from lib.validation_primitives import (
    ValidationMessage,
    extract_error_details,
)
from lib.validators import (
    check_duplicate_ids,
    check_position_conflicts,
    validate_inventory,
)


def _make_data(inventory):
    return {
        "meta": {"box_layout": {"box_numbers": [1, 2, 3, 4, 5], "rows": 9, "cols": 9}},
        "inventory": inventory,
    }


class StructuredValidationErrorsTests(unittest.TestCase):
    def test_missing_required_field_emits_structured_detail(self):
        """Missing `box` should produce a ValidationMessage with rule=missing_required."""
        data = _make_data([
            {"id": 1, "stored_at": "2026-02-01", "position": 1},
        ])
        errors, _ = validate_inventory(data)
        self.assertTrue(errors)
        details = extract_error_details(errors)
        missing = [d for d in details if d.get("rule") == "missing_required" and d.get("field") == "box"]
        self.assertEqual(len(missing), 1, f"expected exactly one missing_required for 'box'; got {details}")
        entry = missing[0]
        self.assertEqual(entry.get("record_id"), 1)
        self.assertEqual(entry.get("record_index"), 0)
        self.assertIn("message", entry)

    def test_duplicate_id_conflict_has_structured_detail(self):
        errors = check_duplicate_ids([
            {"id": 7, "box": 1, "position": 1, "stored_at": "2026-02-01"},
            {"id": 7, "box": 1, "position": 2, "stored_at": "2026-02-02"},
        ])
        self.assertEqual(len(errors), 1)
        msg = errors[0]
        self.assertIsInstance(msg, ValidationMessage)
        self.assertEqual(msg.detail.get("rule"), "duplicate_id")
        self.assertEqual(msg.detail.get("field"), "id")
        self.assertEqual(msg.detail.get("value"), 7)
        self.assertEqual(msg.detail.get("record_index"), 1)
        self.assertEqual(msg.detail.get("previous_record_index"), 0)

    def test_position_conflict_has_structured_detail(self):
        conflicts = check_position_conflicts([
            {"id": 1, "box": 1, "position": 3, "stored_at": "2026-02-01"},
            {"id": 2, "box": 1, "position": 3, "stored_at": "2026-02-02"},
        ])
        self.assertEqual(len(conflicts), 1)
        msg = conflicts[0]
        self.assertIsInstance(msg, ValidationMessage)
        self.assertEqual(msg.detail.get("rule"), "position_conflict")
        self.assertEqual(msg.detail.get("box"), 1)
        self.assertEqual(msg.detail.get("position"), 3)
        entries = msg.detail.get("entries") or []
        self.assertEqual({e["record_id"] for e in entries}, {1, 2})

    def test_validate_data_or_error_surfaces_errors_detail(self):
        data = _make_data([
            {"id": 1, "box": 1, "position": 3, "stored_at": "2026-02-01"},
            {"id": 2, "box": 1, "position": 3, "stored_at": "2026-02-02"},
        ])
        payload = _validate_data_or_error(data)
        self.assertIsNotNone(payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "integrity_validation_failed")
        self.assertIn("errors", payload)
        self.assertIn("errors_detail", payload)
        self.assertTrue(all(isinstance(e, str) for e in payload["errors"]))
        self.assertTrue(all(isinstance(e, dict) for e in payload["errors_detail"]))
        rules = {e.get("rule") for e in payload["errors_detail"]}
        self.assertIn("position_conflict", rules)

    def test_errors_detail_entries_preserve_message_fallback(self):
        """Each detail dict must contain a human-readable message fallback."""
        data = _make_data([
            {"id": 1, "box": 99, "stored_at": "not-a-date"},  # out-of-range box + bad date + missing position
        ])
        payload = _validate_data_or_error(data)
        self.assertIsNotNone(payload)
        for detail in payload["errors_detail"]:
            self.assertIn("message", detail)
            self.assertIsInstance(detail["message"], str)
            self.assertTrue(detail["message"].strip())


if __name__ == "__main__":
    unittest.main()
