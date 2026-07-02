"""Split from test_agent_tool_runner.py."""

from tests.integration.agent._agent_tool_runner_shared import *  # noqa: F401,F403


class AgentToolRunnerToolsTests(AgentToolRunnerBaseCase):
    def test_list_tools_contains_core_entries(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        names = set(runner.list_tools())
        self.assertIn("search_records", names)
        self.assertIn("filter_records", names)
        self.assertIn("recent_frozen", names)
        self.assertIn("query_takeout_events", names)
        self.assertIn("list_audit_timeline", names)
        self.assertIn("add_entry", names)
        self.assertIn("takeout", names)
        self.assertIn("move", names)
        self.assertIn("shell", names)
        self.assertNotIn("bash", names)
        self.assertNotIn("powershell", names)
        self.assertIn("use_skill", names)
        self.assertIn("fs_list", names)
        self.assertIn("fs_read", names)
        self.assertIn("fs_write", names)
        self.assertIn("fs_copy", names)
        self.assertIn("fs_edit", names)
        self.assertNotIn("edit", names)
        self.assertIn("validate", names)
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
        self.assertIn("filter_records", names)
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
        self.assertIn("filter_records", names)
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
        ref_docs = list(response.get("reference_documents") or [])
        shared_refs = list(response.get("shared_references") or [])
        shared_ref_docs = list(response.get("shared_reference_documents") or [])
        assets = list(response.get("assets") or [])
        self.assertIn("agent_skills/migration/references/runbook_en.md", refs)
        self.assertIn("agent_skills/shared/references/schema_context.md", shared_refs)
        self.assertIn("agent_skills/migration/assets/acceptance_checklist_en.md", assets)
        self.assertTrue(any(doc.get("path") == "agent_skills/migration/references/runbook_en.md" for doc in ref_docs))
        self.assertTrue(any("fs_copy" in str(doc.get("content") or "") for doc in ref_docs))
        self.assertTrue(any(doc.get("path") == "agent_skills/shared/references/schema_context.md" for doc in shared_ref_docs))

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
        self.assertIn("snowfox-system", list(response.get("available_skills") or []))
        self.assertIn("yaml-repair", list(response.get("available_skills") or []))

    def test_use_skill_returns_snowfox_system_skill_body_and_resources(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        response = runner.run("use_skill", {"skill_name": "snowfox-system"})

        self.assertTrue(response["ok"])
        self.assertEqual("snowfox-system", response.get("skill_name"))
        self.assertIn("architecture", str(response.get("description") or "").lower())
        self.assertIn("Core Workflow", str(response.get("instructions_markdown") or ""))
        refs = list(response.get("references") or [])
        ref_docs = list(response.get("reference_documents") or [])
        self.assertIn("agent_skills/snowfox-system/references/architecture_map.md", refs)
        self.assertNotIn("agent_skills/snowfox-system/references/repo_sources.md", refs)
        self.assertTrue(
            any(
                doc.get("path") == "agent_skills/snowfox-system/references/user_workflows.md"
                for doc in ref_docs
            )
        )
        self.assertFalse(
            any(
                doc.get("path") == "agent_skills/snowfox-system/references/repo_sources.md"
                for doc in ref_docs
            )
        )

    def test_unknown_tool_returns_hint(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("nonexistent_tool", {})

        self.assertFalse(response["ok"])
        self.assertEqual("unknown_tool", response["error_code"])
        self.assertTrue(response.get("_hint"))
        self.assertIn("available tools", response.get("_hint", "").lower())

    def test_tool_schemas_reuses_yaml_context_for_all_tools(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

        with patch.object(runner, "_load_document", wraps=runner._load_document) as load_document:
            schemas = runner.tool_schemas()

        self.assertGreater(len(schemas), 1)
        # meta/layout/inventory are dispatched from a single document load,
        # so building schemas for every tool reads the YAML only once.
        self.assertEqual(1, load_document.call_count)

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
        self.assertIn("box", add_entry_params.get("required", []))
        self.assertIn("positions", add_entry_params.get("required", []))
        self.assertIn("stored_at", add_entry_params.get("required", []))
        self.assertNotIn("fields", add_entry_params.get("required", []))
        add_entry_positions = (add_entry_params.get("properties") or {}).get("positions", {})
        self.assertEqual("array", add_entry_positions.get("type"))
        self.assertEqual("integer", (add_entry_positions.get("items") or {}).get("type"))
        add_entry_fields = (add_entry_params.get("properties") or {}).get("fields", {})
        self.assertEqual("object", add_entry_fields.get("type"))
        self.assertEqual(False, add_entry_fields.get("additionalProperties"))
        self.assertIn("note", (add_entry_fields.get("properties") or {}))
        self.assertNotIn("cell_line", (add_entry_fields.get("properties") or {}))
        self.assertEqual([], add_entry_fields.get("required", []))
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
        self.assertEqual(["box", "position", "stored_at", "id"], sort_by_schema.get("enum"))
        sort_order_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("sort_order", {})
        )
        self.assertEqual(["asc", "desc"], sort_order_schema.get("enum"))
        filter_schema = next(
            (
                item
                for item in schemas
                if item.get("function", {}).get("name") == "filter_records"
            ),
            None,
        )
        if not isinstance(filter_schema, dict):
            self.fail("filter_records schema should exist")
        filter_params = filter_schema.get("function", {}).get("parameters", {})
        self.assertEqual([], filter_params.get("required", []))
        self.assertIn("keyword", (filter_params.get("properties") or {}))
        self.assertIn("column_filters", (filter_params.get("properties") or {}))
        self.assertIn("sort_by", (filter_params.get("properties") or {}))
        self.assertIn("sort_order", (filter_params.get("properties") or {}))
        self.assertIn("limit", (filter_params.get("properties") or {}))
        self.assertEqual(
            ["asc", "desc"],
            ((filter_params.get("properties") or {}).get("sort_order") or {}).get("enum"),
        )
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
            self.assertIn("stored_at", edit_field_props)
            self.assertNotIn("frozen_at", edit_field_props)
            self.assertIn("passage_number", edit_field_props)
            self.assertEqual("integer", edit_field_props["passage_number"].get("type"))
            self.assertEqual("object", edit_fields.get("type"))
            self.assertEqual(1, edit_fields.get("minProperties"))
            self.assertEqual(False, edit_fields.get("additionalProperties"))

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


