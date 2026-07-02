"""Split from test_agent_tool_runner.py."""

from tests.integration.agent._agent_tool_runner_shared import *  # noqa: F401,F403


class AgentToolRunnerWriteTests(AgentToolRunnerBaseCase):
    def test_manage_boxes_dry_run_remove_normalizes_aliases_and_preserves_yaml(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_box_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                {
                    "meta": {"box_layout": {"rows": 9, "cols": 9, "box_count": 3}},
                    "inventory": [],
                },
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "manage_boxes",
                {
                    "action": "remove_box",
                    "box": 2,
                    "renumber_mode": "compact",
                    "dry_run": True,
                },
            )
            self.assertTrue(response["ok"])
            self.assertTrue(response.get("dry_run"))
            self.assertFalse(response.get("waiting_for_user_confirmation", False))
            preview = response.get("preview") or {}
            self.assertEqual("remove", preview.get("operation"))
            self.assertEqual("renumber_contiguous", preview.get("renumber_mode"))
            self.assertEqual([1, 2], preview.get("box_numbers_after"))

            current = load_yaml(str(yaml_path))
            self.assertEqual(3, current["meta"]["box_layout"].get("box_count"))


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
                    "fields": {},
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
        self.assertIn("Positions [5, 6, 7]", desc)

    def test_staged_plan_remove_requires_index(self):
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        response = runner.run("staged_plan", {"action": "remove"})

        self.assertFalse(response["ok"])
        self.assertEqual("invalid_tool_input", response["error_code"])




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

    def test_edit_entry_restage_merges_fields_in_plan_store(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(435, box=2, position=15)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore

            store = PlanStore()
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=store,
            )

            first = runner.run(
                "edit_entry",
                {
                    "record_id": 435,
                    "fields": {"stored_at": "2026-02-10"},
                },
            )
            second = runner.run(
                "edit_entry",
                {
                    "record_id": 435,
                    "fields": {"cell_line": "NCCIT"},
                },
            )

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(1, store.count())
            self.assertEqual(
                {
                    "stored_at": "2026-02-10",
                    "cell_line": "NCCIT",
                },
                store.list_items()[0]["payload"]["fields"],
            )

    def test_deferred_stage_preflight_serializes_while_running(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=2, position=15),
                        make_record(2, box=2, position=16),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            from lib.plan_store import PlanStore

            active = 0
            max_active = 0
            calls = []
            lock = threading.Lock()
            first_started = threading.Event()
            release = threading.Event()
            second_completed = threading.Event()

            def preflight_fn(_yaml_path, items, _bridge):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                    calls.append(len(items))
                    reached_two = len(calls) >= 2
                first_started.set()
                release.wait(timeout=1)
                with lock:
                    active -= 1
                if reached_two:
                    second_completed.set()
                return {
                    "ok": True,
                    "blocked": False,
                    "items": [
                        {"item": item, "ok": True, "blocked": False}
                        for item in items
                    ],
                    "stats": {
                        "total": len(items),
                        "ok": len(items),
                        "blocked": 0,
                    },
                }

            store = PlanStore()
            runner = AgentToolRunner(
                yaml_path=str(yaml_path),
                plan_store=store,
                preflight_fn=preflight_fn,
            )

            with patch("agent.tool_runner_staging._STAGE_PREFLIGHT_DEBOUNCE_SECONDS", 0.01):
                first = runner.run(
                    "edit_entry",
                    {"record_id": 1, "fields": {"cell_line": "HeLa"}},
                    trace_id="trace-test",
                )
                self.assertTrue(first["ok"])
                self.assertTrue(first_started.wait(timeout=1))

                second = runner.run(
                    "edit_entry",
                    {"record_id": 2, "fields": {"cell_line": "NCCIT"}},
                    trace_id="trace-test",
                )
                self.assertTrue(second["ok"])
                release.set()

                # Wait deterministically for the rescheduled (second) preflight
                # to run to completion instead of polling on a fixed sleep.
                self.assertTrue(second_completed.wait(timeout=2))

            self.assertEqual(1, max_active)
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(2, calls[-1])

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
