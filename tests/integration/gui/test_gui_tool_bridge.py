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
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.tool_bridge import GuiToolBridge
from app_gui.i18n import tr
from lib.app_storage import clear_session_data_root, set_session_data_root
from lib.inventory_paths import create_managed_dataset_yaml_path
from lib.tool_registry import GUI_BRIDGE_READ, iter_gui_bridge_descriptors


@contextmanager
def _managed_data_root(prefix):
    with tempfile.TemporaryDirectory(prefix=prefix) as install_root:
        set_session_data_root(install_root)
        try:
            yield Path(install_root)
        finally:
            clear_session_data_root()


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
            return "app_gui.tool_bridge.resolve_tool_api_callable"
        return "app_gui.tool_bridge._write_adapter.invoke_write_tool"

    def test_export_inventory_csv_writes_full_snapshot(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
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
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-stats")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.resolve_tool_api_callable") as mock_resolve:
                mock_generate = MagicMock(return_value={"ok": True, "result": {}})
                mock_resolve.return_value = mock_generate
                response = bridge.generate_stats(str(path), box=2, include_inactive=True)

            self.assertTrue(response.get("ok"))
            mock_resolve.assert_called_once_with("tool_generate_stats")
            mock_generate.assert_called_once_with(
                yaml_path=str(path),
                box=2,
                include_inactive=True,
                full_records_for_gui=True,
            )

    def test_registry_generated_list_empty_positions_calls_tool_api(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-empty-slots")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.resolve_tool_api_callable") as mock_resolve:
                mock_list = MagicMock(return_value={"ok": True, "result": {"positions": []}})
                mock_resolve.return_value = mock_list
                response = bridge.list_empty_positions(str(path), box=2)

            self.assertTrue(response.get("ok"))
            mock_resolve.assert_called_once_with("tool_list_empty_positions")
            mock_list.assert_called_once_with(
                yaml_path=str(path),
                box=2,
            )

    def test_registry_generated_filter_records_calls_tool_api(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-filter-table")
            bridge = GuiToolBridge()

            with patch("app_gui.tool_bridge.resolve_tool_api_callable") as mock_resolve:
                mock_filter = MagicMock(
                    return_value={"ok": True, "result": {"rows": [], "columns": []}}
                )
                mock_resolve.return_value = mock_filter
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
            mock_resolve.assert_called_once_with("tool_filter_records")
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
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-edit")
            bridge = GuiToolBridge(session_id="gui-session-1")

            with patch("app_gui.tool_bridge._write_adapter.invoke_write_tool") as mock_invoke:
                mock_invoke.return_value = {"ok": True, "result": {}}
                response = bridge.edit_entry(
                    str(path),
                    record_id=5,
                    fields={"note": "updated"},
                    execution_mode="execute",
                    auto_backup=False,
                )

            self.assertTrue(response.get("ok"))
            mock_invoke.assert_called_once()
            self.assertEqual("edit_entry", mock_invoke.call_args.args[0])
            kwargs = mock_invoke.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            payload = kwargs.get("payload") or {}
            self.assertEqual(5, payload.get("record_id"))
            self.assertEqual({"note": "updated"}, payload.get("fields"))
            self.assertEqual(False, payload.get("auto_backup"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("gui-session-1", kwargs.get("actor_context", {}).get("session_id"))

    def test_registry_generated_manage_boxes_preserves_write_bridge_behavior(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-manage-boxes")
            bridge = GuiToolBridge(session_id="boxes-session")

            with patch("app_gui.tool_bridge._write_adapter.invoke_write_tool") as mock_invoke:
                mock_invoke.return_value = {"ok": True, "result": {}}
                response = bridge.manage_boxes(
                    str(path),
                    operation="add",
                    count=2,
                    execution_mode="execute",
                )

            self.assertTrue(response.get("ok"))
            mock_invoke.assert_called_once()
            self.assertEqual("manage_boxes", mock_invoke.call_args.args[0])
            kwargs = mock_invoke.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            payload = kwargs.get("payload") or {}
            self.assertEqual("add", payload.get("operation"))
            self.assertEqual(2, payload.get("count"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("app_gui", kwargs.get("backup_event_source"))
            self.assertEqual("boxes-session", kwargs.get("actor_context", {}).get("session_id"))

    def test_registry_generated_edit_entry_execute_mode_creates_backup_and_persists(self):
        from lib.yaml_ops import load_yaml

        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-edit-execute")
            bridge = GuiToolBridge(session_id="gui-session-2")

            response = bridge.edit_entry(
                str(path),
                record_id=5,
                fields={"note": "updated"},
                execution_mode="execute",
            )

            self.assertTrue(response.get("ok"))
            self.assertTrue(str(response.get("backup_path") or "").strip())
            current = load_yaml(str(path))
            self.assertEqual("updated", current["inventory"][0]["note"])

    def test_registry_generated_methods_accept_keyword_yaml_path(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-keyword-yaml-path")
            bridge = GuiToolBridge(session_id="keyword-session")

            for descriptor in iter_gui_bridge_descriptors():
                bridge_spec = descriptor.gui_bridge
                payload = self._registry_call_payload(descriptor)
                patch_target = self._registry_patch_target(descriptor)

                with self.subTest(method=bridge_spec.method_name), patch(patch_target) as mock_target:
                    if bridge_spec.strategy == GUI_BRIDGE_READ:
                        mock_tool = MagicMock(return_value={"ok": True, "result": {}})
                        mock_target.return_value = mock_tool
                    else:
                        mock_target.return_value = {"ok": True, "result": {}}
                    response = getattr(bridge, bridge_spec.method_name)(
                        yaml_path=str(path),
                        **payload,
                    )

                    self.assertTrue(response.get("ok"))
                    if bridge_spec.strategy == GUI_BRIDGE_READ:
                        mock_target.assert_called_once_with(bridge_spec.tool_api_attr)
                        self.assertEqual(str(path), mock_tool.call_args.kwargs.get("yaml_path"))
                    else:
                        self.assertEqual(descriptor.name, mock_target.call_args.args[0])
                        self.assertEqual(str(path), mock_target.call_args.kwargs.get("yaml_path"))

    def test_registry_generated_methods_accept_positional_yaml_path(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-positional-yaml-path")
            bridge = GuiToolBridge(session_id="positional-session")

            for descriptor in iter_gui_bridge_descriptors():
                bridge_spec = descriptor.gui_bridge
                payload = self._registry_call_payload(descriptor)
                patch_target = self._registry_patch_target(descriptor)

                with self.subTest(method=bridge_spec.method_name), patch(patch_target) as mock_target:
                    if bridge_spec.strategy == GUI_BRIDGE_READ:
                        mock_tool = MagicMock(return_value={"ok": True, "result": {}})
                        mock_target.return_value = mock_tool
                    else:
                        mock_target.return_value = {"ok": True, "result": {}}
                    response = getattr(bridge, bridge_spec.method_name)(
                        str(path),
                        **payload,
                    )

                    self.assertTrue(response.get("ok"))
                    if bridge_spec.strategy == GUI_BRIDGE_READ:
                        mock_target.assert_called_once_with(bridge_spec.tool_api_attr)
                        self.assertEqual(str(path), mock_tool.call_args.kwargs.get("yaml_path"))
                    else:
                        self.assertEqual(descriptor.name, mock_target.call_args.args[0])
                        self.assertEqual(str(path), mock_target.call_args.kwargs.get("yaml_path"))

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
        from app_gui.agent_session import AgentSessionService

        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-agent-mode")
            service = AgentSessionService()
            service.set_api_keys({"deepseek": "sk-test"})

            with patch("app_gui.agent_session.DeepSeekLLMClient") as llm_cls, patch(
                "app_gui.agent_session.AgentToolRunner"
            ) as runner_cls, patch("app_gui.agent_session.ReactAgent") as agent_cls:
                llm_cls.return_value = object()
                runner_cls.return_value = object()
                fake_agent = MagicMock()
                fake_agent.run.return_value = {"ok": True, "final": "done"}
                agent_cls.return_value = fake_agent

                response = service.run_agent_query(
                    yaml_path=str(path),
                    query="run migration flow",
                )

            self.assertTrue(response.get("ok"))
            kwargs = runner_cls.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertIs(tr, kwargs.get("tr_func"))
            self.assertIs(service._shell_state, kwargs.get("shell_state"))
            self.assertNotIn("allowed_tools", kwargs)
            self.assertNotIn("expose_inventory_context", kwargs)

    def test_agent_session_reset_shell_state_restores_repo_root(self):
        from app_gui.agent_session import AgentSessionService

        service = AgentSessionService()
        service._shell_state.current_workdir = "migrate"

        service.reset_shell_state()

        self.assertEqual(".", service._shell_state.current_workdir)

    def test_add_entry_routes_registry_write_through_shared_adapter(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-add-write")
            bridge = GuiToolBridge(session_id="bridge-session")

            with patch("app_gui.tool_bridge._write_adapter.invoke_write_tool") as mock_invoke:
                mock_invoke.return_value = {"ok": True, "result": {"id": 9}}
                response = bridge.add_entry(
                    str(path),
                    box=1,
                    positions=[2],
                    stored_at="2026-02-10",
                    fields={"note": "from gui"},
                )

            self.assertTrue(response.get("ok"))
            mock_invoke.assert_called_once()
            self.assertEqual("add_entry", mock_invoke.call_args.args[0])
            kwargs = mock_invoke.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("app_gui", kwargs.get("backup_event_source"))
            payload = kwargs.get("payload") or {}
            self.assertEqual(1, payload.get("box"))
            self.assertEqual([2], payload.get("positions"))
            self.assertEqual("2026-02-10", payload.get("stored_at"))
            self.assertEqual("bridge-session", kwargs.get("actor_context", {}).get("session_id"))

    def test_registry_write_backup_failure_maps_to_gui_error(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-add-failure")
            bridge = GuiToolBridge()

            with patch(
                "app_gui.tool_bridge._write_adapter.invoke_write_tool",
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
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-box-tag")
            bridge = GuiToolBridge(session_id="bridge-tag")

            with patch("app_gui.tool_bridge._write_adapter.invoke_write_tool") as mock_invoke:
                mock_invoke.return_value = {"ok": True}
                response = bridge.set_box_tag(
                    str(path),
                    box=1,
                    tag="frozen",
                    execution_mode="execute",
                )

            self.assertTrue(response.get("ok"))
            mock_invoke.assert_called_once()
            self.assertEqual("set_box_tag", mock_invoke.call_args.args[0])
            kwargs = mock_invoke.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            payload = kwargs.get("payload") or {}
            self.assertEqual(1, payload.get("box"))
            self.assertEqual("frozen", payload.get("tag"))
            self.assertEqual("execute", kwargs.get("execution_mode"))

    def test_set_box_layout_indexing_routes_explicit_write_through_shared_adapter(self):
        with _managed_data_root("ln2_bridge_") as install_dir:
            path = self._write_inventory("bridge-box-indexing")
            bridge = GuiToolBridge(session_id="bridge-indexing")

            with patch("app_gui.tool_bridge._write_adapter.invoke_write_tool") as mock_invoke:
                mock_invoke.return_value = {"ok": True}
                response = bridge.set_box_layout_indexing(
                    str(path),
                    indexing="alphanumeric",
                    execution_mode="execute",
                )

            self.assertTrue(response.get("ok"))
            mock_invoke.assert_called_once()
            self.assertEqual("set_box_layout_indexing", mock_invoke.call_args.args[0])
            kwargs = mock_invoke.call_args.kwargs
            self.assertEqual(str(path), kwargs.get("yaml_path"))
            payload = kwargs.get("payload") or {}
            self.assertEqual("alphanumeric", payload.get("indexing"))
            self.assertEqual("execute", kwargs.get("execution_mode"))
            self.assertEqual("app_gui", kwargs.get("source"))
            self.assertEqual("app_gui", kwargs.get("backup_event_source"))
            self.assertEqual("bridge-indexing", kwargs.get("actor_context", {}).get("session_id"))


if __name__ == "__main__":
    unittest.main()
