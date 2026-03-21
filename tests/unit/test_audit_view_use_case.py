import unittest
from unittest.mock import patch

from app_gui.application.audit_view_use_case import AuditViewUseCase


class AuditViewUseCaseTests(unittest.TestCase):
    def test_load_field_order_returns_effective_field_order(self):
        use_case = AuditViewUseCase()
        with patch(
            "app_gui.application.audit_view_use_case.load_yaml",
            return_value={
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [
                        {"key": "sample_type", "label": "Sample Type", "type": "str"},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "sample_type": "PBMC",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ],
            },
        ):
            field_order = use_case.load_field_order(yaml_path="D:/tmp/inventory.yaml")

        self.assertIn("note", field_order)
        self.assertIn("sample_type", field_order)

    def test_load_field_order_handles_load_failures(self):
        use_case = AuditViewUseCase()

        with patch(
            "app_gui.application.audit_view_use_case.load_yaml",
            side_effect=RuntimeError("boom"),
        ):
            field_order = use_case.load_field_order(yaml_path="D:/tmp/inventory.yaml")

        self.assertIn("note", field_order)
        self.assertNotIn("sample_type", field_order)


if __name__ == "__main__":
    unittest.main()
