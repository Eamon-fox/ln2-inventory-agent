"""
Module: test_validate_service
Layer: unit
Covers: lib/validate_service.py

验证通用 validate 服务的自动模式分发与告警语义。
"""

import sys
from pathlib import Path

from tests.managed_paths import ManagedPathTestCase


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.validate_service import (  # noqa: E402
    VALIDATION_MODE_META_ONLY,
    validate_yaml_data,
    validate_yaml_file,
)


class ValidateServiceTests(ManagedPathTestCase):
    def test_validate_yaml_file_detects_current_inventory_mode(self):
        managed_path = Path(self.fake_yaml_path)
        managed_path.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "inventory: []\n"
                "color_key: legacy_alias\n"
            ),
            encoding="utf-8",
        )

        result = validate_yaml_file(self.fake_yaml_path)

        self.assertTrue(result.get("ok"), result)
        report = result.get("report") or {}
        self.assertEqual("current_inventory", report.get("mode"))
        self.assertEqual(0, report.get("error_count"))

    def test_validate_yaml_file_detects_document_mode(self):
        repo_root = Path(self.fake_yaml_path).resolve().parents[2]
        candidate = repo_root / "migrate" / "output" / "ln2_inventory.yaml"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "inventory: []\n"
            ),
            encoding="utf-8",
        )

        result = validate_yaml_file(str(candidate))

        self.assertTrue(result.get("ok"), result)
        report = result.get("report") or {}
        self.assertEqual("document", report.get("mode"))

    def test_validate_yaml_file_keeps_warnings_non_blocking_by_default(self):
        repo_root = Path(self.fake_yaml_path).resolve().parents[2]
        candidate = repo_root / "migrate" / "output" / "warn.yaml"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "  cell_line_options: [K562, HeLa]\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: H1299\n"
            ),
            encoding="utf-8",
        )

        result = validate_yaml_file(str(candidate))

        self.assertTrue(result.get("ok"), result)
        report = result.get("report") or {}
        self.assertEqual(0, report.get("error_count"))
        self.assertGreater(report.get("warning_count") or 0, 0)

    def test_validate_yaml_data_meta_only_preserves_internal_mode(self):
        payload = {
            "meta": {
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "cell_line_options": ["K562", "HeLa"],
            },
            "inventory": [
                {
                    "id": 1,
                    "box": 1,
                    "position": 1,
                    "frozen_at": "2024-01-01",
                    "cell_line": "H1299",
                }
            ],
        }

        result = validate_yaml_data(payload, mode=VALIDATION_MODE_META_ONLY)

        self.assertTrue(result.get("ok"), result)
        report = result.get("report") or {}
        self.assertEqual("meta_only", report.get("mode"))
        self.assertEqual(0, report.get("error_count"))
        self.assertEqual(0, report.get("warning_count"))
