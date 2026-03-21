"""
Module: test_tool_api_write_adapter
Layer: unit
Covers: lib/tool_api_write_adapter.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from lib import tool_api_write_adapter as adapter


class ToolApiWriteAdapterTests(unittest.TestCase):
    def test_prepare_write_tool_kwargs_defaults_execute_and_resolves_backup(self):
        with patch(
            "lib.tool_api_write_adapter.resolve_request_backup_path",
            return_value="/tmp/request.bak",
        ) as resolve_mock:
            kwargs, backup_path = adapter.prepare_write_tool_kwargs(
                yaml_path="inventory.yaml",
                dry_run=False,
                execution_mode=None,
                request_backup_path="manual/request.bak",
                backup_event_source="agent.react",
                default_execute=True,
            )

        self.assertEqual("/tmp/request.bak", backup_path)
        self.assertEqual(False, kwargs["dry_run"])
        self.assertEqual("execute", kwargs["execution_mode"])
        self.assertEqual("/tmp/request.bak", kwargs["request_backup_path"])
        self.assertEqual(False, kwargs["auto_backup"])
        resolve_mock.assert_called_once_with(
            yaml_path="inventory.yaml",
            execution_mode="execute",
            dry_run=False,
            request_backup_path="manual/request.bak",
            backup_event_source="agent.react",
        )

    def test_prepare_write_tool_kwargs_uses_preflight_for_dry_run(self):
        with patch(
            "lib.tool_api_write_adapter.resolve_request_backup_path",
            return_value=None,
        ) as resolve_mock:
            kwargs, backup_path = adapter.prepare_write_tool_kwargs(
                yaml_path="inventory.yaml",
                dry_run=True,
                execution_mode=None,
                request_backup_path=None,
                backup_event_source="agent.react",
                default_execute=True,
            )

        self.assertIsNone(backup_path)
        self.assertEqual({"dry_run": True, "execution_mode": "preflight"}, kwargs)
        resolve_mock.assert_called_once_with(
            yaml_path="inventory.yaml",
            execution_mode="preflight",
            dry_run=True,
            request_backup_path=None,
            backup_event_source="agent.react",
        )

    def test_to_tool_positions_formats_layout_aware_values(self):
        layout = {"indexing": "alphanumeric", "rows": 9, "cols": 9}
        self.assertEqual(["A1", "A3"], adapter.to_tool_positions([1, 3], layout))
        with self.assertRaisesRegex(ValueError, "positions is invalid"):
            adapter.to_tool_positions(True, layout)

    def test_call_preflight_tool_uses_execute_shaped_protocol(self):
        tool_fn = MagicMock(return_value={"ok": True})
        with patch("lib.tool_api_write_adapter._resolve_tool", return_value=tool_fn), patch(
            "lib.tool_api_write_adapter._resolve_actor_context",
            return_value={"session_id": "sess-1"},
        ):
            response = adapter.call_preflight_tool(
                "edit_entry",
                yaml_path="inventory.yaml",
                record_id=7,
                fields={"note": "ok"},
            )

        self.assertTrue(response["ok"])
        tool_fn.assert_called_once_with(
            yaml_path="inventory.yaml",
            actor_context={"session_id": "sess-1"},
            source="plan_executor.preflight",
            dry_run=False,
            execution_mode="execute",
            auto_backup=False,
            record_id=7,
            fields={"note": "ok"},
        )

    def test_invoke_write_tool_uses_registry_resolution_and_backup_protocol(self):
        tool_fn = MagicMock(return_value={"ok": True})
        with patch(
            "lib.tool_api_write_adapter.resolve_request_backup_path",
            return_value="/tmp/request.bak",
        ), patch("lib.tool_api_write_adapter._resolve_tool", return_value=tool_fn), patch(
            "lib.tool_api_write_adapter._resolve_actor_context",
            return_value={"session_id": "sess-9"},
        ):
            response = adapter.invoke_write_tool(
                "manage_boxes",
                yaml_path="inventory.yaml",
                actor_context={"session_id": "sess-9"},
                source="app_gui",
                execution_mode="execute",
                backup_event_source="app_gui",
                payload={"operation": "add", "count": 2, "auto_backup": True},
            )

        self.assertTrue(response["ok"])
        self.assertEqual("/tmp/request.bak", response["backup_path"])
        tool_fn.assert_called_once_with(
            yaml_path="inventory.yaml",
            actor_context={"session_id": "sess-9"},
            source="app_gui",
            operation="add",
            count=2,
            auto_backup=False,
            dry_run=False,
            execution_mode="execute",
            request_backup_path="/tmp/request.bak",
        )

    def test_resolve_tool_prefers_registry_backed_tool_attr_for_registered_write_tools(self):
        tool_fn = MagicMock()
        fake_tool_api = type("FakeToolApi", (), {"tool_manage_boxes": tool_fn})()

        with patch("lib.tool_api_write_adapter._load_tool_api", return_value=fake_tool_api):
            resolved = adapter._resolve_tool("manage_boxes")

        self.assertIs(tool_fn, resolved)

    def test_resolve_tool_uses_registry_for_gui_only_box_tag_helper(self):
        tool_fn = MagicMock()
        fake_tool_api = type("FakeToolApi", (), {"tool_set_box_tag": tool_fn})()

        with patch("lib.tool_api_write_adapter._load_tool_api", return_value=fake_tool_api):
            resolved = adapter._resolve_tool("set_box_tag")

        self.assertIs(tool_fn, resolved)

    def test_resolve_tool_uses_registry_for_internal_batch_add_helper(self):
        tool_fn = MagicMock()
        fake_tool_api = type("FakeToolApi", (), {"tool_batch_add_entries": tool_fn})()

        with patch("lib.tool_api_write_adapter._load_tool_api", return_value=fake_tool_api):
            resolved = adapter._resolve_tool("batch_add_entries")

        self.assertIs(tool_fn, resolved)

    def test_batch_add_entries_reuses_resolved_request_backup(self):
        tool_fn = MagicMock(return_value={"ok": True})
        with patch(
            "lib.tool_api_write_adapter.resolve_request_backup_path",
            return_value="/tmp/request.bak",
        ), patch("lib.tool_api_write_adapter._resolve_tool", return_value=tool_fn), patch(
            "lib.tool_api_write_adapter._resolve_actor_context",
            return_value={"session_id": "sess-2"},
        ):
            response = adapter.batch_add_entries(
                yaml_path="inventory.yaml",
                entries=[{"box": 1, "positions": ["A1"], "stored_at": "2026-01-01", "fields": {}}],
                execution_mode="execute",
                actor_context={"session_id": "sess-2"},
                source="plan_executor.execute",
                request_backup_path="manual/request.bak",
            )

        self.assertTrue(response["ok"])
        self.assertEqual("/tmp/request.bak", response["backup_path"])
        tool_fn.assert_called_once_with(
            yaml_path="inventory.yaml",
            actor_context={"session_id": "sess-2"},
            source="plan_executor.execute",
            entries=[{"box": 1, "positions": ["A1"], "stored_at": "2026-01-01", "fields": {}}],
            auto_backup=False,
            execution_mode="execute",
            request_backup_path="/tmp/request.bak",
        )


if __name__ == "__main__":
    unittest.main()
