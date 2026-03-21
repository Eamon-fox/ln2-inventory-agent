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

from lib.csv_export import build_export_columns, build_export_rows


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

    def test_build_export_rows_uses_alphanumeric_position_display(self):
        meta = {"box_layout": {"rows": 3, "cols": 3, "indexing": "alphanumeric"}}
        records = [
            {"id": 1, "box": 1, "position": 2, "frozen_at": "2026-03-22", "note": "alpha"},
        ]

        split_payload = build_export_rows(records, meta=meta, split_location=True)
        self.assertEqual("A2", split_payload["rows"][0]["position"])

        merged_payload = build_export_rows(records, meta=meta, split_location=False)
        self.assertEqual("1:A2", merged_payload["rows"][0]["location"])

    def test_build_export_rows_formats_move_thaw_events_with_display_positions(self):
        meta = {"box_layout": {"rows": 3, "cols": 3, "indexing": "alphanumeric"}}
        records = [
            {
                "id": 1,
                "box": 1,
                "position": 2,
                "frozen_at": "2026-03-22",
                "thaw_events": [
                    {
                        "date": "2026-03-21",
                        "action": "move",
                        "from_position": 2,
                        "to_position": 4,
                    }
                ],
            },
        ]

        payload = build_export_rows(records, meta=meta, split_location=True)
        self.assertEqual("2026-03-21 move A2->B1", payload["rows"][0]["thaw_events"])


if __name__ == "__main__":
    unittest.main()
