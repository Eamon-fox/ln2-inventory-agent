import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.tool_bridge import GuiToolBridge
from lib.yaml_ops import write_yaml


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


class GuiBridgeAgentTests(unittest.TestCase):
    def test_run_agent_query_mock_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_agent_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 1,
                            "positions": [1],
                            "frozen_at": "2026-02-10",
                        }
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            bridge = GuiToolBridge(actor_id="gui-test", session_id="session-gui-test")
            response = bridge.run_agent_query(
                yaml_path=str(yaml_path),
                query="Find K562 records",
                mock=True,
                max_steps=6,
            )

            self.assertTrue(response["ok"])
            self.assertEqual("mock", response["mode"])
            self.assertIsNone(response["model"])
            self.assertTrue(response["result"]["ok"])
            self.assertTrue(response["result"].get("trace_id"))
            self.assertIn("Mock client enabled", response["result"].get("final", ""))

    def test_run_agent_query_requires_prompt(self):
        bridge = GuiToolBridge()
        response = bridge.run_agent_query(
            yaml_path="/tmp/does_not_matter.yaml",
            query="   ",
            mock=True,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("empty_query", response["error_code"])

    def test_run_agent_query_passes_history_to_agent(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_agent_history_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 1,
                            "positions": [1],
                            "frozen_at": "2026-02-10",
                        }
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            bridge = GuiToolBridge(actor_id="gui-test", session_id="session-gui-test")
            response = bridge.run_agent_query(
                yaml_path=str(yaml_path),
                query="repeat",
                mock=True,
                history=[
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            )

            self.assertTrue(response["ok"])
            self.assertEqual(2, response["result"].get("conversation_history_used"))

    def test_run_agent_query_requires_api_key_when_not_mock(self):
        bridge = GuiToolBridge()
        with patch("app_gui.tool_bridge.DeepSeekLLMClient", side_effect=RuntimeError("DEEPSEEK_API_KEY is required")):
            response = bridge.run_agent_query(
                yaml_path="/tmp/does_not_matter.yaml",
                query="show stats",
                mock=False,
                model=None,
            )

        self.assertFalse(response["ok"])
        self.assertEqual("api_key_required", response["error_code"])

    def test_run_agent_query_rejects_bad_max_steps(self):
        bridge = GuiToolBridge()
        response = bridge.run_agent_query(
            yaml_path="/tmp/does_not_matter.yaml",
            query="show stats",
            mock=True,
            max_steps=0,
        )

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_max_steps", response["error_code"])

    def test_run_agent_query_rejects_invalid_agent_result(self):
        bridge = GuiToolBridge()
        with patch("app_gui.tool_bridge.ReactAgent.run", return_value="bad-payload"):
            response = bridge.run_agent_query(
                yaml_path="/tmp/does_not_matter.yaml",
                query="show stats",
                mock=True,
            )

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_agent_result", response["error_code"])

    def test_run_agent_query_emits_progress_events(self):
        with tempfile.TemporaryDirectory(prefix="ln2_gui_agent_events_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 1,
                            "positions": [1],
                            "frozen_at": "2026-02-10",
                        }
                    ]
                ),
                path=str(yaml_path),
                auto_html=False,
                auto_server=False,
            )

            bridge = GuiToolBridge(actor_id="gui-test", session_id="session-gui-test")
            events = []
            response = bridge.run_agent_query(
                yaml_path=str(yaml_path),
                query="Find K562 records",
                mock=True,
                on_event=lambda e: events.append(dict(e)),
            )

            self.assertTrue(response["ok"])
            event_names = [e.get("event") for e in events]
            self.assertIn("run_start", event_names)
            self.assertIn("step_start", event_names)
            self.assertIn("final", event_names)
            self.assertIn("stream_end", event_names)


if __name__ == "__main__":
    unittest.main()
