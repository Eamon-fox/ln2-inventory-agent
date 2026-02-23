import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.tool_bridge import GuiToolBridge
from agent.tool_access_profiles import MIGRATION_ALLOWED_TOOLS
from lib.inventory_paths import create_managed_dataset_yaml_path


class GuiToolBridgeTests(unittest.TestCase):
    def _write_inventory(self, dataset_name="bridge-test"):
        path = Path(create_managed_dataset_yaml_path(dataset_name))
        path.write_text(
            """meta:
  box_layout:
    rows: 9
    cols: 9
inventory:
  - id: 5
    parent_cell_line: K562
    short_name: K562_clone12
    box: 1
    positions: [30]
    frozen_at: 2026-02-10
    note: test note
""",
            encoding="utf-8",
        )
        return path

    def test_export_inventory_csv_writes_full_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-export")
            bridge = GuiToolBridge()

            output_path = Path(install_dir) / "full_export.csv"
            response = bridge.export_inventory_csv(str(path), str(output_path))

            self.assertTrue(response.get("ok"))
            self.assertTrue(output_path.exists())

            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))

            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual("id", rows[0][0])
            self.assertIn("cell_line", rows[0])
            self.assertEqual("5", rows[1][0])
            self.assertIn("test note", rows[1])

    def test_generate_stats_requests_full_records_for_gui(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-stats")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.tool_generate_stats") as mock_generate:
                mock_generate.return_value = {"ok": True, "result": {}}
                response = bridge.generate_stats(str(path), box=2, include_inactive=True)

            self.assertTrue(response.get("ok"))
            mock_generate.assert_called_once_with(
                yaml_path=str(path),
                box=2,
                include_inactive=True,
                full_records_for_gui=True,
            )

    def test_run_agent_query_migration_mode_uses_restricted_tool_profile(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-agent-mode")
            bridge = GuiToolBridge()
            bridge.set_api_keys({"deepseek": "sk-test"})

            with patch("app_gui.tool_bridge.DeepSeekLLMClient") as llm_cls, patch(
                "app_gui.tool_bridge.AgentToolRunner"
            ) as runner_cls, patch("app_gui.tool_bridge.ReactAgent") as agent_cls:
                llm_cls.return_value = object()
                runner_cls.return_value = object()
                fake_agent = MagicMock()
                fake_agent.run.return_value = {"ok": True, "final": "done"}
                agent_cls.return_value = fake_agent

                response = bridge.run_agent_query(
                    yaml_path=str(path),
                    query="run migration flow",
                    agent_mode="migration",
                )

            self.assertTrue(response.get("ok"))
            kwargs = runner_cls.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertFalse(kwargs.get("expose_inventory_context"))
            allowed_tools = set(kwargs.get("allowed_tools") or [])
            self.assertEqual(set(MIGRATION_ALLOWED_TOOLS), allowed_tools)
            self.assertNotIn("search_records", allowed_tools)


if __name__ == "__main__":
    unittest.main()
