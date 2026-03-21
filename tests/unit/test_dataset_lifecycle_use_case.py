"""Unit tests for managed dataset lifecycle orchestration."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import DatasetLifecycleUseCase


def _assert_existing_if_needed(path, must_exist=False):
    normalized = os.path.abspath(str(path or ""))
    if must_exist and not os.path.isfile(normalized):
        raise ValueError(normalized)
    return normalized


class DatasetLifecycleUseCaseTests(unittest.TestCase):
    def test_create_dataset_writes_canonical_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "demo", "inventory.yaml")
            use_case = DatasetLifecycleUseCase(
                assert_allowed_path=_assert_existing_if_needed,
            )

            result = use_case.create_dataset(
                target_path=target,
                box_layout={"box_1": {"rows": 9, "cols": 9}},
                custom_fields=[
                    {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
                    {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                ],
                display_key="short_name",
                color_key="cell_line",
            )

            self.assertEqual(os.path.abspath(target), result.target_path)
            payload = yaml.safe_load(Path(target).read_text(encoding="utf-8"))
            self.assertEqual([], payload["inventory"])
            self.assertEqual({"box_1": {"rows": 9, "cols": 9}}, payload["meta"]["box_layout"])
            self.assertEqual("short_name", payload["meta"]["display_key"])
            self.assertEqual("cell_line", payload["meta"]["color_key"])
            self.assertEqual(
                [
                    {"key": "short_name", "label": "Short Name", "type": "str", "required": False},
                    {"key": "cell_line", "label": "Cell Line", "type": "str", "required": True},
                ],
                payload["meta"]["custom_fields"],
            )

    def test_resolve_startup_yaml_path_creates_default_dataset_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_yaml = os.path.join(tmpdir, "inventory", "inventory.yaml")
            create_path_calls = []
            ensure_root_calls = []
            use_case = DatasetLifecycleUseCase(
                ensure_inventories_root_fn=lambda: ensure_root_calls.append(True),
                latest_inventory_yaml_path_fn=lambda: "",
                create_dataset_yaml_path_fn=lambda name: create_path_calls.append(name) or default_yaml,
                assert_allowed_path=_assert_existing_if_needed,
            )

            resolved = use_case.resolve_startup_yaml_path(configured_yaml_path="")

            self.assertEqual(os.path.abspath(default_yaml), resolved)
            self.assertEqual(["inventory"], create_path_calls)
            self.assertEqual([True], ensure_root_calls)
            payload = yaml.safe_load(Path(default_yaml).read_text(encoding="utf-8"))
            self.assertEqual(use_case.default_inventory_payload(), payload)

    def test_rename_dataset_returns_audit_warning_without_failing_switch(self):
        appended = []
        old_yaml = os.path.abspath("D:/inventories/old/inventory.yaml")
        new_yaml = os.path.abspath("D:/inventories/new/inventory.yaml")

        def _append_audit_event(**kwargs):
            appended.append(kwargs)
            raise RuntimeError("audit failed")

        use_case = DatasetLifecycleUseCase(
            normalize_yaml_path=lambda value: os.path.abspath(str(value or "")),
            rename_dataset_yaml_path_fn=lambda source_yaml, dataset_name: new_yaml,
            build_dataset_rename_payload_fn=lambda source_yaml, target_yaml: {
                "source_yaml": source_yaml,
                "target_yaml": target_yaml,
            },
            load_yaml_fn=lambda yaml_path: {"meta": {}, "inventory": []},
            append_audit_event_fn=_append_audit_event,
        )

        result = use_case.rename_dataset(
            current_yaml_path=old_yaml,
            new_dataset_name="new",
        )

        self.assertEqual(new_yaml, result.target_path)
        self.assertEqual("audit failed", result.audit_error)
        self.assertEqual(new_yaml, appended[0]["yaml_path"])
        self.assertEqual({"meta": {}, "inventory": []}, appended[0]["before_data"])
        self.assertEqual({"meta": {}, "inventory": []}, appended[0]["after_data"])
        self.assertEqual("dataset_rename", appended[0]["audit_meta"]["action"])

    def test_delete_dataset_creates_fallback_dataset_when_none_remain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deleted_yaml = os.path.join(tmpdir, "old", "inventory.yaml")
            fallback_yaml = os.path.join(tmpdir, "inventory", "inventory.yaml")
            appended = []
            use_case = DatasetLifecycleUseCase(
                normalize_yaml_path=lambda value: os.path.abspath(str(value or "")),
                assert_allowed_path=_assert_existing_if_needed,
                delete_dataset_yaml_path_fn=lambda source_yaml: {"yaml_path": source_yaml},
                list_managed_datasets_fn=lambda: [],
                create_dataset_yaml_path_fn=lambda dataset_name: fallback_yaml,
                build_dataset_delete_payload_fn=lambda removed_yaml, target_yaml: {
                    "removed_yaml": removed_yaml,
                    "target_yaml": target_yaml,
                },
                load_yaml_fn=lambda yaml_path: yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8")),
                append_audit_event_fn=lambda **kwargs: appended.append(kwargs),
            )

            result = use_case.delete_dataset(current_yaml_path=deleted_yaml)

            self.assertEqual(os.path.abspath(fallback_yaml), result.target_path)
            self.assertEqual(os.path.abspath(deleted_yaml), result.deleted_yaml_path)
            self.assertTrue(result.fallback_created)
            self.assertIsNone(result.audit_error)
            self.assertTrue(os.path.isfile(fallback_yaml))
            payload = yaml.safe_load(Path(fallback_yaml).read_text(encoding="utf-8"))
            self.assertEqual(use_case.default_inventory_payload(), payload)
            self.assertEqual(os.path.abspath(fallback_yaml), appended[0]["yaml_path"])
            self.assertEqual("dataset_delete", appended[0]["audit_meta"]["action"])


if __name__ == "__main__":
    unittest.main()
