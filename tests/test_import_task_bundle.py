import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.import_task_bundle import build_import_task_bundle


class ImportTaskBundleTests(unittest.TestCase):
    def test_build_bundle_includes_required_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_zip = Path(td) / "task_bundle.zip"
            result = build_import_task_bundle([str(src_file)], str(out_zip))

            self.assertTrue(result.get("ok"), result)
            self.assertTrue(out_zip.is_file())

            with zipfile.ZipFile(str(out_zip), "r") as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("schema/ln2_import_schema.json", names)
                self.assertIn("schema/validation_rules.md", names)
                self.assertIn("templates/prompt_en.md", names)
                self.assertIn("templates/runbook_en.md", names)
                self.assertIn("templates/acceptance_checklist_en.md", names)
                self.assertNotIn("templates/prompt_cn.md", names)
                self.assertIn("examples/valid_inventory_min.yaml", names)
                self.assertIn("output/README.md", names)
                self.assertIn("inputs/records.txt", names)

                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertEqual("output/ln2_inventory.yaml", manifest.get("required_output_path"))
                self.assertEqual(1, manifest.get("source_count"))
                self.assertEqual("1.1", manifest.get("bundle_version"))

    def test_prompt_en_contains_hard_constraints(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_zip = Path(td) / "task_bundle.zip"
            result = build_import_task_bundle([str(src_file)], str(out_zip))

            self.assertTrue(result.get("ok"), result)
            with zipfile.ZipFile(str(out_zip), "r") as archive:
                prompt = archive.read("templates/prompt_en.md").decode("utf-8")
                prompt_lower = prompt.lower()
                self.assertIn("manifest.json", prompt)
                self.assertIn("source_files", prompt)
                self.assertIn("output/ln2_inventory.yaml", prompt)
                self.assertIn("do not invent", prompt_lower)

    def test_runbook_en_contains_mandatory_phase_order(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_zip = Path(td) / "task_bundle.zip"
            result = build_import_task_bundle([str(src_file)], str(out_zip))

            self.assertTrue(result.get("ok"), result)
            with zipfile.ZipFile(str(out_zip), "r") as archive:
                runbook = archive.read("templates/runbook_en.md").decode("utf-8")
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

    def test_acceptance_checklist_en_contains_blocking_checks(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_zip = Path(td) / "task_bundle.zip"
            result = build_import_task_bundle([str(src_file)], str(out_zip))

            self.assertTrue(result.get("ok"), result)
            with zipfile.ZipFile(str(out_zip), "r") as archive:
                checklist = archive.read("templates/acceptance_checklist_en.md").decode("utf-8")
                self.assertIn("output/ln2_inventory.yaml", checklist)
                self.assertIn("Top-level keys are exactly `meta` and `inventory`", checklist)
                self.assertIn("Active tubes do not conflict on `(box, position)`", checklist)
                self.assertIn("`meta.custom_fields`, if present, uses structured objects", checklist)

    def test_manifest_bundle_version_bumped(self):
        with tempfile.TemporaryDirectory() as td:
            src_file = Path(td) / "records.txt"
            src_file.write_text("id,box,position\n1,1,1\n", encoding="utf-8")

            out_zip = Path(td) / "task_bundle.zip"
            result = build_import_task_bundle([str(src_file)], str(out_zip))

            self.assertTrue(result.get("ok"), result)
            with zipfile.ZipFile(str(out_zip), "r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertEqual("1.1", manifest.get("bundle_version"))

    def test_build_bundle_rejects_empty_sources(self):
        with tempfile.TemporaryDirectory() as td:
            out_zip = os.path.join(td, "empty.zip")
            result = build_import_task_bundle([], out_zip)
            self.assertFalse(result.get("ok"))
            self.assertEqual("empty_sources", result.get("error_code"))


if __name__ == "__main__":
    unittest.main()
