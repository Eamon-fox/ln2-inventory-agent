"""Unit tests for schema-first field helpers."""

from datetime import timedelta

from lib.field_schema import (
    ALIAS_COMPAT_END_DATE,
    get_applicable_alias_map,
    migrate_record_aliases,
    normalize_input_fields,
    ordered_field_items,
    split_record_fields,
)


class TestAliasMap:
    def test_alias_map_enabled_when_canonical_exists(self):
        alias_map = get_applicable_alias_map({})
        assert alias_map.get("parent_cell_line") == "cell_line"

    def test_alias_map_disabled_when_alias_is_declared_key(self):
        meta = {
            "custom_fields": [
                {"key": "parent_cell_line", "label": "Parent", "type": "str"},
            ],
        }
        assert get_applicable_alias_map(meta) == {}


class TestNormalizeInputFields:
    def test_preserves_alias_when_alias_is_explicitly_declared(self):
        result = normalize_input_fields(
            {"parent_cell_line": "K562"},
            {
                "custom_fields": [
                    {"key": "parent_cell_line", "label": "Parent", "type": "str"},
                ],
            },
            today=ALIAS_COMPAT_END_DATE,
        )
        assert result["ok"] is True
        assert result["fields"]["parent_cell_line"] == "K562"
        assert "cell_line" not in result["fields"]
        assert result.get("alias_hits") == []

    def test_maps_alias_to_canonical_before_cutoff(self):
        result = normalize_input_fields(
            {"parent_cell_line": "K562", "short_name": "clone-a"},
            {},
            today=ALIAS_COMPAT_END_DATE,
        )
        assert result["ok"] is True
        assert result["fields"]["cell_line"] == "K562"
        assert "parent_cell_line" not in result["fields"]
        assert len(result.get("warnings") or []) == 1
        assert (result.get("alias_hits") or [])[0]["behavior"] == "mapped"

    def test_preserves_canonical_when_alias_conflicts_before_cutoff(self):
        result = normalize_input_fields(
            {"cell_line": "HeLa", "parent_cell_line": "K562"},
            {},
            today=ALIAS_COMPAT_END_DATE - timedelta(days=1),
        )
        assert result["ok"] is True
        assert result["fields"]["cell_line"] == "HeLa"
        assert "parent_cell_line" not in result["fields"]
        assert (result.get("alias_hits") or [])[0]["behavior"] == "ignored"

    def test_rejects_alias_after_cutoff(self):
        result = normalize_input_fields(
            {"parent_cell_line": "K562"},
            {},
            today=ALIAS_COMPAT_END_DATE + timedelta(days=1),
        )
        assert result["ok"] is False
        assert result.get("error_code") == "deprecated_field_alias_removed"
        assert "support ended" in (result.get("message") or "").lower()


class TestRecordFieldSplit:
    def test_migrate_record_aliases_maps_and_counts_conflicts(self):
        rec = {
            "id": 1,
            "parent_cell_line": "K562",
            "cell_line": "HeLa",
        }
        migrated = migrate_record_aliases(rec, {})
        assert migrated["changed"] is True
        assert migrated["conflicts"] == 1
        assert rec["cell_line"] == "HeLa"
        assert "parent_cell_line" not in rec

    def test_split_record_fields_emits_schema_and_legacy(self):
        meta = {
            "custom_fields": [
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
                {"key": "short_name", "label": "Short Name", "type": "str"},
                {"key": "plasmid_name", "label": "Plasmid Name", "type": "str"},
            ],
        }
        rec = {
            "id": 8,
            "box": 1,
            "position": 3,
            "frozen_at": "2026-02-10",
            "parent_cell_line": "K562",
            "short_name": "clone-8",
            "note": "seed",
            "plasmid_name": "pDemo",
            "plasmid_id": "PID-8",
        }

        split = split_record_fields(rec, meta)
        assert split["fields"]["cell_line"] == "K562"
        assert split["fields"]["short_name"] == "clone-8"
        assert split["fields"]["note"] == "seed"
        assert split["fields"]["plasmid_name"] == "pDemo"
        assert "parent_cell_line" not in split["legacy_fields"]
        assert split["legacy_fields"]["plasmid_id"] == "PID-8"

    def test_ordered_field_items_respects_schema_order_then_remaining(self):
        items = ordered_field_items(
            {"plasmid_id": "p1", "short_name": "A", "cell_line": "K562"},
            field_order=["cell_line", "short_name"],
        )
        assert items == [
            ("cell_line", "K562"),
            ("short_name", "A"),
            ("plasmid_id", "p1"),
        ]
