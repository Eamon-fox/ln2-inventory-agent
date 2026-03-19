"""
Module: test_gui_tool_bridge
Layer: integration/gui
Covers: app_gui/tool_bridge.py

GUI 到工具桥接的调用与参数映射测试
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.tool_bridge import GuiToolBridge
from lib.inventory_paths import create_managed_dataset_yaml_path
from lib.tool_registry import GUI_BRIDGE_READ, iter_gui_bridge_descriptors


class GuiToolBridgeTests(unittest.TestCase):
    def _write_inventory(self, dataset_name="bridge-test"):
        path = Path(create_managed_dataset_yaml_path(dataset_name))
        path.write_text(
            """meta:
  box_layout:
    rows: 9
    cols: 9
  custom_fields:
    - key: cell_line
      type: options
      options: [K562]
      required: false
inventory:
  - id: 5
    cell_line: K562
    box: 1
    position: 30
    frozen_at: 2026-02-10
    note: test note
""",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _registry_call_payload(descriptor):
        payload = {}
        bridge_spec = descriptor.gui_bridge
        for field_name in tuple(getattr(bridge_spec, "required_payload_args", ()) or ()):
            if field_name == "record_id":
                payload[field_name] = 5
            elif field_name == "fields":
                payload[field_name] = {"note": "updated"}
            else:
                payload[field_name] = f"sample-{field_name}"
        return payload

    @staticmethod
    def _registry_patch_target(descriptor):
        bridge_spec = descriptor.gui_bridge
        if bridge_spec.strategy == GUI_BRIDGE_READ:
            return f"app_gui.tool_bridge.{bridge_spec.tool_api_attr}"
        return f"app_gui.tool_bridge._write_adapter.{bridge_spec.method_name}"

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

    def test_registry_generated_list_empty_positions_calls_tool_api(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-empty-slots")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.tool_list_empty_positions") as mock_list:
                mock_list.return_value = {"ok": True, "result": {"positions": []}}
                response = bridge.list_empty_positions(str(path), box=2)

            self.assertTrue(response.get("ok"))
            mock_list.assert_called_once_with(
                yaml_path=str(path),
                box=2,
            )

    def test_registry_generated_filter_records_calls_tool_api(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-filter-table")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.tool_filter_records") as mock_filter:
                mock_filter.return_value = {"ok": True, "result": {"rows": [], "columns": []}}
                response = bridge.filter_records(
                    str(path),
                    keyword="genomic DNA",
                    box=1,
                    color_value="K562",
                    include_inactive=True,
                    column_filters={"cell_line": {"type": "text", "text": "K562"}},
                    sort_by="location",
                    sort_order="asc",
                    limit=50,
                    offset=10,
                )

            self.assertTrue(response.get("ok"))
            mock_filter.assert_called_once_with(
                yaml_path=str(path),
                keyword="genomic DNA",
                box=1,
                color_value="K562",
                include_inactive=True,
                column_filters={"cell_line": {"type": "text", "text": "K562"}},
                sort_by="location",
                sort_order="asc",
                limit=50,
                offset=10,
            )

    def test_registry_generated_edit_entry_preserves_write_bridge_behavior(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-edit")
            bridge = GuiToolBridge(session_id="gui-session-1")

            with patch("app_gui.tool_bridge._write_adapter.edit_entry") as mock_edit:
                mock_edit.return_value = {"ok": True, "result": {}}
                response = bridge.edit_entry(
                    str(path),
                    record_id=5,
                    fields={"note": "updated"},
                    execution_mode="execute",
                    auto_backup=False,
                )

            self.assertTrue(response.get("ok"))
            mock_edit.assert_called_once()
            kwargs = mock_edit.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertEqual(5, kwargs.get("record_id"))
            self.assertEqual({"note": "updated"}, kwargs.get("fields"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual(False, kwargs.get("auto_backup"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("gui-session-1", kwargs.get("actor_context", {}).get("session_id"))

    def test_registry_generated_methods_accept_keyword_yaml_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-keyword-yaml-path")
            bridge = GuiToolBridge(session_id="keyword-session")

            for descriptor in iter_gui_bridge_descriptors():
                bridge_spec = descriptor.gui_bridge
                payload = self._registry_call_payload(descriptor)
                patch_target = self._registry_patch_target(descriptor)

                with self.subTest(method=bridge_spec.method_name), patch(patch_target) as mock_tool:
                    mock_tool.return_value = {"ok": True, "result": {}}
                    response = getattr(bridge, bridge_spec.method_name)(
                        yaml_path=str(path),
                        **payload,
                    )

                    self.assertTrue(response.get("ok"))
                    self.assertEqual(str(path), mock_tool.call_args.kwargs.get("yaml_path"))

    def test_registry_generated_methods_accept_positional_yaml_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-positional-yaml-path")
            bridge = GuiToolBridge(session_id="positional-session")

            for descriptor in iter_gui_bridge_descriptors():
                bridge_spec = descriptor.gui_bridge
                payload = self._registry_call_payload(descriptor)
                patch_target = self._registry_patch_target(descriptor)

                with self.subTest(method=bridge_spec.method_name), patch(patch_target) as mock_tool:
                    mock_tool.return_value = {"ok": True, "result": {}}
                    response = getattr(bridge, bridge_spec.method_name)(
                        str(path),
                        **payload,
                    )

                    self.assertTrue(response.get("ok"))
                    self.assertEqual(str(path), mock_tool.call_args.kwargs.get("yaml_path"))

    def test_registry_generated_methods_reject_duplicate_yaml_path(self):
        bridge = GuiToolBridge()

        for descriptor in iter_gui_bridge_descriptors():
            bridge_spec = descriptor.gui_bridge
            payload = self._registry_call_payload(descriptor)
            with self.subTest(method=bridge_spec.method_name):
                with self.assertRaises(TypeError) as exc_info:
                    getattr(bridge, bridge_spec.method_name)(
                        "inventory.yaml",
                        yaml_path="inventory.yaml",
                        **payload,
                    )

                self.assertIn("yaml_path", str(exc_info.exception))
                self.assertIn("multiple values", str(exc_info.exception))

    def test_registry_generated_methods_require_yaml_path(self):
        bridge = GuiToolBridge()

        for descriptor in iter_gui_bridge_descriptors():
            bridge_spec = descriptor.gui_bridge
            payload = self._registry_call_payload(descriptor)
            with self.subTest(method=bridge_spec.method_name):
                with self.assertRaises(TypeError) as exc_info:
                    getattr(bridge, bridge_spec.method_name)(**payload)

                self.assertIn("yaml_path", str(exc_info.exception))
                self.assertIn("required positional argument", str(exc_info.exception))

    def test_run_agent_query_builds_runner_without_access_profile(self):
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
                )

            self.assertTrue(response.get("ok"))
            kwargs = runner_cls.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertNotIn("allowed_tools", kwargs)
            self.assertNotIn("expose_inventory_context", kwargs)

    def test_add_entry_routes_registry_write_through_shared_adapter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-add-write")
            bridge = GuiToolBridge(session_id="bridge-session")

            with patch("app_gui.tool_bridge._write_adapter.add_entry") as mock_add:
                mock_add.return_value = {"ok": True, "result": {"id": 9}}
                response = bridge.add_entry(
                    str(path),
                    box=1,
                    positions=[2],
                    stored_at="2026-02-10",
                    fields={"note": "from gui"},
                )

            self.assertTrue(response.get("ok"))
            mock_add.assert_called_once()
            kwargs = mock_add.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("app_gui", kwargs.get("backup_event_source"))
            self.assertEqual(1, kwargs.get("box"))
            self.assertEqual([2], kwargs.get("positions"))
            self.assertEqual("2026-02-10", kwargs.get("stored_at"))
            self.assertEqual("bridge-session", kwargs.get("actor_context", {}).get("session_id"))

    def test_registry_write_backup_failure_maps_to_gui_error(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-add-failure")
            bridge = GuiToolBridge()

            with patch(
                "app_gui.tool_bridge._write_adapter.add_entry",
                side_effect=RuntimeError("backup exploded"),
            ):
                response = bridge.add_entry(
                    str(path),
                    box=1,
                    positions=[3],
                    stored_at="2026-02-10",
                    fields={},
                )

            self.assertFalse(response.get("ok"))
            self.assertEqual("backup_create_failed", response.get("error_code"))
            self.assertIn("backup exploded", response.get("message", ""))

    def test_set_box_tag_routes_explicit_write_through_shared_adapter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_bridge_") as install_dir, patch(
            "lib.inventory_paths.get_install_dir",
            return_value=install_dir,
        ):
            path = self._write_inventory("bridge-box-tag")
            bridge = GuiToolBridge(session_id="bridge-tag")

            with patch("app_gui.tool_bridge._write_adapter.set_box_tag") as mock_set_tag:
                mock_set_tag.return_value = {"ok": True}
                response = bridge.set_box_tag(
                    str(path),
                    box=1,
                    tag="frozen",
                    execution_mode="execute",
                )

            self.assertTrue(response.get("ok"))
            mock_set_tag.assert_called_once()
            kwargs = mock_set_tag.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertEqual(1, kwargs.get("box"))
            self.assertEqual("frozen", kwargs.get("tag"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("bridge-tag", kwargs.get("actor_context", {}).get("session_id"))


if __name__ == "__main__":
    unittest.main()
