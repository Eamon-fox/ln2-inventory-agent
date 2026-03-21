"""Unit tests for settings validation application use case."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import SettingsValidationUseCase


class SettingsValidationUseCaseTests(unittest.TestCase):
    def test_validate_yaml_for_settings_accept_uses_strict_validation_on_path_change(self):
        use_case = SettingsValidationUseCase()

        with patch(
            "app_gui.application.settings_validation_use_case.validate_candidate_yaml",
            return_value={"ok": False, "error_code": "validation_failed", "message": "strict failed"},
        ) as strict_mock, patch(
            "app_gui.application.settings_validation_use_case.validate_yaml_file",
        ) as meta_mock:
            result = use_case.validate_yaml_for_settings_accept(
                yaml_path="D:/inventories/new.yaml",
                initial_yaml_path="D:/inventories/original.yaml",
            )

        strict_mock.assert_called_once_with("D:/inventories/new.yaml", fail_on_warnings=True)
        meta_mock.assert_not_called()
        self.assertEqual("strict failed", result.get("message"))

    def test_validate_yaml_for_settings_accept_uses_meta_only_when_path_unchanged(self):
        use_case = SettingsValidationUseCase()

        with patch(
            "app_gui.application.settings_validation_use_case.validate_yaml_file",
            return_value={"ok": True},
        ) as meta_mock, patch(
            "app_gui.application.settings_validation_use_case.validate_candidate_yaml",
        ) as strict_mock:
            result = use_case.validate_yaml_for_settings_accept(
                yaml_path="D:/inventories/current.yaml",
                initial_yaml_path="D:/inventories/current.yaml",
            )

        meta_mock.assert_called_once_with(
            "D:/inventories/current.yaml",
            mode="meta_only",
        )
        strict_mock.assert_not_called()
        self.assertEqual({"ok": True}, result)

    def test_validate_yaml_meta_only_rewrites_validation_prefix(self):
        use_case = SettingsValidationUseCase()

        with patch(
            "app_gui.application.settings_validation_use_case.validate_yaml_file",
            return_value={
                "ok": False,
                "error_code": "validation_failed",
                "report": {
                    "errors": ["meta.color_key is invalid"],
                    "warnings": ["warn-1"],
                },
            },
        ):
            result = use_case.validate_yaml_meta_only(yaml_path="D:/inventories/current.yaml")

        self.assertFalse(result.get("ok"))
        self.assertEqual("validation_failed", result.get("error_code"))
        self.assertTrue(str(result.get("message") or "").startswith("Validation failed"))
        report = result.get("report") or {}
        self.assertEqual(["meta.color_key is invalid"], report.get("errors"))
        self.assertEqual(["warn-1"], report.get("warnings"))


if __name__ == "__main__":
    unittest.main()
