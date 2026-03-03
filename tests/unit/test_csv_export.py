"""
Module: test_csv_export
Layer: unit
Covers: lib/csv_export.py

Export columns should be derived from effective fields declared in metadata.
"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.csv_export import build_export_columns


class CsvExportColumnsTests(unittest.TestCase):
    def test_build_export_columns_follows_effective_field_order(self):
        meta = {
            "custom_fields": [
                {"key": "short_name", "label": "Short Name", "type": "str"},
                {"key": "project_code", "label": "Project", "type": "str"},
            ]
        }

        columns = build_export_columns(meta, split_location=False)
        self.assertEqual(
            [
                "id",
                "location",
                "frozen_at",
                "note",
                "short_name",
                "project_code",
                "thaw_events",
            ],
            columns,
        )

    def test_build_export_columns_split_location_keeps_same_field_policy(self):
        meta = {"custom_fields": [{"key": "batch_tag", "label": "Batch", "type": "str"}]}

        columns = build_export_columns(meta, split_location=True)
        self.assertEqual(
            [
                "id",
                "box",
                "position",
                "frozen_at",
                "note",
                "batch_tag",
                "thaw_events",
            ],
            columns,
        )


if __name__ == "__main__":
    unittest.main()
