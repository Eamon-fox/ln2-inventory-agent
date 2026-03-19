import unittest

from lib.schema_aliases import (
    coalesce_stored_at_value,
    expand_structural_aliases_in_sections,
    normalize_record_sort_field,
    normalize_structural_alias_input_map,
    present_record_sort_field,
)


class TestSchemaAliases(unittest.TestCase):
    def test_coalesce_stored_at_prefers_canonical(self):
        self.assertEqual(
            "2026-03-01",
            coalesce_stored_at_value(
                stored_at="2026-03-01",
                frozen_at="2026-02-01",
            ),
        )

    def test_coalesce_stored_at_falls_back_to_legacy(self):
        self.assertEqual(
            "2026-02-01",
            coalesce_stored_at_value(
                stored_at="",
                frozen_at="2026-02-01",
            ),
        )

    def test_normalize_record_sort_field_maps_legacy_alias(self):
        self.assertEqual("stored_at", normalize_record_sort_field("frozen_at"))
        self.assertEqual("stored_at", normalize_record_sort_field(None))
        self.assertEqual("box", normalize_record_sort_field(" box "))

    def test_present_record_sort_field_preserves_requested_shape(self):
        self.assertEqual(
            "frozen_at",
            present_record_sort_field("stored_at", requested=None, default_legacy=True),
        )
        self.assertEqual(
            "stored_at",
            present_record_sort_field("stored_at", requested="stored_at", default_legacy=True),
        )
        self.assertEqual(
            "frozen_at",
            present_record_sort_field("stored_at", requested="frozen_at", default_legacy=False),
        )
        self.assertEqual(
            "stored_at",
            present_record_sort_field("frozen_at", requested=None, default_legacy=False),
        )

    def test_normalize_structural_alias_input_map_maps_legacy_to_canonical(self):
        normalized, errors = normalize_structural_alias_input_map(
            {
                "frozen_at": "2026-02-10",
                "note": "legacy",
            },
            scope="fields",
        )

        self.assertEqual(
            {
                "stored_at": "2026-02-10",
                "note": "legacy",
            },
            normalized,
        )
        self.assertEqual([], errors)

    def test_normalize_structural_alias_input_map_reports_conflicts(self):
        normalized, errors = normalize_structural_alias_input_map(
            {
                "stored_at": "2026-02-10",
                "frozen_at": "2026-02-11",
            },
            scope="fields",
        )

        self.assertEqual({"stored_at": "2026-02-10"}, normalized)
        self.assertEqual(["fields.stored_at conflicts with fields.frozen_at"], errors)

    def test_normalize_structural_alias_input_map_prefers_nonempty_legacy_over_blank_canonical(self):
        normalized, errors = normalize_structural_alias_input_map(
            {
                "stored_at": "",
                "frozen_at": "2026-02-11",
            },
            scope="fields",
        )

        self.assertEqual({"stored_at": "2026-02-11"}, normalized)
        self.assertEqual([], errors)

    def test_expand_structural_aliases_in_sections_populates_before_and_after(self):
        payload = {
            "before": {"stored_at": "2026-02-10"},
            "after": {"thaw_events": [{"action": "takeout"}]},
            "other": {"stored_at": "2026-02-12"},
        }

        expand_structural_aliases_in_sections(payload)

        self.assertEqual("2026-02-10", payload["before"]["frozen_at"])
        self.assertEqual(
            [{"action": "takeout"}],
            payload["after"]["storage_events"],
        )
        self.assertNotIn("frozen_at", payload["other"])


if __name__ == "__main__":
    unittest.main()
