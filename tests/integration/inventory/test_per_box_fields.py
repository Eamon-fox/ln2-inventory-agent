"""Integration tests for per-box custom field schemas.

Verifies that add_entry, edit_entry, and validation respect
box-level field overrides defined in ``meta.box_fields``.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    tool_add_entry,
    tool_edit_entry,
    tool_search_records,
)
from lib.validators import validate_inventory
from lib.yaml_ops import load_yaml, write_yaml
from tests.managed_paths import ManagedPathTestCase


def _make_meta(global_fields=None, box_fields=None):
    meta = {"box_layout": {"rows": 9, "cols": 9}}
    if global_fields is not None:
        meta["custom_fields"] = global_fields
    if box_fields is not None:
        meta["box_fields"] = box_fields
    return meta


def _make_record(rec_id=1, box=1, position=1, **extra):
    rec = {
        "id": rec_id,
        "box": box,
        "position": position,
        "frozen_at": "2025-01-01",
    }
    rec.update(extra)
    return rec


def _make_data(records, global_fields=None, box_fields=None):
    return {
        "meta": _make_meta(global_fields, box_fields),
        "inventory": records,
    }


class TestAddEntryPerBoxFields(ManagedPathTestCase):
    """Per-box field schema is enforced during add_entry."""

    def test_add_uses_box_specific_fields(self):
        """Adding to box 2 should use box 2's field schema."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_add_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [_make_record(1, box=1, position=1, cell_line="K562")],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                            {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=2,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "HeLa", "virus_titer": "MOI10"},
                source="test_per_box",
            )

            self.assertTrue(result["ok"], result.get("message"))
            data = load_yaml(str(yaml_path))
            new_rec = data["inventory"][-1]
            self.assertEqual("HeLa", new_rec["cell_line"])
            self.assertEqual("MOI10", new_rec["virus_titer"])

    def test_add_rejects_box2_field_on_box1(self):
        """Fields defined only for box 2 should be rejected when adding to box 1."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_reject_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                            {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "K562", "virus_titer": "MOI10"},
                source="test_per_box",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("forbidden_fields", result.get("error_code"))

    def test_add_box_without_override_uses_global(self):
        """Box 1 has no override, so it should use global fields."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_global_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        {"key": "passage_number", "label": "P#", "type": "int"},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "K562", "passage_number": 5},
                source="test_per_box",
            )

            self.assertTrue(result["ok"], result.get("message"))
            data = load_yaml(str(yaml_path))
            new_rec = data["inventory"][-1]
            self.assertEqual(5, new_rec["passage_number"])

    def test_add_enforces_per_box_required_fields(self):
        """Per-box required fields should be enforced."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_req_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    ],
                    box_fields={
                        "1": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                            {"key": "sample_type", "label": "Sample Type", "type": "str", "required": True},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            # Missing required sample_type
            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "K562"},
                source="test_per_box",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("missing_required_fields", result.get("error_code"))

    def test_add_enforces_per_box_options(self):
        """Per-box option constraints should be enforced."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_opts_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str",
                         "options": ["K562", "HeLa"]},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str",
                             "options": ["A549", "MCF7"]},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            # K562 is valid for box 1 but not box 2
            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=2,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "K562"},
                source="test_per_box",
            )

            self.assertFalse(result["ok"])
            self.assertIn(result.get("error_code"), ("invalid_cell_line", "invalid_field_options"))


class TestEditEntryPerBoxFields(ManagedPathTestCase):
    """Per-box field schema is enforced during edit_entry."""

    def test_edit_uses_record_box_fields(self):
        """Editing a record in box 2 should use box 2's field schema."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_edit_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [
                        _make_record(1, box=2, position=1, cell_line="HeLa", virus_titer="MOI5"),
                    ],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                            {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"virus_titer": "MOI20"},
                source="test_per_box",
            )

            self.assertTrue(result["ok"], result.get("message"))
            data = load_yaml(str(yaml_path))
            self.assertEqual("MOI20", data["inventory"][0]["virus_titer"])

    def test_edit_rejects_field_not_in_box_schema(self):
        """Editing a field not in the record's box schema should fail."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_edit_bad_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [
                        _make_record(1, box=1, position=1, cell_line="K562"),
                    ],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    ],
                    box_fields={
                        "2": [
                            {"key": "cell_line", "label": "Cell Line", "type": "str"},
                            {"key": "virus_titer", "label": "Virus Titer", "type": "str"},
                        ],
                    },
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            # virus_titer is only defined for box 2, record is in box 1
            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"virus_titer": "MOI10"},
                source="test_per_box",
            )

            self.assertFalse(result["ok"])
            self.assertIn("error_code", result)


class TestValidationPerBoxFields(ManagedPathTestCase):
    """validate_inventory respects per-box field schemas."""

    def test_validates_with_per_box_required_field_present(self):
        data = _make_data(
            [
                _make_record(1, box=1, position=1, cell_line="K562"),
                _make_record(2, box=2, position=1, cell_line="HeLa", virus_titer="MOI5"),
            ],
            global_fields=[
                {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
            ],
            box_fields={
                "2": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                    {"key": "virus_titer", "label": "Virus Titer", "type": "str", "required": True},
                ],
            },
        )

        errors, warnings = validate_inventory(data)
        self.assertEqual([], errors)

    def test_validation_warns_missing_per_box_required_field(self):
        """Missing required per-box field should produce a warning (legacy-compatible)."""
        data = _make_data(
            [
                _make_record(1, box=2, position=1, cell_line="HeLa"),
                # virus_titer is missing but required for box 2
            ],
            global_fields=[
                {"key": "cell_line", "label": "Cell Line", "type": "str"},
            ],
            box_fields={
                "2": [
                    {"key": "cell_line", "label": "Cell Line", "type": "str"},
                    {"key": "virus_titer", "label": "Virus Titer", "type": "str", "required": True},
                ],
            },
        )

        errors, warnings = validate_inventory(data)
        # Required non-option fields produce errors; but virus_titer has no
        # value at all so we check for either error or that validation ran
        # correctly with per-box resolution.
        # The key assertion is that box 2's schema was used.
        has_virus_titer_mention = any(
            "virus_titer" in msg for msg in (errors + warnings)
        )
        self.assertTrue(has_virus_titer_mention,
                        f"Expected virus_titer in errors/warnings, got: {errors + warnings}")


class TestPerBoxFieldsFallback(ManagedPathTestCase):
    """Backward compatibility: no box_fields means global-only behavior."""

    def test_no_box_fields_works_normally(self):
        """Without box_fields, everything should work as before."""
        with tempfile.TemporaryDirectory(prefix="ln2_pbf_compat_") as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                _make_data(
                    [],
                    global_fields=[
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        {"key": "passage_number", "label": "P#", "type": "int"},
                    ],
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[1],
                frozen_at="2026-03-01",
                fields={"cell_line": "K562", "passage_number": 3},
                source="test_compat",
            )

            self.assertTrue(result["ok"], result.get("message"))


if __name__ == "__main__":
    unittest.main()
