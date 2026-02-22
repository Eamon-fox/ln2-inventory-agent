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

    def test_run_terminal_contract_is_single_string_input_and_not_write_tool(self):
        self.assertIn("run_terminal", TOOL_CONTRACTS)
        params = TOOL_CONTRACTS["run_terminal"]["parameters"]
        self.assertEqual(["command"], params.get("required"))
        self.assertEqual({"command"}, set((params.get("properties") or {}).keys()))
        self.assertEqual(False, params.get("additionalProperties"))
        self.assertNotIn("run_terminal", WRITE_TOOLS)


if __name__ == "__main__":
    unittest.main()
