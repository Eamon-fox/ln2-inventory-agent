"""Split from test_agent_tool_runner.py."""

from tests.integration.agent._agent_tool_runner_shared import *  # noqa: F401,F403


class AgentToolRunnerShellFsTests(AgentToolRunnerBaseCase):
    def test_shell_requires_non_empty_command(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("shell", {"command": "   ", "description": "run command"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])
        self.assertIn("command", str(response.get("message") or ""))

    def test_shell_requires_non_empty_description(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("shell", {"command": "echo hi", "description": "   "})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])
        self.assertIn("description", str(response.get("message") or ""))

    def test_shell_executes_command_and_returns_raw_output(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        marker = "snowfox_terminal_ok"
        response = runner.run(
            "shell",
            {"command": f"echo {marker}", "description": "echo marker output"},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(0, response.get("exit_code"))
        self.assertIn(marker, str(response.get("raw_output") or ""))
        self.assertIn("cwd:", str(response.get("_hint") or ""))
        self.assertIn("cwd: repo root", str(response.get("_hint") or ""))

    def test_shell_accepts_explicit_repo_relative_workdir(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "shell",
            {
                "command": "pwd",
                "description": "print cwd",
                "workdir": "migrate/output",
            },
        )

        self.assertTrue(response["ok"])
        self.assertIn("cwd: migrate/output", str(response.get("_hint") or ""))

    def test_shell_persists_current_workdir_between_calls(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        migrate_dir = self._repo_root() / "migrate"
        migrate_dir.mkdir(parents=True, exist_ok=True)

        first = runner.run(
            "shell",
            {"command": "cd migrate", "description": "enter migrate directory"},
        )
        second = runner.run(
            "shell",
            {"command": "pwd", "description": "print current directory"},
        )

        self.assertTrue(first["ok"])
        self.assertEqual("migrate", first.get("current_workdir"))
        self.assertTrue(second["ok"])
        self.assertEqual("migrate", second.get("current_workdir"))
        self.assertIn("cwd: migrate", str(second.get("_hint") or ""))

    def test_shell_rejects_cd_outside_repo_and_keeps_previous_workdir(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        migrate_dir = self._repo_root() / "migrate"
        migrate_dir.mkdir(parents=True, exist_ok=True)
        ok = runner.run("shell", {"command": "cd migrate", "description": "enter migrate directory"})
        denied = runner.run("shell", {"command": "cd .. && cd ..", "description": "leave repository"})

        self.assertTrue(ok["ok"])
        self.assertFalse(denied["ok"])
        self.assertEqual("workdir_out_of_scope", denied.get("error_code"))
        self.assertEqual("migrate", runner._shell_state.current_workdir)

    def test_shell_allows_cd_chain_inside_repo(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        output_dir = self._repo_root() / "migrate" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        response = runner.run(
            "shell",
            {"command": "cd migrate; cd output", "description": "enter output directory"},
        )

        self.assertTrue(response["ok"], response)
        self.assertEqual("migrate/output", response.get("current_workdir"))
        self.assertEqual("migrate/output", runner._shell_state.current_workdir)

    def test_shell_nonzero_exit_still_updates_current_workdir(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        migrate_dir = self._repo_root() / "migrate"
        migrate_dir.mkdir(parents=True, exist_ok=True)

        response = runner.run(
            "shell",
            {"command": "cd migrate; exit 7", "description": "fail after changing directory"},
        )

        self.assertFalse(response["ok"])
        self.assertEqual("terminal_nonzero_exit", response.get("error_code"))
        self.assertEqual("migrate", response.get("current_workdir"))
        self.assertEqual("migrate", runner._shell_state.current_workdir)

    def test_shell_schema_exposes_expected_fields(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        schemas = runner.tool_schemas()
        terminal_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "shell"
            ),
            None,
        )
        if not isinstance(terminal_schema, dict):
            self.fail("shell schema should exist")

        params = terminal_schema.get("function", {}).get("parameters", {})
        self.assertEqual(["command", "description"], params.get("required", []))
        self.assertEqual(
            {"command", "description", "timeout", "workdir", "engine"},
            set((params.get("properties") or {}).keys()),
        )
        self.assertEqual(False, params.get("additionalProperties"))

    def test_corrupt_yaml_returns_error_instead_of_empty_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_corrupt_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            # Invalid YAML that cannot be parsed (unbalanced/broken structure).
            yaml_path.write_text("inventory: [\n  {id: 1, box: : :}\n", encoding="utf-8")

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run("search_records", {"query": "anything"})

            self.assertFalse(response["ok"])
            self.assertEqual("inventory_load_failed", response.get("error_code"))
            # Must NOT silently degrade into an empty successful result.
            self.assertNotIn("result", response)

    def test_corrupt_yaml_document_load_raises_inventory_load_error(self):
        from agent.tool_runner import InventoryLoadError

        with tempfile.TemporaryDirectory(prefix="ln2_agent_corrupt_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            yaml_path.write_text("inventory: [\n  {id: 1, box: : :}\n", encoding="utf-8")

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            with self.assertRaises(InventoryLoadError):
                runner._load_document()
            # Individual dispatchers must not swallow the failure as empty data.
            with self.assertRaises(InventoryLoadError):
                runner._load_inventory()
            with self.assertRaises(InventoryLoadError):
                runner._load_layout()

    def test_shell_rejects_workdir_outside_scope(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "shell",
            {
                "command": "echo should_not_run",
                "description": "verify repository boundary",
                "workdir": "../outside",
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("path.escape_detected", response.get("error_code"))

    def test_shell_timeout_is_milliseconds(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "shell",
            {
                "command": f'"{sys.executable}" -c "import time; time.sleep(0.5)"',
                "description": "timeout behavior check",
                "timeout": 10,
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual("terminal_timeout", response.get("error_code"))

    def test_shell_unicode_output_does_not_crash_file_ops_service(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "shell",
            {
                "command": "python -c \"print('\\\\u03f5')\"",
                "description": "emit unicode output",
            },
        )
        if response.get("error_code") == "shell_unavailable":
            self.skipTest("shell unavailable in current runtime")
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

    def test_fs_copy_copies_file_under_migrate(self):
        source = self._repo_root() / "migrate" / "inputs" / "inventory.yaml"
        target = self._repo_root() / "migrate" / "output" / "ln2_inventory.yaml"
        source.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("meta: {}\ninventory: []\n", encoding="utf-8")
        target.unlink(missing_ok=True)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run(
            "fs_copy",
            {"src": "inputs/inventory.yaml", "dst": "output/ln2_inventory.yaml"},
        )
        self.assertTrue(response["ok"])
        self.assertTrue(target.is_file())
        self.assertEqual(source.read_text(encoding="utf-8"), target.read_text(encoding="utf-8"))
        self.assertIn("Last copy target: migrate/output/ln2_inventory.yaml", str(response.get("_hint") or ""))

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

