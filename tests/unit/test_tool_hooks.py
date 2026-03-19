import tempfile
import unittest
from pathlib import Path

from agent.tool_hooks import (
    DEFAULT_TOOL_HOOK_SPECS,
    apply_payload_patch,
    build_default_tool_hook_manager,
    merge_hook_result,
)


class ToolHookManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = build_default_tool_hook_manager()
        self.context = {
            "yaml_path": "/tmp/repo/inventories/demo/inventory.yaml",
            "repo_root": "/tmp/repo",
            "migrate_root": "/tmp/repo/migrate",
            "trace_id": "trace-demo",
        }

    def test_bash_before_hook_leaves_default_workdir_unset(self):
        hook_result = self.manager.run_before(
            "bash",
            {"command": "pwd", "description": "print cwd"},
            self.context,
        )

        patched = apply_payload_patch(
            {"command": "pwd", "description": "print cwd"},
            hook_result,
        )

        self.assertIsNone(patched.get("workdir"))

    def test_bash_before_hook_preserves_explicit_repo_relative_workdir(self):
        hook_result = self.manager.run_before(
            "bash",
            {"command": "pwd", "description": "print cwd", "workdir": "output"},
            self.context,
        )

        patched = apply_payload_patch(
            {"command": "pwd", "description": "print cwd", "workdir": "output"},
            hook_result,
        )

        self.assertEqual("output", patched.get("workdir"))

    def test_default_hook_specs_are_explicit_per_tool(self):
        self.assertEqual(
            {
                "use_skill",
                "validate",
                "search_records",
                "filter_records",
                "fs_list",
                "fs_read",
                "fs_write",
                "fs_edit",
                "bash",
                "powershell",
                "import_migration_output",
            },
            set(DEFAULT_TOOL_HOOK_SPECS),
        )
        self.assertTrue(all("*" not in name for name in DEFAULT_TOOL_HOOK_SPECS))

    def test_use_skill_migration_after_hook_returns_hint_and_effect(self):
        hook_result = self.manager.run_after(
            "use_skill",
            {"skill_name": "migration"},
            {"ok": True, "skill_name": "migration"},
            self.context,
        )

        merged = merge_hook_result({"ok": True}, hook_result)

        self.assertIn("migration_checklist.md", str(merged.get("_hint") or ""))
        effects = list(merged.get("ui_effects") or [])
        self.assertEqual("migration_mode", effects[0].get("type"))
        self.assertTrue(bool(effects[0].get("enabled")))

    def test_fs_read_after_hook_adds_hint(self):
        hook_result = self.manager.run_after(
            "fs_read",
            {"path": "README.md"},
            {
                "ok": True,
                "effective_root": "/tmp/repo",
                "resolved_path": "/tmp/repo/README.md",
                "content": "demo",
            },
            self.context,
        )

        self.assertIn("Last read path: README.md", str(hook_result.get("_hint") or ""))

    def test_validate_after_hook_adds_success_hint(self):
        hook_result = self.manager.run_after(
            "validate",
            {"path": "migrate/output/ln2_inventory.yaml"},
            {
                "ok": True,
                "effective_root": "/tmp/repo",
                "resolved_path": "/tmp/repo/migrate/output/ln2_inventory.yaml",
                "report": {"error_count": 0, "warning_count": 0},
            },
            self.context,
        )

        self.assertIn("Validation passed for `migrate/output/ln2_inventory.yaml`.", str(hook_result.get("_hint") or ""))

    def test_validate_after_hook_adds_failure_hint(self):
        hook_result = self.manager.run_after(
            "validate",
            {"path": "migrate/output/ln2_inventory.yaml"},
            {
                "ok": False,
                "error_code": "validation_failed",
                "effective_root": "/tmp/repo",
                "resolved_path": "/tmp/repo/migrate/output/ln2_inventory.yaml",
                "report": {"error_count": 2, "warning_count": 1},
            },
            self.context,
        )

        hint = str(hook_result.get("_hint") or "")
        self.assertIn("Validation failed for `migrate/output/ln2_inventory.yaml`", hint)
        self.assertIn("2 error(s), 1 warning(s)", hint)

    def test_search_records_after_hook_adds_truncation_hint(self):
        hook_result = self.manager.run_after(
            "search_records",
            {"query": "DNA", "max_results": 10},
            {
                "ok": True,
                "result": {
                    "total_count": 15,
                    "display_count": 10,
                },
            },
            self.context,
        )

        hint = str(hook_result.get("_hint") or "")
        self.assertIn("showing 10 of 15 matches", hint)
        self.assertIn("max_results", hint)
        self.assertIn("Do not conclude", hint)

    def test_search_records_after_hook_skips_full_result_pages(self):
        hook_result = self.manager.run_after(
            "search_records",
            {"query": "DNA"},
            {
                "ok": True,
                "result": {
                    "total_count": 3,
                    "display_count": 3,
                },
            },
            self.context,
        )

        self.assertEqual({}, hook_result)

    def test_filter_records_after_hook_adds_truncation_hint(self):
        hook_result = self.manager.run_after(
            "filter_records",
            {"keyword": "DNA", "limit": 10},
            {
                "ok": True,
                "result": {
                    "total_count": 15,
                    "display_count": 10,
                },
            },
            self.context,
        )

        hint = str(hook_result.get("_hint") or "")
        self.assertIn("showing 10 of 15 matches", hint)
        self.assertIn("filter_records", hint)
        self.assertIn("limit", hint)

    def test_fs_write_before_hook_normalizes_relative_path_under_migrate(self):
        hook_result = self.manager.run_before(
            "fs_write",
            {"path": "output/demo.txt", "content": "demo"},
            self.context,
        )

        patched = apply_payload_patch(
            {"path": "output/demo.txt", "content": "demo"},
            hook_result,
        )

        self.assertEqual("migrate/output/demo.txt", patched.get("path"))

    def test_fs_edit_before_hook_normalizes_relative_path_under_migrate(self):
        hook_result = self.manager.run_before(
            "fs_edit",
            {"filePath": "notes.txt", "oldString": "old", "newString": "new"},
            self.context,
        )

        patched = apply_payload_patch(
            {"filePath": "notes.txt", "oldString": "old", "newString": "new"},
            hook_result,
        )

        self.assertEqual("migrate/notes.txt", patched.get("filePath"))

    def test_fs_edit_before_hook_preserves_explicit_repo_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "inventories").mkdir(parents=True, exist_ok=True)
            context = dict(self.context, repo_root=str(repo_root), migrate_root=str(repo_root / "migrate"))
            hook_result = self.manager.run_before(
                "fs_edit",
                {
                    "filePath": "inventories/demo/outside.txt",
                    "oldString": "old",
                    "newString": "new",
                },
                context,
            )

            patched = apply_payload_patch(
                {
                    "filePath": "inventories/demo/outside.txt",
                    "oldString": "old",
                    "newString": "new",
                },
                hook_result,
            )

            self.assertEqual("inventories/demo/outside.txt", patched.get("filePath"))

    def test_import_migration_output_after_hook_returns_dataset_and_exit_effects(self):
        hook_result = self.manager.run_after(
            "import_migration_output",
            {
                "confirmation_token": "CONFIRM_IMPORT",
                "target_dataset_name": "demo",
            },
            {
                "ok": True,
                "target_path": "/tmp/repo/inventories/demo/inventory.yaml",
            },
            self.context,
        )

        effects = list(hook_result.get("ui_effects") or [])
        self.assertEqual("open_dataset", effects[0].get("type"))
        self.assertEqual(
            "/tmp/repo/inventories/demo/inventory.yaml",
            effects[0].get("target_path"),
        )
        self.assertEqual("migration_mode", effects[1].get("type"))
        self.assertFalse(bool(effects[1].get("enabled")))


if __name__ == "__main__":
    unittest.main()
