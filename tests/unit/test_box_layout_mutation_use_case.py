import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app_gui.application.box_layout_mutation_use_case import BoxLayoutMutationUseCase


class BoxLayoutMutationUseCaseTests(unittest.TestCase):
    def test_prepare_request_normalizes_remove_alias_and_keeps_payload_shape(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_layout_use_case_") as tmpdir:
            yaml_path = os.path.join(tmpdir, "inventory.yaml")
            Path(yaml_path).write_text("meta: {}\ninventory: []\n", encoding="utf-8")

            use_case = BoxLayoutMutationUseCase(
                bridge=SimpleNamespace(),
                current_yaml_path_getter=lambda: yaml_path,
            )

            prepared = use_case.prepare_request(
                {"operation": "remove_box", "box": 2, "renumber_mode": "compact"}
            )

            self.assertEqual(yaml_path, prepared["yaml_path"])
            self.assertEqual("remove", prepared["op"])
            self.assertEqual(
                {"operation": "remove", "box": 2, "renumber_mode": "compact"},
                prepared["payload"],
            )

    def test_preflight_routes_write_request_through_bridge_dry_run(self):
        bridge = SimpleNamespace(
            manage_boxes=lambda **kwargs: {"ok": True, "kwargs": kwargs}
        )
        use_case = BoxLayoutMutationUseCase(
            bridge=bridge,
            current_yaml_path_getter=lambda: "D:/inventories/current/inventory.yaml",
        )

        response = use_case.preflight(
            {
                "yaml_path": "D:/inventories/current/inventory.yaml",
                "op": "add",
                "payload": {"operation": "add", "count": 2},
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            {
                "yaml_path": "D:/inventories/current/inventory.yaml",
                "dry_run": True,
                "operation": "add",
                "count": 2,
            },
            response["kwargs"],
        )

    def test_load_box_numbers_for_presentation_reads_current_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_box_layout_present_") as tmpdir:
            yaml_path = os.path.join(tmpdir, "inventory.yaml")
            Path(yaml_path).write_text(
                (
                    "meta:\n"
                    "  box_layout:\n"
                    "    rows: 9\n"
                    "    cols: 9\n"
                    "    box_count: 3\n"
                    "    box_numbers: [1, 3, 5]\n"
                    "inventory: []\n"
                ),
                encoding="utf-8",
            )
            use_case = BoxLayoutMutationUseCase(
                bridge=SimpleNamespace(),
                current_yaml_path_getter=lambda: yaml_path,
            )

            box_numbers = use_case.load_box_numbers_for_presentation(yaml_path)

            self.assertEqual([1, 3, 5], box_numbers)


if __name__ == "__main__":
    unittest.main()
