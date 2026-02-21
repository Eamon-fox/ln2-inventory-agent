import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.import_acceptance import import_validated_yaml, validate_candidate_yaml


def _valid_payload():
    return {
        "meta": {
            "box_layout": {"rows": 9, "cols": 9},
            "custom_fields": [],
        },
        "inventory": [
            {
                "id": 1,
                "box": 1,
                "position": 1,
                "frozen_at": "2025-01-01",
                "cell_line": "K562",
                "note": None,
                "thaw_events": None,
            }
        ],
    }


class ImportAcceptanceTests(unittest.TestCase):
    def test_validate_candidate_yaml_ok(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(0, (result.get("report") or {}).get("error_count"))

    def test_validate_candidate_yaml_rejects_extra_root_keys(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            payload["unexpected"] = {"x": 1}
            candidate = Path(td) / "bad.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate))
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            errors = (result.get("report") or {}).get("errors") or []
            self.assertTrue(any("Unsupported top-level key" in msg for msg in errors))

    def test_import_validated_yaml_writes_target(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            target = Path(td) / "imported.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            result = import_validated_yaml(str(candidate), str(target))
            self.assertTrue(result.get("ok"), result)
            self.assertTrue(target.exists())

    def test_import_validated_yaml_honors_overwrite_flag(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "candidate.yaml"
            target = Path(td) / "existing.yaml"
            candidate.write_text(
                yaml.safe_dump(_valid_payload(), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            target.write_text("meta: {}\ninventory: []\n", encoding="utf-8")

            blocked = import_validated_yaml(str(candidate), str(target))
            self.assertFalse(blocked.get("ok"))
            self.assertEqual("target_exists", blocked.get("error_code"))

            allowed = import_validated_yaml(str(candidate), str(target), overwrite=True)
            self.assertTrue(allowed.get("ok"), allowed)

    def test_validate_candidate_yaml_blocks_warnings_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            payload = _valid_payload()
            # Missing cell_line triggers legacy-compatible warning in validators.
            payload["inventory"][0].pop("cell_line", None)
            candidate = Path(td) / "warn.yaml"
            candidate.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            result = validate_candidate_yaml(str(candidate), fail_on_warnings=True)
            self.assertFalse(result.get("ok"))
            self.assertEqual("validation_failed", result.get("error_code"))
            report = result.get("report") or {}
            self.assertGreater((report.get("warning_count") or 0), 0)


if __name__ == "__main__":
    unittest.main()
