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
                self.assertIn("templates/prompt_cn.md", names)
                self.assertIn("examples/valid_inventory_min.yaml", names)
                self.assertIn("output/README.md", names)
                self.assertIn("inputs/records.txt", names)

                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                self.assertEqual("output/ln2_inventory.yaml", manifest.get("required_output_path"))
                self.assertEqual(1, manifest.get("source_count"))

    def test_build_bundle_rejects_empty_sources(self):
        with tempfile.TemporaryDirectory() as td:
            out_zip = os.path.join(td, "empty.zip")
            result = build_import_task_bundle([], out_zip)
            self.assertFalse(result.get("ok"))
            self.assertEqual("empty_sources", result.get("error_code"))


if __name__ == "__main__":
    unittest.main()
