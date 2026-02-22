import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.import_task_bundle import export_import_task_bundle


class ImportTaskBundleTests(unittest.TestCase):
    def test_build_bundle_includes_required_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            self.assertTrue(out_dir.is_dir())
            self.assertEqual(str(out_dir.resolve()), result.get("bundle_dir"))

            self.assertTrue((out_dir / "manifest.json").is_file())
            self.assertTrue((out_dir / "schema" / "ln2_import_schema.json").is_file())
            self.assertTrue((out_dir / "schema" / "validation_rules.md").is_file())
            self.assertTrue((out_dir / "templates" / "prompt_en.md").is_file())
            self.assertTrue((out_dir / "templates" / "runbook_en.md").is_file())
            self.assertTrue((out_dir / "templates" / "acceptance_checklist_en.md").is_file())
            self.assertFalse((out_dir / "templates" / "prompt_cn.md").exists())
            self.assertTrue((out_dir / "examples" / "valid_inventory_min.yaml").is_file())
            self.assertTrue((out_dir / "examples" / "valid_inventory_full.yaml").is_file())
            self.assertTrue((out_dir / "output" / "README.md").is_file())
            self.assertTrue((out_dir / "inputs" / "records.txt").is_file())

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("output/ln2_inventory.yaml", manifest.get("required_output_path"))
            self.assertEqual(1, manifest.get("source_count"))
            self.assertEqual("1.1", manifest.get("bundle_version"))

    def test_prompt_en_contains_hard_constraints(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            prompt = (out_dir / "templates" / "prompt_en.md").read_text(encoding="utf-8")
            prompt_lower = prompt.lower()
            self.assertIn("manifest.json", prompt)
            self.assertIn("source_files", prompt)
            self.assertIn("output/ln2_inventory.yaml", prompt)
            self.assertIn("do not invent", prompt_lower)

    def test_runbook_en_contains_mandatory_phase_order(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            runbook = (out_dir / "templates" / "runbook_en.md").read_text(encoding="utf-8")
            phases = [
                "## Phase 1 - Read task context",
                "## Phase 2 - Inspect source structure",
                "## Phase 3 - Design field mapping",
                "## Phase 4 - Transform data",
                "## Phase 5 - Validate draft output",
                "## Phase 6 - Finalize delivery",
            ]
            offsets = [runbook.find(phase) for phase in phases]
            self.assertTrue(all(offset >= 0 for offset in offsets), offsets)
            self.assertEqual(offsets, sorted(offsets))
            self.assertIn("required-field coverage (`box`, `position`, `frozen_at`, `cell_line`)", runbook)
            self.assertIn("duplicate active locations on `(box, position)`", runbook)
            self.assertIn("date parseability and future-date risks", runbook)
            self.assertIn("custom-field metadata shape (`meta.custom_fields` entries use `key` + `type`)", runbook)

    def test_acceptance_checklist_en_contains_blocking_checks(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            checklist = (out_dir / "templates" / "acceptance_checklist_en.md").read_text(encoding="utf-8")
            self.assertIn("output/ln2_inventory.yaml", checklist)
            self.assertIn("Top-level keys are exactly `meta` and `inventory`", checklist)
            self.assertIn("Active tubes do not conflict on `(box, position)`", checklist)
            self.assertIn("Every inventory record has non-empty `cell_line`", checklist)
            self.assertIn("`meta.custom_fields`, if present, uses structured objects with `key` + `type`", checklist)

    def test_validation_rules_include_split_and_excel_date_guidance(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            rules = (out_dir / "schema" / "validation_rules.md").read_text(encoding="utf-8")
            self.assertIn("contains multiple positions", rules)
            self.assertIn("split it into multiple tube-level records", rules)
            self.assertIn("Excel serial number", rules)
            self.assertIn("include non-empty `cell_line`", rules)
            self.assertIn("structured object with `key`", rules)
            self.assertIn("examples/valid_inventory_full.yaml", rules)

    def test_full_example_custom_fields_use_key_type_contract(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            payload = yaml.safe_load((out_dir / "examples" / "valid_inventory_full.yaml").read_text(encoding="utf-8"))
            custom_fields = payload.get("meta", {}).get("custom_fields", [])
            self.assertTrue(custom_fields)
            self.assertTrue(all("key" in item and "type" in item for item in custom_fields))
            self.assertTrue(all("name" not in item for item in custom_fields))
            inventory = payload.get("inventory", [])
            self.assertTrue(inventory)
            self.assertTrue(all(str(rec.get("cell_line") or "").strip() for rec in inventory))

    def test_manifest_bundle_version_bumped(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_dir = Path(td) / "task_bundle"
            result = export_import_task_bundle([str(src_file)], str(out_dir))

            self.assertTrue(result.get("ok"), result)
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("1.1", manifest.get("bundle_version"))

    def test_build_bundle_rejects_empty_sources(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = os.path.join(td, "empty")
            result = export_import_task_bundle([], out_dir)
            self.assertFalse(result.get("ok"))
            self.assertEqual("empty_sources", result.get("error_code"))


if __name__ == "__main__":
    unittest.main()
