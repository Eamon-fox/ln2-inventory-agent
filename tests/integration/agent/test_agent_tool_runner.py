"""
Module: test_agent_tool_runner
Layer: integration/agent
Covers: agent/tool_runner.py

工具分发、验证与处理器行为
"""

import ast
import json
import sys
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_runner import AgentToolRunner
from lib.tool_api_write_validation import resolve_request_backup_path
from lib.yaml_ops import create_yaml_backup, get_audit_log_path, load_yaml, read_audit_events, write_yaml
from tests.managed_paths import ManagedPathTestCase


def _collect_agent_tool_runner_i18n_keys():
    source = (ROOT / "agent" / "tool_runner.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    keys = set()

    for node in ast.walk(module):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_msg"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)

    for node in module.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_TOOL_CONTRACTS" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            continue

        for name_node, contract_node in zip(node.value.keys, node.value.values):
            if not (
                isinstance(name_node, ast.Constant)
                and isinstance(name_node.value, str)
                and isinstance(contract_node, ast.Dict)
            ):
                continue

            tool_name = name_node.value
            has_description = False
            has_notes = False
            for key_node, _value_node in zip(contract_node.keys, contract_node.values):
                if isinstance(key_node, ast.Constant) and key_node.value == "description":
                    has_description = True
                if isinstance(key_node, ast.Constant) and key_node.value == "notes":
                    has_notes = True

            if has_description:
                keys.add(f"toolContracts.{tool_name}.description")
            if has_notes:
                keys.add(f"toolContracts.{tool_name}.notes")
        break

    return keys


def _flatten_leaf_keys(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix} if prefix else set()

    flattened = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flattened |= _flatten_leaf_keys(value, path)
        else:
            flattened.add(path)
    return flattened


def make_record(rec_id=1, box=1, position=None):
    return {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "position": position if position is not None else 1,
        "frozen_at": "2025-01-01",
    }


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


def make_data_alphanumeric(records):
    data = make_data(records)
    data["meta"]["box_layout"]["indexing"] = "alphanumeric"
    return data


class AgentToolRunnerTests(ManagedPathTestCase):
    def _repo_root(self):
        return Path(self.fake_yaml_path).resolve().parents[2]

    def test_list_tools_contains_core_entries(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        names = set(runner.list_tools())
        self.assertIn("search_records", names)
        self.assertIn("recent_frozen", names)
        self.assertIn("query_takeout_events", names)
        self.assertIn("list_audit_timeline", names)
        self.assertIn("add_entry", names)
        self.assertIn("takeout", names)
        self.assertIn("move", names)
        self.assertIn("bash", names)
        self.assertIn("powershell", names)
        self.assertIn("use_skill", names)
        self.assertIn("fs_list", names)
        self.assertIn("fs_read", names)
        self.assertIn("fs_write", names)
        self.assertIn("fs_edit", names)
        self.assertNotIn("edit", names)
        self.assertIn("validate_migration_output", names)
        self.assertIn("import_migration_output", names)
        self.assertNotIn("python_run", names)
        self.assertIn("manage_boxes", names)
        self.assertIn("staged_plan", names)
        self.assertNotIn("manage_boxes_add", names)
        self.assertNotIn("manage_boxes_remove", names)
        self.assertNotIn("staged_list", names)
        self.assertNotIn("staged_remove", names)
        self.assertNotIn("staged_clear", names)
        self.assertNotIn("manage_staged", names)
        self.assertNotIn("collect_timeline", names)
        self.assertNotIn("list_staged", names)
        self.assertNotIn("remove_staged", names)
        self.assertNotIn("clear_staged", names)

    def test_list_tools_returns_full_contract_surface(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        names = set(runner.list_tools())
        self.assertIn("search_records", names)
        self.assertIn("add_entry", names)
        self.assertIn("staged_plan", names)

    def test_tool_schemas_cover_full_contract_surface(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        names = {
            item.get("function", {}).get("name")
            for item in runner.tool_schemas()
            if isinstance(item, dict)
        }
        self.assertIn("question", names)
        self.assertIn("use_skill", names)
        self.assertIn("search_records", names)
        self.assertIn("add_entry", names)
        self.assertIn("staged_plan", names)

    def test_use_skill_returns_migration_skill_body_and_resources(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("use_skill", {"skill_name": "migration"})

        self.assertTrue(response["ok"])
        self.assertEqual("migration", response.get("skill_name"))
        self.assertIn("Convert staged legacy source files", str(response.get("description") or ""))
        self.assertIn("Core Workflow", str(response.get("instructions_markdown") or ""))
        refs = list(response.get("references") or [])
        shared_refs = list(response.get("shared_references") or [])
        assets = list(response.get("assets") or [])
        self.assertIn("agent_skills/migration/references/runbook_en.md", refs)
        self.assertIn("agent_skills/shared/references/schema_context.md", shared_refs)
        self.assertIn("agent_skills/migration/assets/acceptance_checklist_en.md", assets)

    def test_use_skill_migration_returns_hook_hint_and_ui_effects(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("use_skill", {"skill_name": "migration"})

        self.assertTrue(response["ok"])
        self.assertIn("migration_checklist.md", str(response.get("_hint") or ""))
        self.assertIn("ln2_inventory.yaml", str(response.get("_hint") or ""))
        ui_effects = list(response.get("ui_effects") or [])
        self.assertTrue(
            any(
                effect.get("type") == "migration_mode" and bool(effect.get("enabled"))
                for effect in ui_effects
                if isinstance(effect, dict)
            ),
            ui_effects,
        )

    def test_use_skill_returns_available_skills_for_unknown_name(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("use_skill", {"skill_name": "missing-skill"})

        self.assertFalse(response["ok"])
        self.assertEqual("unknown_skill", response.get("error_code"))
        self.assertIn("migration", list(response.get("available_skills") or []))
        self.assertIn("yaml-repair", list(response.get("available_skills") or []))

    def _migration_output_path(self):
        repo_root = self._repo_root()
        output_dir = repo_root / "migrate" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / "ln2_inventory.yaml"

    def _migration_validation_report_path(self):
        repo_root = self._repo_root()
        output_dir = repo_root / "migrate" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / "validation_report.json"

    def test_validate_migration_output_returns_file_not_found_when_missing(self):
        candidate = self._migration_output_path()
        report_path = self._migration_validation_report_path()
        candidate.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate_migration_output", {})

        self.assertFalse(response["ok"])
        self.assertEqual("file_not_found", response.get("error_code"))
        self.assertIn("Candidate YAML not found", str(response.get("message") or ""))
        self.assertIn("migration_checklist.md", str(response.get("_hint") or ""))
        self.assertEqual(str(report_path), str(response.get("validation_report_path") or ""))
        self.assertTrue(response.get("validation_report_written"))
        self.assertTrue(report_path.is_file())
        persisted = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(persisted.get("ok"))
        self.assertEqual("validate_migration_output", persisted.get("validation_tool"))

    def test_validate_migration_output_returns_ok_when_output_yaml_is_valid(self):
        candidate = self._migration_output_path()
        report_path = self._migration_validation_report_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "  custom_fields:\n"
                "    - key: cell_line\n"
                "      label: Cell Line\n"
                "      type: str\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: K562\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        report_path.unlink(missing_ok=True)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate_migration_output", {})

        self.assertTrue(response["ok"])
        report = response.get("report") or {}
        self.assertEqual(0, report.get("error_count"))
        self.assertIn("migration_checklist.md", str(response.get("_hint") or ""))
        self.assertEqual(str(report_path), str(response.get("validation_report_path") or ""))
        self.assertTrue(response.get("validation_report_written"))
        self.assertTrue(report_path.is_file())
        persisted = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(persisted.get("ok"))
        self.assertEqual(0, ((persisted.get("report") or {}).get("error_count") or 0))

    def test_validate_migration_output_validation_failed_hint_mentions_checklist(self):
        candidate = self._migration_output_path()
        report_path = self._migration_validation_report_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "  color_key: legacy_alias\n"
                "  custom_fields:\n"
                "    - key: cell_line\n"
                "      label: Cell Line\n"
                "      type: str\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        report_path.unlink(missing_ok=True)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate_migration_output", {})

        self.assertFalse(response["ok"])
        self.assertEqual("validation_failed", response.get("error_code"))
        self.assertIn("migration_checklist.md", str(response.get("_hint") or ""))
        self.assertEqual(str(report_path), str(response.get("validation_report_path") or ""))
        self.assertTrue(response.get("validation_report_written"))
        self.assertTrue(report_path.is_file())
        persisted = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(persisted.get("ok"))
        self.assertEqual("validation_failed", str(persisted.get("error_code") or ""))

    def test_validate_migration_output_accepts_valid_box_tags(self):
        candidate = self._migration_output_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "    box_tags:\n"
                "      1: Rack A\n"
                "      3: Shelf B\n"
                "  custom_fields:\n"
                "    - key: cell_line\n"
                "      label: Cell Line\n"
                "      type: str\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: K562\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate_migration_output", {})

        self.assertTrue(response["ok"])
        report = response.get("report") or {}
        self.assertEqual(0, report.get("error_count"))

    def test_validate_migration_output_rejects_undeclared_box_tag(self):
        candidate = self._migration_output_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "    box_tags:\n"
                "      6: Not Declared\n"
                "  custom_fields:\n"
                "    - key: cell_line\n"
                "      label: Cell Line\n"
                "      type: str\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: K562\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate_migration_output", {})

        self.assertFalse(response["ok"])
        self.assertEqual("validation_failed", response.get("error_code"))
        report = response.get("report") or {}
        errors = list(report.get("errors") or [])
        self.assertTrue(any("box_tags key '6'" in msg for msg in errors), report)

    def test_import_migration_output_requires_explicit_confirmation_token(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "import_migration_output",
            {
                "confirmation_token": "confirm_import",
                "target_dataset_name": "imported_dataset",
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_confirmation_token", response.get("error_code"))

    def test_import_migration_output_requires_target_dataset_name(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "import_migration_output",
            {"confirmation_token": "CONFIRM_IMPORT"},
        )

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response.get("error_code"))
        self.assertIn("target_dataset_name", str(response.get("message") or ""))

    def test_import_migration_output_rejects_invalid_target_dataset_name(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "import_migration_output",
            {
                "confirmation_token": "CONFIRM_IMPORT",
                "target_dataset_name": "bad/name",
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_target_dataset_name", response.get("error_code"))

    def test_import_migration_output_creates_new_managed_dataset(self):
        candidate = self._migration_output_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "  custom_fields:\n"
                "    - key: cell_line\n"
                "      label: Cell Line\n"
                "      type: str\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: K562\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run(
            "import_migration_output",
            {
                "confirmation_token": "CONFIRM_IMPORT",
                "target_dataset_name": "migrated_batch_01",
            },
        )

        self.assertTrue(response["ok"])
        target_path = Path(str(response.get("target_path") or ""))
        self.assertTrue(target_path.is_file())
        self.assertIn(str(self.inventories_root), str(target_path))
        self.assertIn(str(target_path), str(response.get("_hint") or ""))
        ui_effects = list(response.get("ui_effects") or [])
        self.assertTrue(
            any(
                effect.get("type") == "open_dataset"
                and str(effect.get("target_path") or "").strip() == str(target_path)
                for effect in ui_effects
                if isinstance(effect, dict)
            ),
            ui_effects,
        )
        self.assertTrue(
            any(
                effect.get("type") == "migration_mode"
                and effect.get("enabled") is False
                for effect in ui_effects
                if isinstance(effect, dict)
            ),
            ui_effects,
        )

    def test_manage_boxes_ignores_dry_run_input(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_box_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "manage_boxes",
                {"action": "add", "count": 2, "dry_run": True},
            )
            self.assertTrue(response["ok"])
            self.assertTrue(response.get("waiting_for_user_confirmation"))
            self.assertEqual("add", response.get("request", {}).get("operation"))


    def test_add_entry_rejects_undeclared_fields_via_schema_validation(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                session_id="session-agent-test",
            )
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": [2, 3],
                    "frozen_at": "2026-02-10",
                    "fields": {
                        "cell_line": "K562",
                        "short_name": "clone-2",
                        "note": "via runner",
                    },
                },
                trace_id="trace-agent-test",
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("short_name", str(response.get("message") or ""))

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, len(current["inventory"]))

    def test_add_entry_staging_supports_alphanumeric_positions(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=PlanStore(),
            )
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": ["A5"],
                    "frozen_at": "2026-02-10",
                    "fields": {
                        "cell_line": "K562",
                    },
                },
            )

            self.assertTrue(response["ok"])
            self.assertTrue(response.get("staged"))

    def test_takeout_requires_entries_payload(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_bad_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("takeout", {"position": 1, "date": "2026-02-10"})
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertTrue(response.get("_hint"))
            self.assertIn("Required", response.get("_hint", ""))

    def test_add_entry_invalid_tool_input_hint_explains_shared_fields(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        payload = {"error_code": "invalid_tool_input"}

        hint = runner._hint_for_error("add_entry", payload)

        self.assertIn("shared `fields` object", hint)
        self.assertIn("Split into multiple add_entry calls", hint)
        self.assertIn("Required", hint)
        self.assertIn("Optional", hint)

    def test_unknown_tool_returns_hint(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("nonexistent_tool", {})

        self.assertFalse(response["ok"])
        self.assertEqual("unknown_tool", response["error_code"])
        self.assertTrue(response.get("_hint"))
        self.assertIn("available tools", response.get("_hint", "").lower())

    def test_bash_requires_non_empty_command(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("bash", {"command": "   ", "description": "run command"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])
        self.assertIn("command", str(response.get("message") or ""))

    def test_bash_requires_non_empty_description(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("bash", {"command": "echo hi", "description": "   "})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])
        self.assertIn("description", str(response.get("message") or ""))

    def test_bash_executes_command_and_returns_raw_output(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        marker = "snowfox_terminal_ok"
        response = runner.run(
            "bash",
            {"command": f"echo {marker}", "description": "echo marker output"},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(0, response.get("exit_code"))
        self.assertIn(marker, str(response.get("raw_output") or ""))
        self.assertIn("Shell engine: bash.", str(response.get("_hint") or ""))
        self.assertIn("Current working directory: migrate", str(response.get("_hint") or ""))

    def test_bash_normalizes_relative_workdir_under_migrate(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "bash",
            {
                "command": "pwd",
                "description": "print cwd",
                "workdir": "output",
            },
        )

        self.assertTrue(response["ok"])
        self.assertIn("Current working directory: migrate/output", str(response.get("_hint") or ""))

    def test_bash_schema_exposes_expected_fields(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        schemas = runner.tool_schemas()
        terminal_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "bash"
            ),
            None,
        )
        if not isinstance(terminal_schema, dict):
            self.fail("bash schema should exist")

        params = terminal_schema.get("function", {}).get("parameters", {})
        self.assertEqual(["command", "description"], params.get("required", []))
        self.assertEqual(
            {"command", "description", "timeout", "workdir"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))

    def test_powershell_schema_exposes_expected_fields(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        schemas = runner.tool_schemas()
        powershell_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "powershell"
            ),
            None,
        )
        if not isinstance(powershell_schema, dict):
            self.fail("powershell schema should exist")

        params = powershell_schema.get("function", {}).get("parameters", {})
        self.assertEqual(["command", "description"], params.get("required", []))
        self.assertEqual(
            {"command", "description", "timeout", "workdir"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))

    def test_bash_rejects_workdir_outside_scope(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "bash",
            {
                "command": "echo should_not_run",
                "description": "verify repository boundary",
                "workdir": "../outside",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("path.escape_detected", response.get("error_code"))

    def test_powershell_rejects_workdir_outside_scope(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "powershell",
            {
                "command": "Write-Output should_not_run",
                "description": "verify repository boundary",
                "workdir": "../outside",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("path.escape_detected", response.get("error_code"))

    def test_bash_timeout_is_milliseconds(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "bash",
            {
                "command": "python -c \"import time; time.sleep(0.5)\"",
                "description": "timeout behavior check",
                "timeout": 10,
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("terminal_timeout", response.get("error_code"))

    def test_bash_unicode_output_does_not_crash_file_ops_service(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "bash",
            {
                "command": "python -c \"print('\\\\u03f5')\"",
                "description": "emit unicode output",
            },
        )
        if response.get("error_code") == "bash_unavailable":
            self.skipTest("bash unavailable in current runtime")
        self.assertNotEqual("file_ops_service_failed", response.get("error_code"))
        self.assertNotEqual("file_ops_invalid_response", response.get("error_code"))

    def test_environment_tools_respect_repo_read_and_migrate_write_scope(self):
        repo_root = self._repo_root()
        migrate_root = repo_root / "migrate"
        migrate_root.mkdir(parents=True, exist_ok=True)
        read_target = repo_root / "README_scope_test.txt"
        read_target.write_text("hello repo", encoding="utf-8")

        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        read_resp = runner.run("fs_read", {"path": "README_scope_test.txt"})
        self.assertTrue(read_resp["ok"])
        self.assertEqual("hello repo", read_resp.get("content"))
        self.assertIn("Last read path: README_scope_test.txt", str(read_resp.get("_hint") or ""))

        denied_write = runner.run("fs_write", {"path": "../README_scope_test_2.txt", "content": "nope"})
        self.assertFalse(denied_write["ok"])
        self.assertEqual("path.escape_detected", denied_write.get("error_code"))
        self.assertIn("Writable workspace root: migrate", str(denied_write.get("_hint") or ""))

        write_resp = runner.run("fs_write", {"path": "migrate/data/input.txt", "content": "hello migrate"})
        self.assertTrue(write_resp["ok"])
        self.assertTrue((migrate_root / "data" / "input.txt").exists())
        self.assertIn("Last write target: migrate/data/input.txt", str(write_resp.get("_hint") or ""))

        list_resp = runner.run("fs_list", {"path": "migrate/data"})
        self.assertTrue(list_resp["ok"])
        names = {entry.get("name") for entry in list(list_resp.get("entries") or [])}
        self.assertIn("input.txt", names)
        self.assertIn("Last listed path: migrate/data", str(list_resp.get("_hint") or ""))

    def test_environment_tools_reject_paths_outside_scope(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("fs_read", {"path": "../outside.txt"})
        self.assertFalse(response["ok"])
        self.assertEqual("path.escape_detected", response.get("error_code"))

    def test_python_run_is_unknown_tool(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("python_run", {"code": "print('x')"})
        self.assertFalse(response["ok"])
        self.assertEqual("unknown_tool", response.get("error_code"))

    def test_fs_write_requires_overwrite_for_existing_destination(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        first = runner.run("fs_write", {"path": "migrate/data/file.txt", "content": "first"})
        second = runner.run("fs_write", {"path": "migrate/data/file.txt", "content": "second"})
        third = runner.run("fs_write", {"path": "migrate/data/file.txt", "content": "second", "overwrite": True})
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual("file_exists_and_overwrite_false", second.get("error_code"))
        self.assertTrue(third["ok"])

    def test_fs_write_normalizes_relative_path_under_migrate(self):
        target = self._repo_root() / "migrate" / "output" / "demo.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("fs_write", {"path": "output/demo.txt", "content": "hello"})

        self.assertTrue(response["ok"])
        self.assertTrue(target.is_file())
        self.assertEqual("hello", target.read_text(encoding="utf-8"))
        self.assertIn("Last write target: migrate/output/demo.txt", str(response.get("_hint") or ""))

    def test_fs_copy_is_unknown_tool(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("fs_copy", {"src": "a", "dst": "b"})
        self.assertFalse(response["ok"])
        self.assertEqual("unknown_tool", response.get("error_code"))

    def test_fs_edit_replaces_single_match(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("alpha OLD omega", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes.txt",
                "oldString": "OLD",
                "newString": "NEW",
            },
        )
        self.assertTrue(response["ok"])
        self.assertEqual(1, response.get("match_count"))
        self.assertEqual(False, response.get("replace_all"))
        self.assertEqual("alpha NEW omega", target.read_text(encoding="utf-8"))

    def test_fs_edit_normalizes_bare_filename_under_migrate(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("alpha OLD omega", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run(
            "fs_edit",
            {
                "filePath": "notes.txt",
                "oldString": "OLD",
                "newString": "NEW",
            },
        )

        self.assertTrue(response["ok"])
        self.assertEqual("alpha NEW omega", target.read_text(encoding="utf-8"))
        self.assertIn("Last edited file: migrate/notes.txt", str(response.get("_hint") or ""))

    def test_fs_edit_ambiguous_match_when_replace_all_false(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("A OLD B OLD C", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes.txt",
                "oldString": "OLD",
                "newString": "NEW",
                "replaceAll": False,
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("ambiguous_match", response.get("error_code"))
        self.assertIn("replaceAll", str(response.get("message") or ""))
        self.assertEqual("A OLD B OLD C", target.read_text(encoding="utf-8"))

    def test_fs_edit_replace_all_replaces_every_match(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("A OLD B OLD C", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes.txt",
                "oldString": "OLD",
                "newString": "NEW",
                "replaceAll": True,
            },
        )
        self.assertTrue(response["ok"])
        self.assertEqual(2, response.get("match_count"))
        self.assertEqual(True, response.get("replace_all"))
        self.assertEqual("A NEW B NEW C", target.read_text(encoding="utf-8"))

    def test_fs_edit_returns_not_found_when_old_string_missing(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("hello world", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes.txt",
                "oldString": "absent",
                "newString": "NEW",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("old_string_not_found", response.get("error_code"))

    def test_fs_edit_rejects_identical_old_and_new_strings(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("OLD", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes.txt",
                "oldString": "OLD",
                "newString": "OLD",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response.get("error_code"))
        self.assertIn("must differ", str(response.get("message") or ""))

    def test_fs_edit_rejects_absolute_file_path(self):
        target = self._repo_root() / "migrate" / "notes.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("OLD", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": str(target.resolve()),
                "oldString": "OLD",
                "newString": "NEW",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response.get("error_code"))

    def test_fs_edit_rejects_write_outside_migrate(self):
        outside = self._repo_root() / "inventories" / "_fake" / "outside_edit_target.txt"
        outside.write_text("OLD", encoding="utf-8")
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        try:
            response = runner.run(
                "fs_edit",
                {
                    "filePath": "inventories/_fake/outside_edit_target.txt",
                    "oldString": "OLD",
                    "newString": "NEW",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("path.scope_write_denied", response.get("error_code"))
        finally:
            with suppress(FileNotFoundError):
                outside.unlink()

    def test_fs_edit_rejects_non_utf8_files(self):
        target = self._repo_root() / "migrate" / "notes_latin1.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes("caf\xe9 OLD".encode("latin-1"))
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_edit",
            {
                "filePath": "migrate/notes_latin1.txt",
                "oldString": "OLD",
                "newString": "NEW",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("file_read_failed", response.get("error_code"))

    def test_search_records_rejects_keyword_mode_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "position": 10,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "K562", "mode": "keyword"})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_search_records_rejects_invalid_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_mode_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 3,
                        "parent_cell_line": "NCCIT",
                        "short_name": "nccit-abc",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "NCCIT", "mode": "bad-mode"})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_search_records_allows_empty_query_and_wildcard(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_empty_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "NCCIT",
                            "short_name": "active-rec",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            empty_response = runner.run("search_records", {})
            wildcard_response = runner.run("search_records", {"query": "*"})

            self.assertTrue(empty_response["ok"])
            self.assertEqual(1, empty_response["result"]["total_count"])
            self.assertEqual(1, empty_response["result"]["records"][0]["id"])
            self.assertEqual("", empty_response["result"]["normalized_query"])
            self.assertTrue(wildcard_response["ok"])
            self.assertEqual(
                empty_response["result"]["total_count"],
                wildcard_response["result"]["total_count"],
            )
            self.assertEqual("", wildcard_response["result"]["normalized_query"])

    def test_search_records_supports_structured_slot_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_slot_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 2,
                        "position": 15,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "k562", "box": 2, "position": 15})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])

    def test_search_records_supports_alphanumeric_slot_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_slot_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric(
                    [
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "k562-a",
                            "box": 2,
                            "position": 15,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "k562", "box": 2, "position": "B6"})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])

    def test_search_records_supports_location_shortcut_query(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_shortcut_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 3,
                        "parent_cell_line": "NCCIT",
                        "short_name": "nccit-a",
                        "box": 2,
                        "position": 15,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "2:15"})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(3, response["result"]["records"][0]["id"])
            self.assertEqual("2:15", response["result"]["applied_filters"]["query_shortcut"])

    def test_search_records_default_includes_active_and_inactive_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_active_default_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "active",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [1]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "K562"})

            self.assertTrue(response["ok"])
            self.assertEqual(2, response["result"]["total_count"])
            self.assertEqual([2, 1], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("all", response["result"]["applied_filters"]["status"])
            self.assertEqual("frozen_at", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("desc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("last", response["result"]["applied_filters"]["sort_nulls"])

            active_only = runner.run("search_records", {"query": "K562", "status": "active"})
            self.assertTrue(active_only["ok"])
            self.assertEqual([1], [item.get("id") for item in active_only["result"]["records"]])
            self.assertEqual("active", active_only["result"]["applied_filters"]["status"])

            inactive_only = runner.run("search_records", {"query": "K562", "status": "inactive"})
            self.assertTrue(inactive_only["ok"])
            self.assertEqual([2], [item.get("id") for item in inactive_only["result"]["records"]])
            self.assertEqual("inactive", inactive_only["result"]["applied_filters"]["status"])

    def test_search_records_supports_explicit_sorting(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_sort_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "box2",
                            "box": 2,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "box1-p2",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "box1-p1",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "search_records",
                {
                    "query": "K562",
                    "sort_by": "box",
                    "sort_order": "asc",
                },
            )

            self.assertTrue(response["ok"])
            self.assertEqual([1, 2, 3], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("box", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("asc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("last", response["result"]["applied_filters"]["sort_nulls"])

    def test_search_records_rejects_invalid_sort_by(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_sort_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "search_records",
                {"query": "NCCIT", "sort_by": "created_at"},
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("sort_by", str(response.get("message") or ""))

    def test_generate_stats_supports_optional_box_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_stats_box_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [1],
                                }
                            ],
                        },
                        make_record(3, box=2, position=1),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("generate_stats", {"box": 1})

            self.assertTrue(response["ok"])
            result = response.get("result") or {}
            self.assertEqual(1, result.get("box"))
            self.assertEqual(1, result.get("box_occupied"))
            self.assertEqual(1, result.get("box_record_count"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1], ids)
            self.assertNotIn("occupancy_rate", result)
            self.assertNotIn("stats", result)

    def test_generate_stats_include_inactive_adds_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_stats_box_inactive_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [1]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("generate_stats", {"box": 1, "include_inactive": True})

            self.assertTrue(response["ok"])
            result = response.get("result") or {}
            self.assertEqual(1, result.get("box_occupied"))
            self.assertEqual(2, result.get("box_record_count"))
            self.assertTrue(result.get("include_inactive"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2], ids)
            self.assertNotIn("occupancy_rate", result)

    def test_generate_stats_rejects_full_records_for_gui_flag(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("generate_stats", {"full_records_for_gui": True})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response.get("error_code"))
        self.assertIn("full_records_for_gui", str(response.get("message") or ""))

    def test_recent_frozen_replaces_recent_filters(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_recent_search_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "old",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2025-01-01",
                    },
                    {
                        "id": 2,
                        "parent_cell_line": "K562",
                        "short_name": "new",
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("recent_frozen", {"basis": "count", "value": 1})

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["count"])
            self.assertEqual("new", response["result"]["records"][0]["short_name"])

    def test_search_records_rejects_mixed_recent_and_query_filters(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("search_records", {"query": "K562", "recent_count": 1})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])

    def test_query_takeout_events_summary_mode_replaces_collect_timeline(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_timeline_summary_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "parent_cell_line": "K562",
                        "short_name": "A",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("query_takeout_events", {"range": "all"})

            self.assertTrue(response["ok"])
            self.assertIn("summary", response["result"])

    def test_query_takeout_events_summary_rejects_event_filters(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("query_takeout_events", {"range": "all", "action": "takeout"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])

    def test_list_audit_timeline_returns_only_persisted_audit_rows(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_audit_timeline_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            # Creating filesystem backups alone should not inject synthetic rows.
            create_yaml_backup(str(yaml_path), keep=0)

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("list_audit_timeline", {})

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(50, result.get("limit"))
            self.assertEqual(0, result.get("offset"))
            items = list(result.get("items") or [])
            self.assertGreaterEqual(len(items), 1)
            self.assertFalse(any(str(item.get("action")) == "backup" for item in items))

    def test_rollback_rejects_backup_path_not_in_backup_events(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_rollback_backup_rows_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            backup_path = create_yaml_backup(str(yaml_path))
            self.assertTrue(Path(str(backup_path)).exists())

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "rollback",
                {"backup_path": str(backup_path)},
            )

            self.assertFalse(response["ok"])
            self.assertEqual("backup_not_in_timeline", response.get("error_code"))

    def test_rollback_rejects_backup_event_without_audit_seq(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_rollback_seq_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            backup_path = resolve_request_backup_path(
                yaml_path=str(yaml_path),
                execution_mode="execute",
                dry_run=False,
                request_backup_path=None,
                backup_event_source="tests.rollback_seq_guard",
            )
            backup_abs = str(Path(str(backup_path)).resolve())

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            touched = False
            for row in rows:
                if str(row.get("action") or "").strip().lower() != "backup":
                    continue
                candidate = str(Path(str(row.get("backup_path") or "")).resolve()) if row.get("backup_path") else ""
                if candidate != backup_abs:
                    continue
                row.pop("audit_seq", None)
                touched = True
                break
            self.assertTrue(touched)
            audit_path.write_text(
                "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows),
                encoding="utf-8",
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "rollback",
                {"backup_path": backup_abs},
            )

            self.assertFalse(response["ok"])
            self.assertEqual("missing_audit_seq", response.get("error_code"))

    def test_add_entry_rejects_alias_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "add_entry",
                {
                    "cell_line": "K562",
                    "short": "alias-test",
                    "box_num": 1,
                    "position": 2,
                    "date": "2026-02-10",
                    "notes": "alias payload",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

            current = load_yaml(str(yaml_path))
            records = current.get("inventory", [])
            self.assertEqual(1, len(records))

    def test_takeout_rejects_id_and_pos_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_thaw_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "takeout",
                {
                    "id": 1,
                    "pos": 1,
                    "thaw_date": "2026-02-10",
                    "action": "takeout",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_move_rejects_target_position_alias(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "move",
                {
                    "id": 1,
                    "pos": 1,
                    "to_pos": 2,
                    "thaw_date": "2026-02-10",
                    "action": "move",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

    def test_takeout_missing_source_returns_hint(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_move_hint_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "takeout",
                {
                    "entries": [{"record_id": 1}],
                    "date": "2026-02-10",
                },
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_box", response.get("message", ""))

    def test_plan_preflight_hint_guides_record_repair_flow(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        payload = {
            "error_code": "plan_preflight_failed",
            "message": "Write blocked: integrity validation failed\n- Record #16 (id=16): invalid cell_line",
            "blocked_items": [
                {
                    "action": "takeout",
                    "record_id": 21,
                    "message": "Write blocked: integrity validation failed\n- Record #16 (id=16): invalid cell_line",
                }
            ],
        }

        hint = runner._hint_for_error("takeout", payload)
        self.assertIn("get_raw_entries", hint)
        self.assertIn("edit_entry", hint)
        self.assertIn("16", hint)

    def test_plan_preflight_hint_guides_execute_prerequisite_flow(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        payload = {
            "error_code": "plan_preflight_failed",
            "message": (
                "All operations rejected by validation: "
                "move 212 @ Box 5:1 -> Box 3:46: target box 3 position 46 is occupied by record #173; "
                "takeout 153 @ Box 3:20: Record ID 153 source mismatch: requested Box 3:20, current Box 3:27"
            ),
            "blocked_items": [
                {
                    "action": "move",
                    "record_id": 212,
                    "message": "target box 3 position 46 is occupied by record #173",
                },
                {
                    "action": "takeout",
                    "record_id": 153,
                    "message": "Record ID 153 source mismatch: requested Box 3:20, current Box 3:27",
                },
            ],
        }

        hint = runner._hint_for_error("move", payload)
        self.assertIn("staged_plan", hint)
        self.assertIn("only staged, not executed", hint)
        self.assertIn("plan tab", hint.lower())
        self.assertIn("do not reassign a different slot", hint.lower())
        self.assertNotIn("edit_entry", hint)

    def test_tool_schemas_expose_required_fields(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        schemas = runner.tool_schemas()
        names = [item.get("function", {}).get("name") for item in schemas]

        self.assertIn("add_entry", names)
        add_entry_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "add_entry"),
            None,
        )
        if not isinstance(add_entry_schema, dict):
            self.fail("add_entry schema should exist")
        add_entry_params = add_entry_schema.get("function", {}).get("parameters", {})
        add_entry_desc = str(add_entry_schema.get("function", {}).get("description") or "").lower()
        self.assertIn("shared", add_entry_desc)
        self.assertIn("fields", add_entry_desc)
        self.assertIn("positions", add_entry_params.get("required", []))
        self.assertIn("fields", add_entry_params.get("required", []))
        add_entry_positions = (add_entry_params.get("properties") or {}).get("positions", {})
        self.assertEqual("array", add_entry_positions.get("type"))
        self.assertEqual("integer", (add_entry_positions.get("items") or {}).get("type"))
        add_entry_fields = (add_entry_params.get("properties") or {}).get("fields", {})
        self.assertEqual("object", add_entry_fields.get("type"))
        self.assertEqual(False, add_entry_fields.get("additionalProperties"))
        self.assertIn("cell_line", (add_entry_fields.get("properties") or {}))
        self.assertIn("note", (add_entry_fields.get("properties") or {}))
        self.assertIn("cell_line", add_entry_fields.get("required", []))
        self.assertNotIn("dry_run", (add_entry_params.get("properties") or {}))

        self.assertIn("fs_edit", names)
        fs_edit_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "fs_edit"),
            None,
        )
        if not isinstance(fs_edit_schema, dict):
            self.fail("fs_edit schema should exist")
        edit_text_params = fs_edit_schema.get("function", {}).get("parameters", {})
        self.assertEqual(
            ["filePath", "oldString", "newString"],
            edit_text_params.get("required", []),
        )
        self.assertEqual(
            {"filePath", "oldString", "newString", "replaceAll"},
            set((edit_text_params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, edit_text_params.get("additionalProperties"))

        search_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "search_records"
            ),
            None,
        )
        if not isinstance(search_schema, dict):
            self.fail("search_records schema should exist")
        search_params = search_schema.get("function", {}).get("parameters", {})
        self.assertEqual([], search_params.get("required", []))
        self.assertIn("box", (search_params.get("properties") or {}))
        self.assertIn("position", (search_params.get("properties") or {}))
        self.assertIn("status", (search_params.get("properties") or {}))
        self.assertIn("sort_by", (search_params.get("properties") or {}))
        self.assertIn("sort_order", (search_params.get("properties") or {}))
        self.assertNotIn("active_only", (search_params.get("properties") or {}))
        mode_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("mode", {})
        )
        self.assertEqual(["fuzzy", "exact", "keywords"], mode_schema.get("enum"))
        sort_by_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("sort_by", {})
        )
        self.assertEqual(["box", "position", "frozen_at", "id"], sort_by_schema.get("enum"))
        sort_order_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("sort_order", {})
        )
        self.assertEqual(["asc", "desc"], sort_order_schema.get("enum"))
        takeout_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "takeout"
            ),
            None,
        )
        if not isinstance(takeout_schema, dict):
            self.fail("takeout schema should exist")
        takeout_properties = (
            takeout_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )
        takeout_required = (
            takeout_schema.get("function", {})
            .get("parameters", {})
            .get("required", [])
        )
        self.assertIn("entries", takeout_required)
        self.assertIn("date", takeout_required)
        takeout_entry_props = ((takeout_properties.get("entries") or {}).get("items") or {}).get(
            "properties",
            {},
        )
        self.assertIn("from_box", takeout_entry_props)
        self.assertIn("from_position", takeout_entry_props)
        self.assertEqual("integer", (takeout_entry_props.get("from_position") or {}).get("type"))
        self.assertNotIn("dry_run", takeout_properties)

        self.assertIn("recent_frozen", names)
        self.assertIn("query_takeout_events", names)
        self.assertNotIn("collect_timeline", names)
        self.assertNotIn("list_staged", names)
        self.assertNotIn("remove_staged", names)
        self.assertNotIn("clear_staged", names)
        self.assertIn("staged_plan", names)

        staged_plan_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "staged_plan"),
            None,
        )
        if not isinstance(staged_plan_schema, dict):
            self.fail("staged_plan schema should exist")
        self.assertIn(
            "action",
            staged_plan_schema.get("function", {}).get("parameters", {}).get("required", []),
        )

        generate_stats_schema = next(
            (item for item in schemas if item.get("function", {}).get("name") == "generate_stats"),
            None,
        )
        if not isinstance(generate_stats_schema, dict):
            self.fail("generate_stats schema should exist")
        self.assertIn(
            "box",
            generate_stats_schema.get("function", {}).get("parameters", {}).get("properties", {}),
        )
        self.assertIn(
            "include_inactive",
            generate_stats_schema.get("function", {}).get("parameters", {}).get("properties", {}),
        )

        for tool_name in [
            "move",
            "takeout",
            "manage_boxes",
            "staged_plan",
        ]:
            schema_item = next(
                (item for item in schemas if item.get("function", {}).get("name") == tool_name),
                None,
            )
            if not isinstance(schema_item, dict):
                self.fail(f"{tool_name} schema should exist")
            self.assertNotIn(
                "dry_run",
                schema_item.get("function", {}).get("parameters", {}).get("properties", {}),
            )

    def test_tool_schemas_positions_follow_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_schema_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            schemas = runner.tool_schemas()

            def _schema(name):
                return next(
                    (item for item in schemas if item.get("function", {}).get("name") == name),
                    None,
                )

            add_entry_schema = _schema("add_entry")
            if not isinstance(add_entry_schema, dict):
                self.fail("add_entry schema should exist")
            add_positions = (
                add_entry_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("positions", {})
            )
            self.assertEqual("array", add_positions.get("type"))
            self.assertEqual("string", (add_positions.get("items") or {}).get("type"))

            search_schema = _schema("search_records")
            if not isinstance(search_schema, dict):
                self.fail("search_records schema should exist")
            search_position = (
                search_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("position", {})
            )
            self.assertEqual("string", search_position.get("type"))

            takeout_schema = _schema("takeout")
            if not isinstance(takeout_schema, dict):
                self.fail("takeout schema should exist")
            from_position = (
                takeout_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("entries", {})
                .get("items", {})
                .get("properties", {})
                .get("from_position", {})
            )
            self.assertEqual("string", from_position.get("type"))

    def test_tool_schemas_include_dynamic_custom_fields_for_add_and_edit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_schema_custom_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            seeded_record = make_record(1, box=1, position=1)
            seeded_record["passage_number"] = 1
            custom_data = make_data([seeded_record])
            custom_data.setdefault("meta", {}).update(
                {
                    "cell_line_required": False,
                    "custom_fields": [
                        {"key": "passage_number", "label": "Passage", "type": "int", "required": True},
                        {"key": "source_batch", "label": "Source Batch", "type": "str", "required": False},
                    ],
                }
            )
            write_yaml(
                custom_data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            schemas = runner.tool_schemas()

            add_schema = next(
                (item for item in schemas if item.get("function", {}).get("name") == "add_entry"),
                None,
            )
            if not isinstance(add_schema, dict):
                self.fail("add_entry schema should exist")
            add_fields = (
                add_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("fields", {})
            )
            add_field_props = add_fields.get("properties", {})
            self.assertIn("passage_number", add_field_props)
            self.assertEqual("integer", add_field_props["passage_number"].get("type"))
            self.assertIn("source_batch", add_field_props)
            self.assertEqual("string", add_field_props["source_batch"].get("type"))
            self.assertIn("passage_number", add_fields.get("required", []))
            self.assertNotIn("cell_line", add_fields.get("required", []))
            self.assertIn(
                "fields",
                add_schema.get("function", {}).get("parameters", {}).get("required", []),
            )

            edit_schema = next(
                (item for item in schemas if item.get("function", {}).get("name") == "edit_entry"),
                None,
            )
            if not isinstance(edit_schema, dict):
                self.fail("edit_entry schema should exist")
            edit_fields = (
                edit_schema.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("fields", {})
            )
            edit_field_props = edit_fields.get("properties", {})
            self.assertIn("frozen_at", edit_field_props)
            self.assertIn("passage_number", edit_field_props)
            self.assertEqual("integer", edit_field_props["passage_number"].get("type"))
            self.assertEqual("object", edit_fields.get("type"))
            self.assertEqual(1, edit_fields.get("minProperties"))
            self.assertEqual(False, edit_fields.get("additionalProperties"))

    def test_add_entry_rejects_positions_string_payload(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_add_schema_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "add_entry",
                {
                    "box": 1,
                    "positions": "2,3",
                    "frozen_at": "2026-02-10",
                    "fields": {"cell_line": "K562"},
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("positions", str(response.get("message") or ""))

    def test_takeout_rejects_string_position_in_numeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_takeout_numeric_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "takeout",
                {
                    "entries": [
                        {
                            "record_id": 1,
                            "from_box": 1,
                            "from_position": "1",
                        }
                    ],
                    "date": "2026-02-10",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_position", str(response.get("message") or ""))

    def test_takeout_rejects_integer_position_in_alphanumeric_layout(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_takeout_alpha_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data_alphanumeric([make_record(1, box=1, position=5)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "takeout",
                {
                    "entries": [
                        {
                            "record_id": 1,
                            "from_box": 1,
                            "from_position": 5,
                        }
                    ],
                    "date": "2026-02-10",
                },
            )
            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])
            self.assertIn("from_position", str(response.get("message") or ""))

    def test_rollback_tool_schema_mentions_explicit_backup_path(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        rollback_schema = next(
            (
                item
                for item in runner.tool_schemas()
                if item.get("function", {}).get("name") == "rollback"
            ),
            None,
        )
        if not isinstance(rollback_schema, dict):
            self.fail("rollback schema should exist")
        description = str(rollback_schema.get("function", {}).get("description") or "").lower()

        self.assertIn("backup_path", description)
        self.assertIn("explicit", description)

    def test_staged_plan_list_remove_clear(self):
        from lib.plan_store import PlanStore

        store = PlanStore()
        store.add([
            {
                "action": "takeout",
                "record_id": 1,
                "box": 1,
                "position": 5,
                "source": "ai",
            },
            {
                "action": "move",
                "record_id": 2,
                "box": 1,
                "position": 6,
                "to_position": 7,
                "source": "ai",
            },
        ])
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path, plan_store=store)

        list_resp = runner.run("staged_plan", {"action": "list"})
        self.assertTrue(list_resp["ok"])
        self.assertEqual(2, list_resp["result"]["count"])
        items = list_resp["result"]["items"]
        self.assertEqual([5], items[0]["positions"])
        self.assertEqual([6], items[1]["positions"])
        self.assertEqual(7, items[1]["to_position"])
        self.assertNotIn("position", items[0])
        self.assertNotIn("position", items[1])

        remove_resp = runner.run("staged_plan", {"action": "remove", "index": 0})
        self.assertTrue(remove_resp["ok"])
        self.assertEqual(1, remove_resp["result"]["removed"])

        clear_resp = runner.run("staged_plan", {"action": "clear"})
        self.assertTrue(clear_resp["ok"])
        self.assertEqual(1, clear_resp["result"]["cleared_count"])

    def test_staged_plan_list_returns_all_add_positions(self):
        from lib.plan_item_factory import build_add_plan_item
        from lib.plan_store import PlanStore

        store = PlanStore()
        store.add(
            [
                build_add_plan_item(
                    box=1,
                    positions=[5, 6, 7],
                    frozen_at="2026-02-10",
                    fields={"cell_line": "K562"},
                    source="ai",
                )
            ]
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path, plan_store=store)

        list_resp = runner.run("staged_plan", {"action": "list"})
        self.assertTrue(list_resp["ok"])
        self.assertEqual(1, list_resp["result"]["count"])
        entry = list_resp["result"]["items"][0]
        self.assertEqual("add", entry["action"])
        self.assertEqual([5, 6, 7], entry["positions"])
        self.assertNotIn("position", entry)

    def test_item_desc_add_includes_all_positions(self):
        from lib.plan_item_factory import build_add_plan_item

        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        item = build_add_plan_item(
            box=1,
            positions=[5, 6, 7],
            frozen_at="2026-02-10",
            fields={"cell_line": "K562"},
            source="ai",
        )
        desc = runner._item_desc(item)
        self.assertIn("5,6,7", desc)

    def test_staged_plan_remove_requires_index(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("staged_plan", {"action": "remove"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])


    def test_agent_tool_runner_i18n_keys_covered_in_en_and_zh(self):
        required_keys = _collect_agent_tool_runner_i18n_keys()
        i18n_dir = ROOT / "app_gui" / "i18n" / "translations"

        for locale in ("en.json", "zh-CN.json"):
            data = json.loads((i18n_dir / locale).read_text(encoding="utf-8"))
            available = _flatten_leaf_keys(data.get("agentToolRunner", {}))
            missing = sorted(required_keys - available)
            self.assertEqual(
                [],
                missing,
                f"{locale} missing agentToolRunner keys: {missing}",
            )

    def test_removed_tools_are_unknown(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        for name in (
            "collect_timeline",
            "manage_boxes_add",
            "manage_boxes_remove",
            "manage_staged",
            "staged_list",
            "staged_remove",
            "staged_clear",
            "query_takeout_summary",
            "list_staged",
            "remove_staged",
            "clear_staged",
            "edit",
        ):
            response = runner.run(name, {})
            self.assertFalse(response["ok"])
            self.assertEqual("unknown_tool", response["error_code"])


class EditEntryToolRunnerTests(ManagedPathTestCase):
    """Integration tests for edit_entry through AgentToolRunner."""

    def test_edit_entry_stages_plan_item(self):
        """edit_entry should produce a plan item with real position from record."""
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=2, position=15)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore
            store = PlanStore()
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=store,
            )

            response = runner.run(
                "edit_entry",
                {"record_id": 1, "fields": {"cell_line": "HeLa"}},
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, store.count())
            item = store.list_items()[0]
            self.assertEqual("edit", item["action"])
            self.assertEqual(1, item["record_id"])
            self.assertEqual(2, item["box"])
            self.assertEqual(15, item["position"])
            self.assertEqual("ai", item["source"])
            self.assertEqual({"cell_line": "HeLa"}, item["payload"]["fields"])

    def test_edit_entry_missing_record_id(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"fields": {"note": "x"}})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_missing_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"record_id": 1})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_empty_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("edit_entry", {"record_id": 1, "fields": {}})

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response["error_code"])

    def test_edit_entry_listed_in_tools(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        self.assertIn("edit_entry", set(runner.list_tools()))

    def test_edit_entry_in_tool_schemas(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        schemas = runner.tool_schemas()
        names = [item.get("function", {}).get("name") for item in schemas]
        self.assertIn("edit_entry", names)

    # --- cell_line alias tests ---


if __name__ == "__main__":
    unittest.main()
