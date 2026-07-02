"""Split from test_agent_tool_runner.py."""

from tests.integration.agent._agent_tool_runner_shared import *  # noqa: F401,F403


class AgentToolRunnerMigrationTests(AgentToolRunnerBaseCase):
    def test_validate_returns_file_not_found_when_missing(self):
        candidate = self._migration_output_path()
        candidate.unlink(missing_ok=True)
        json_sidecars_before = sorted(path.name for path in candidate.parent.glob("*.json"))
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate", {"path": "migrate/output/ln2_inventory.yaml"})

        self.assertFalse(response["ok"])
        self.assertEqual("file_not_found", response.get("error_code"))
        self.assertIn("YAML file not found", str(response.get("message") or ""))
        self.assertIn("migrate/output/ln2_inventory.yaml", str(response.get("_hint") or ""))
        self.assertEqual(
            json_sidecars_before,
            sorted(path.name for path in candidate.parent.glob("*.json")),
        )

    def test_validate_returns_ok_when_output_yaml_is_valid(self):
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
        json_sidecars_before = sorted(path.name for path in candidate.parent.glob("*.json"))
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate", {"path": "migrate/output/ln2_inventory.yaml"})

        self.assertTrue(response["ok"])
        report = response.get("report") or {}
        self.assertEqual(0, report.get("error_count"))
        self.assertEqual(0, report.get("warning_count"))
        self.assertEqual("document", report.get("mode"))
        self.assertIn("migrate/output/ln2_inventory.yaml", str(response.get("_hint") or ""))
        self.assertEqual(
            json_sidecars_before,
            sorted(path.name for path in candidate.parent.glob("*.json")),
        )

    def test_validate_returns_warning_report_without_failing_document_validation(self):
        candidate = self._migration_output_path()
        candidate.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "  cell_line_options: [K562, HeLa]\n"
                "inventory:\n"
                "  - id: 1\n"
                "    box: 1\n"
                "    position: 1\n"
                "    frozen_at: \"2024-01-01\"\n"
                "    cell_line: H1299\n"
                "    note: null\n"
                "    thaw_events: null\n"
            ),
            encoding="utf-8",
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate", {"path": "migrate/output/ln2_inventory.yaml"})

        self.assertTrue(response["ok"])
        report = response.get("report") or {}
        self.assertEqual(0, report.get("error_count"))
        self.assertGreater(report.get("warning_count") or 0, 0)
        warnings = list(report.get("warnings") or [])
        self.assertTrue(any("not in configured options" in msg for msg in warnings), report)
        self.assertIn("warning", str(response.get("_hint") or "").lower())

    def test_validate_uses_current_inventory_semantics_for_managed_inventory_path(self):
        managed_path = Path(self.fake_yaml_path)
        managed_path.write_text(
            (
                "meta:\n"
                "  box_layout:\n"
                "    rows: 9\n"
                "    cols: 9\n"
                "    box_count: 5\n"
                "    box_numbers: [1, 2, 3, 4, 5]\n"
                "inventory: []\n"
                "color_key: legacy_alias\n"
            ),
            encoding="utf-8",
        )
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("validate", {"path": self._repo_relative_path(self.fake_yaml_path)})

        self.assertTrue(response["ok"], response)
        report = response.get("report") or {}
        self.assertEqual("current_inventory", report.get("mode"))
        self.assertEqual(0, report.get("error_count"))

    def test_validate_rejects_undeclared_box_tag(self):
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

        response = runner.run("validate", {"path": "migrate/output/ln2_inventory.yaml"})

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

    def test_import_migration_output_reads_candidate_from_current_data_root(self):
        data_root = self.install_root.parent / f"{self.install_root.name}_data"
        ensure_data_root_layout(str(data_root))
        set_session_data_root(str(data_root))
        self.addCleanup(lambda: set_session_data_root(str(self.install_root)))

        active_yaml_path = self.ensure_dataset_yaml("_fake_data_root")
        candidate = Path(active_yaml_path).resolve().parents[2] / "migrate" / "output" / "ln2_inventory.yaml"
        candidate.parent.mkdir(parents=True, exist_ok=True)
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

        runner = AgentToolRunner(yaml_path=active_yaml_path)
        response = runner.run(
            "import_migration_output",
            {
                "confirmation_token": "CONFIRM_IMPORT",
                "target_dataset_name": "migrated_data_root_batch",
            },
        )

        self.assertTrue(response["ok"], response)
        target_path = Path(str(response.get("target_path") or ""))
        self.assertTrue(target_path.is_file())
        self.assertIn(str(data_root / "inventories"), str(target_path))

