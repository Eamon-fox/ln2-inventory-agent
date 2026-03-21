"""
Module: test_tool_contracts_single_source
Layer: contract
Covers: lib/tool_api.py, app_gui/tool_bridge.py, agent/tool_runner.py

工具契约单一来源执行检查，验证 Agent、GUI 和 Tool API
使用相同的契约定义，包括工具参数、必填字段和写操作分类。
"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import tool_runner
from agent.tool_runtime_registry import build_tool_runtime_specs, expected_runtime_tool_names
from app_gui.tool_bridge import GuiToolBridge
from lib.tool_registry import (
    MIGRATION_TOOL_NAMES,
    TOOL_CONTRACTS,
    VALID_PLAN_ACTIONS,
    WRITE_TOOL_TO_PLAN_ACTION,
    WRITE_TOOLS,
    get_tool_descriptor,
    get_tool_contracts,
    iter_agent_dispatch_descriptors,
    iter_gui_bridge_descriptors,
    iter_tool_descriptors,
    iter_write_tool_descriptors,
    resolve_tool_api_callable,
)


class ToolContractsSingleSourceTests(unittest.TestCase):
    def test_registry_drives_tool_contract_surface(self):
        self.assertEqual(
            [descriptor.name for descriptor in iter_tool_descriptors()],
            list(TOOL_CONTRACTS.keys()),
        )

    def test_non_contract_registry_entries_do_not_leak_into_tool_contracts(self):
        hidden_names = {
            "export_inventory_csv",
            "collect_timeline",
            "set_box_tag",
            "set_box_layout_indexing",
            "batch_add_entries",
        }
        for name in hidden_names:
            with self.subTest(tool=name):
                self.assertIsNotNone(get_tool_descriptor(name))
                self.assertNotIn(name, TOOL_CONTRACTS)

    def test_agent_uses_canonical_tool_contracts(self):
        self.assertIs(tool_runner._TOOL_CONTRACTS, TOOL_CONTRACTS)

    def test_agent_uses_canonical_write_tools(self):
        self.assertIs(tool_runner._WRITE_TOOLS, WRITE_TOOLS)

    def test_write_tools_derived_from_contracts(self):
        """WRITE_TOOLS must match exactly the set of tools with _write flag."""
        expected = frozenset(
            name for name, spec in TOOL_CONTRACTS.items() if spec.get("_write")
        )
        self.assertEqual(WRITE_TOOLS, expected)
        # Verify known members
        self.assertEqual(
            WRITE_TOOLS,
            frozenset({"add_entry", "edit_entry", "takeout", "move", "rollback"}),
        )

    def test_migration_tools_derived_from_contracts(self):
        """MIGRATION_TOOL_NAMES must match exactly the set of tools with _migration flag."""
        expected = frozenset(
            name for name, spec in TOOL_CONTRACTS.items() if spec.get("_migration")
        )
        self.assertEqual(MIGRATION_TOOL_NAMES, expected)
        # Verify known members
        for name in ("question", "use_skill", "bash", "powershell", "fs_list", "fs_read",
                      "fs_write", "fs_copy", "fs_edit", "validate",
                      "import_migration_output"):
            self.assertIn(name, MIGRATION_TOOL_NAMES)

    def test_valid_plan_actions_derived_from_write_tool_map(self):
        """VALID_PLAN_ACTIONS covers all write tools via WRITE_TOOL_TO_PLAN_ACTION."""
        self.assertEqual(set(WRITE_TOOL_TO_PLAN_ACTION.keys()), set(WRITE_TOOLS))
        self.assertEqual(VALID_PLAN_ACTIONS, frozenset(WRITE_TOOL_TO_PLAN_ACTION.values()))

    def test_plan_model_uses_canonical_valid_actions(self):
        """plan_model_sheet._VALID_ACTIONS should reference contracts."""
        from app_gui.plan_model_sheet import _VALID_ACTIONS
        self.assertIs(_VALID_ACTIONS, VALID_PLAN_ACTIONS)

    def test_registry_agent_dispatch_descriptors_resolve_to_runner_methods(self):
        runner_cls = tool_runner.AgentToolRunner
        for descriptor in iter_agent_dispatch_descriptors():
            handler = getattr(runner_cls, descriptor.agent_handler_attr, None)
            self.assertTrue(
                callable(handler),
                f"{descriptor.name} missing runner handler {descriptor.agent_handler_attr}",
            )

    def test_registry_write_descriptors_resolve_to_staging_methods(self):
        runner_cls = tool_runner.AgentToolRunner
        for descriptor in iter_write_tool_descriptors():
            handler = getattr(runner_cls, descriptor.stage_handler_attr, None)
            self.assertTrue(
                callable(handler),
                f"{descriptor.name} missing staging handler {descriptor.stage_handler_attr}",
            )

    def test_registry_gui_bridge_descriptors_expose_methods(self):
        for descriptor in iter_gui_bridge_descriptors():
            bridge_spec = descriptor.gui_bridge
            method = getattr(GuiToolBridge, bridge_spec.method_name, None)
            self.assertTrue(
                callable(method),
                f"{descriptor.name} missing bridge method {bridge_spec.method_name}",
            )

    def test_registry_gui_bridge_descriptors_resolve_tool_api_targets(self):
        for descriptor in iter_gui_bridge_descriptors():
            bridge_spec = descriptor.gui_bridge
            target = resolve_tool_api_callable(bridge_spec.tool_api_attr)
            self.assertTrue(
                callable(target),
                f"{descriptor.name} missing tool_api target {bridge_spec.tool_api_attr}",
            )

    def test_write_capable_descriptors_declare_explicit_write_api_attr(self):
        for name in (
            "add_entry",
            "edit_entry",
            "takeout",
            "move",
            "rollback",
            "batch_add_entries",
            "set_box_tag",
            "set_box_layout_indexing",
            "manage_boxes",
        ):
            with self.subTest(tool=name):
                descriptor = get_tool_descriptor(name)
                self.assertIsNotNone(descriptor)
                write_api_attr = str(descriptor.write_api_attr or "").strip()
                self.assertTrue(write_api_attr, f"{name} missing explicit write_api_attr")
                self.assertTrue(callable(resolve_tool_api_callable(write_api_attr)))

    def test_runtime_specs_cover_all_dispatch_descriptors(self):
        runner = object.__new__(tool_runner.AgentToolRunner)
        runtime_specs = build_tool_runtime_specs(runner)

        self.assertEqual(expected_runtime_tool_names(), frozenset(runtime_specs))
        self.assertNotIn("question", runtime_specs)
        for name in WRITE_TOOLS:
            with self.subTest(tool=name):
                self.assertTrue(callable(runtime_specs[name].stage_builder))

    def test_get_tool_contracts_strips_internal_flags(self):
        """Public API must not expose _write / _migration flags."""
        public = get_tool_contracts()
        for name, spec in public.items():
            self.assertNotIn("_write", spec, f"{name} leaks _write flag")
            self.assertNotIn("_migration", spec, f"{name} leaks _migration flag")

    def test_v2_move_takeout_contract_shapes(self):
        self.assertIn("move", TOOL_CONTRACTS)
        self.assertIn("takeout", TOOL_CONTRACTS)

        takeout_props = TOOL_CONTRACTS["takeout"]["parameters"]["properties"]
        self.assertIn("entries", takeout_props)
        entries_schema = takeout_props["entries"]
        self.assertEqual("array", entries_schema.get("type"))
        entry_props = entries_schema["items"]["properties"]
        self.assertIn("from_box", entry_props)
        self.assertIn("from_position", entry_props)
        self.assertNotIn("to_position", entry_props)
        self.assertNotIn("to_box", entry_props)

        move_props = TOOL_CONTRACTS["move"]["parameters"]["properties"]
        move_entry_props = move_props["entries"]["items"]["properties"]
        self.assertIn("to_position", move_entry_props)
        self.assertIn("to_box", move_entry_props)

    def test_bash_contract_requires_command_and_description(self):
        self.assertIn("bash", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["bash"]["parameters"]
        self.assertEqual(["command", "description"], params.get("required"))
        self.assertEqual(
            {"command", "description", "timeout", "workdir"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))
        self.assertNotIn("bash", WRITE_TOOLS)

    def test_powershell_contract_requires_command_and_description(self):
        self.assertIn("powershell", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["powershell"]["parameters"]
        self.assertEqual(["command", "description"], params.get("required"))
        self.assertEqual(
            {"command", "description", "timeout", "workdir"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))
        self.assertNotIn("powershell", WRITE_TOOLS)

    def test_environment_tool_contracts_exist_with_expected_required_fields(self):
        required_by_tool = {
            "fs_list": [],
            "fs_read": ["path"],
            "fs_write": ["path", "content"],
            "fs_edit": ["filePath", "oldString", "newString"],
        }
        for tool_name, expected_required in required_by_tool.items():
            self.assertIn(tool_name, TOOL_CONTRACTS)
            params = TOOL_CONTRACTS[tool_name]["parameters"]
            self.assertEqual(expected_required, params.get("required"))
            self.assertEqual(False, params.get("additionalProperties"))

    def test_environment_tools_are_not_inventory_write_tools(self):
        for tool_name in ("fs_list", "fs_read", "fs_write", "fs_edit", "bash", "powershell"):
            self.assertNotIn(tool_name, WRITE_TOOLS)

    def test_use_skill_contract_shape(self):
        self.assertIn("use_skill", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["use_skill"]["parameters"]
        self.assertEqual(["skill_name"], params.get("required"))
        self.assertEqual({"skill_name"}, set((params.get("properties") or {}).keys()))
        self.assertEqual(False, params.get("additionalProperties"))
        self.assertNotIn("use_skill", WRITE_TOOLS)

    def test_migration_import_tool_contracts_exist(self):
        self.assertIn("validate", TOOL_CONTRACTS)
        self.assertIn("import_migration_output", TOOL_CONTRACTS)
        validate_desc = str(TOOL_CONTRACTS["validate"].get("description") or "")
        self.assertIn("repository-relative YAML file", validate_desc)
        self.assertIn("does not write side-effect files", validate_desc)

        validate_params = TOOL_CONTRACTS["validate"]["parameters"]
        self.assertEqual(["path"], validate_params.get("required"))
        self.assertEqual({"path"}, set((validate_params.get("properties") or {}).keys()))
        self.assertEqual(False, validate_params.get("additionalProperties"))

        import_params = TOOL_CONTRACTS["import_migration_output"]["parameters"]
        self.assertEqual(
            ["confirmation_token", "target_dataset_name"],
            import_params.get("required"),
        )
        self.assertEqual(
            {"confirmation_token", "target_dataset_name"},
            set((import_params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, import_params.get("additionalProperties"))
        self.assertNotIn("validate", WRITE_TOOLS)
        self.assertNotIn("import_migration_output", WRITE_TOOLS)

    def test_fs_copy_contract_shape(self):
        self.assertIn("fs_copy", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["fs_copy"]["parameters"]
        self.assertEqual(["src", "dst"], params.get("required"))
        self.assertEqual({"src", "dst", "overwrite"}, set((params.get("properties") or {}).keys()))
        self.assertNotIn("python_run", TOOL_CONTRACTS)
        self.assertNotIn("edit", TOOL_CONTRACTS)

    def test_fs_edit_contract_shape(self):
        self.assertIn("fs_edit", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["fs_edit"]["parameters"]
        self.assertEqual(["filePath", "oldString", "newString"], params.get("required"))
        self.assertEqual(
            {"filePath", "oldString", "newString", "replaceAll"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))


class PlanItemTypeTests(unittest.TestCase):
    """Verify PlanItem TypedDict is importable and builders return correct shapes."""

    def test_plan_item_type_importable(self):
        from lib.plan_item_factory import PlanItem, PlanItemPayload
        # TypedDict classes are importable and usable for isinstance-like checks
        self.assertTrue(hasattr(PlanItem, "__annotations__"))
        self.assertTrue(hasattr(PlanItemPayload, "__annotations__"))

    def test_plan_item_required_keys(self):
        from lib.plan_item_factory import PlanItem
        annotations = PlanItem.__annotations__
        for key in ("action", "box", "position", "record_id", "source", "payload"):
            self.assertIn(key, annotations, f"PlanItem missing key: {key}")

    def test_build_add_plan_item_shape(self):
        from lib.plan_item_factory import build_add_plan_item
        item = build_add_plan_item(
            box=1, positions=[5, 6], frozen_at="2025-01-01", fields={"cell_line": "K562"}
        )
        self.assertEqual(item["action"], "add")
        self.assertEqual(item["box"], 1)
        self.assertIsNone(item["record_id"])
        self.assertEqual(item["source"], "human")
        self.assertIn("payload", item)
        self.assertEqual(item["payload"]["positions"], [5, 6])

    def test_build_record_plan_item_shape(self):
        from lib.plan_item_factory import build_record_plan_item
        item = build_record_plan_item(
            action="takeout", record_id=42, position=5, box=1, date_str="2025-01-01"
        )
        self.assertEqual(item["action"], "takeout")
        self.assertEqual(item["record_id"], 42)
        self.assertNotIn("to_position", item)

    def test_build_move_plan_item_shape(self):
        from lib.plan_item_factory import build_record_plan_item
        item = build_record_plan_item(
            action="move", record_id=42, position=5, box=1,
            date_str="2025-01-01", to_position=10, to_box=2,
        )
        self.assertEqual(item["action"], "move")
        self.assertEqual(item["to_position"], 10)
        self.assertEqual(item["to_box"], 2)

    def test_build_edit_plan_item_shape(self):
        from lib.plan_item_factory import build_edit_plan_item
        item = build_edit_plan_item(record_id=7, fields={"note": "test"}, box=1, position=3)
        self.assertEqual(item["action"], "edit")
        self.assertEqual(item["record_id"], 7)
        self.assertEqual(item["payload"]["fields"], {"note": "test"})

    def test_build_rollback_plan_item_shape(self):
        from lib.plan_item_factory import build_rollback_plan_item
        item = build_rollback_plan_item(backup_path="/tmp/backup.yaml")
        self.assertEqual(item["action"], "rollback")
        self.assertIsNone(item["record_id"])
        self.assertEqual(item["payload"]["backup_path"], "/tmp/backup.yaml")


if __name__ == "__main__":
    unittest.main()
