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
from lib.tool_contracts import TOOL_CONTRACTS, WRITE_TOOLS


class ToolContractsSingleSourceTests(unittest.TestCase):
    def test_agent_uses_canonical_tool_contracts(self):
        self.assertIs(tool_runner._TOOL_CONTRACTS, TOOL_CONTRACTS)

    def test_agent_uses_canonical_write_tools(self):
        self.assertIs(tool_runner._WRITE_TOOLS, WRITE_TOOLS)

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

    def test_migration_import_tool_contracts_exist(self):
        self.assertIn("validate_migration_output", TOOL_CONTRACTS)
        self.assertIn("import_migration_output", TOOL_CONTRACTS)

        validate_params = TOOL_CONTRACTS["validate_migration_output"]["parameters"]
        self.assertEqual([], validate_params.get("required"))
        self.assertEqual({}, validate_params.get("properties"))
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
        self.assertNotIn("validate_migration_output", WRITE_TOOLS)
        self.assertNotIn("import_migration_output", WRITE_TOOLS)

    def test_fs_copy_contract_removed(self):
        self.assertNotIn("fs_copy", TOOL_CONTRACTS)
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


if __name__ == "__main__":
    unittest.main()
