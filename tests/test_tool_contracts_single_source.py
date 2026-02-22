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
        self.assertIn("record_move", TOOL_CONTRACTS)
        self.assertIn("batch_move", TOOL_CONTRACTS)

        record_takeout_props = TOOL_CONTRACTS["record_takeout"]["parameters"]["properties"]
        self.assertIn("from_box", record_takeout_props)
        self.assertIn("from_position", record_takeout_props)
        self.assertNotIn("action", record_takeout_props)
        self.assertNotIn("to_position", record_takeout_props)

        batch_takeout_props = TOOL_CONTRACTS["batch_takeout"]["parameters"]["properties"]
        self.assertIn("entries", batch_takeout_props)
        entries_schema = batch_takeout_props["entries"]
        self.assertEqual("array", entries_schema.get("type"))
        entry_props = entries_schema["items"]["properties"]
        self.assertIn("from_box", entry_props)
        self.assertIn("from_position", entry_props)
        self.assertNotIn("to_position", entry_props)
        self.assertNotIn("to_box", entry_props)


if __name__ == "__main__":
    unittest.main()
