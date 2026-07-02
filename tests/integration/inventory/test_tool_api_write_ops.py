"""Split from test_tool_api.py."""

from tests.integration.inventory._tool_api_shared import *  # noqa: F401,F403


class ToolApiWriteOpsTests(ManagedPathTestCase):
    def test_resolve_request_backup_path_appends_backup_audit_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_request_backup_event_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            request_backup = resolve_request_backup_path(
                yaml_path=str(yaml_path),
                execution_mode="execute",
                dry_run=False,
                request_backup_path=None,
                backup_event_source="tests.request_backup",
            )
            self.assertTrue(Path(request_backup).exists())

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("backup", last.get("action"))
            self.assertEqual(str(Path(request_backup).resolve()), str(Path(last.get("backup_path")).resolve()))
            self.assertGreater(int(last.get("audit_seq") or 0), 0)

    def test_resolve_request_backup_path_accepts_relative_path_under_dataset_backups(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_request_backup_relative_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            resolved = resolve_request_backup_path(
                yaml_path=str(yaml_path),
                execution_mode="execute",
                dry_run=False,
                request_backup_path="manual/request-backup.bak",
                backup_event_source="tests.request_backup_relative",
            )

            expected = Path(yaml_path).resolve().parent / "backups" / "manual" / "request-backup.bak"
            self.assertEqual(str(expected.resolve()), str(Path(resolved).resolve()))

    def test_resolve_request_backup_path_rejects_path_outside_dataset_backups(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_request_backup_scope_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            outside = Path(yaml_path).resolve().parent / "manual_invalid_backup.yaml"
            with self.assertRaises(PathPolicyError) as exc:
                resolve_request_backup_path(
                    yaml_path=str(yaml_path),
                    execution_mode="execute",
                    dry_run=False,
                    request_backup_path=str(outside),
                    backup_event_source="tests.request_backup_scope",
                )
            self.assertEqual("path.backup_scope_denied", exc.exception.code)

    def test_tool_add_entry_writes_trace_session_metadata(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_add_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            actor = build_actor_context(
                session_id="sess-test",
                trace_id="trace-test",
            )
            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2, 3],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562", "note": "from test"},
                actor_context=actor,
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["new_id"])
            self.assertEqual([2, 3], result["result"]["new_ids"])

            current = load_yaml(str(yaml_path))
            # Tube-level model: positions [2,3] creates 2 new tube records.
            self.assertEqual(3, len(current["inventory"]))

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            lines = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last = lines[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("tool_add_entry", last["tool_name"])
            self.assertEqual("sess-test", last["session_id"])
            self.assertEqual("trace-test", last["trace_id"])
            self.assertNotIn("actor_type", last)
            self.assertNotIn("actor_id", last)
            self.assertNotIn("channel", last)

    def test_tool_record_takeout_dry_run_no_write(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_dry_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                dry_run=True,
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(1, len(lines))

    def test_tool_record_takeout_blocks_agent_write_without_execute_mode(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_gate_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            blocked = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                source="agent.react",
            )

            self.assertFalse(blocked["ok"])
            self.assertEqual("write_requires_execute_mode", blocked["error_code"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])

            allowed = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
                source="agent.react",
                execution_mode="execute",
                request_backup_path=str(create_yaml_backup(str(yaml_path))),
            )
            self.assertTrue(allowed["ok"])

    def test_tool_batch_takeout_updates_multiple_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_batch_takeout(
                yaml_path=str(yaml_path),
                entries=[
                    takeout_entry(1, 1, 1),
                    takeout_entry(2, 1, 2),
                ],
                date_str="2026-02-10",
                source="tests/test_tool_api.py",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["count"])

            current = load_yaml(str(yaml_path))
            self.assertIsNone(current["inventory"][0]["position"])
            self.assertIsNone(current["inventory"][1]["position"])

    def test_tool_batch_takeout_same_record_duplicate_entry_rejected(self):
        """Tube-level model: batching the same tube twice should be rejected."""
        with tempfile.TemporaryDirectory(prefix="ln2_tool_batch_same_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [make_record(1, box=5, position=33)]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_batch_takeout(
                yaml_path=str(yaml_path),
                entries=[
                    takeout_entry(1, 5, 33),
                    takeout_entry(1, 5, 33),
                ],
                date_str="2026-02-10",
                source="tests/test_tool_api.py",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result.get("error_code"))

    def test_legacy_actions_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_takeout_canon_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            with self.assertRaises(TypeError):
                tool_record_takeout(
                    yaml_path=str(yaml_path),
                    record_id=1,
                    from_slot=slot(1, 1),
                    date_str="2026-02-10",
                    action="Thaw",
                    source="tests/test_tool_api.py",
                )

            with self.assertRaises(TypeError):
                tool_batch_takeout(
                    yaml_path=str(yaml_path),
                    entries=[takeout_entry(2, 1, 2)],
                    date_str="2026-02-10",
                    action="Discard",
                    source="tests/test_tool_api.py",
                )

            data = load_yaml(str(yaml_path))
            self.assertEqual([], data["inventory"][0].get("thaw_events") or [])
            self.assertEqual([], data["inventory"][1].get("thaw_events") or [])

    def test_tool_record_takeout_move_updates_positions_and_appends_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 3),
                date_str="2026-02-10",
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual("3", result["preview"]["to_position"])
            self.assertEqual("1", result["preview"]["position_before"])
            self.assertEqual("3", result["preview"]["position_after"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(3, current["inventory"][0]["position"])
            events = current["inventory"][0].get("thaw_events") or []
            self.assertEqual(1, len(events))
            self.assertEqual("move", events[-1].get("action"))
            self.assertEqual([1], events[-1].get("positions"))
            self.assertEqual(1, events[-1].get("from_position"))
            self.assertEqual(3, events[-1].get("to_position"))
            self.assertNotIn("note", events[-1])

    def test_tool_record_takeout_move_rejects_occupied_same_box_target(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_occupied_single_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 2),
                date_str="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])
            self.assertTrue(any("is occupied by record #2" in err for err in result.get("errors", [])))

            current = load_yaml(str(yaml_path))
            self.assertEqual(1, current["inventory"][0]["position"])
            self.assertEqual(2, current["inventory"][1]["position"])
            self.assertEqual([], current["inventory"][0].get("thaw_events") or [])
            self.assertEqual([], current["inventory"][1].get("thaw_events") or [])

    def test_tool_record_takeout_move_requires_to_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_require_to_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            with self.assertRaises(TypeError):
                tool_record_move(
                    yaml_path=str(yaml_path),
                    record_id=1,
                    from_slot=slot(1, 1),
                    date_str="2026-02-10",
                )

    def test_tool_batch_takeout_move_updates_positions_to_empty_targets(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        make_record(3, box=1, position=3),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[
                    move_entry(1, 1, 1, 1, 4),
                    move_entry(3, 1, 3, 1, 5),
                ],
                date_str="2026-02-10",
            )

            self.assertTrue(result["ok"])
            self.assertEqual("move", result["preview"]["action_en"])
            self.assertEqual(2, result["result"]["count"])
            self.assertEqual([1, 3], result["result"]["affected_record_ids"])

            current = load_yaml(str(yaml_path))
            self.assertEqual(4, current["inventory"][0]["position"])
            self.assertEqual(2, current["inventory"][1]["position"])
            self.assertEqual(5, current["inventory"][2]["position"])

            self.assertEqual(1, len(current["inventory"][0].get("thaw_events") or []))
            self.assertEqual(0, len(current["inventory"][1].get("thaw_events") or []))
            self.assertEqual(1, len(current["inventory"][2].get("thaw_events") or []))

    def test_tool_batch_takeout_move_rejects_non_move_entry_shape(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_shape_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[{"record_id": 1, "from": slot(1, 1)}],
                date_str="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])

    def test_tool_batch_takeout_move_rejects_duplicate_targets_in_batch(self):
        """Regression: multiple moves to same target position should be rejected."""
        with tempfile.TemporaryDirectory(prefix="ln2_tool_move_batch_dup_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(8, box=3, position=3),
                        make_record(7, box=3, position=2),
                        make_record(6, box=3, position=1),
                    ]
                ),
                path=str(yaml_path),
            )

            result = tool_batch_move(
                yaml_path=str(yaml_path),
                entries=[
                    move_entry(8, 3, 3, 3, 4),
                    move_entry(7, 3, 2, 3, 3),
                    move_entry(6, 3, 1, 3, 3),
                ],
                date_str="2026-02-14",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("validation_failed", result["error_code"])
            self.assertTrue(
                any("already been moved in this request" in err for err in result.get("errors", []))
            )

    def test_tool_add_entry_rejects_duplicate_ids_in_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_dup_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(1, box=1, position=2),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[3],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("Duplicate ID" in err for err in result.get("errors", [])))

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 1)
            matched = [row for row in rows if row.get("action") == "add_entry" and row.get("status") == "failed"]
            self.assertTrue(matched)
            last = matched[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("integrity_validation_failed", (last.get("error") or {}).get("error_code"))

    def test_tool_add_entry_invalid_date_writes_failed_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_date_audit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("invalid_date", result["error_code"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("add_entry", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("invalid_date", (last.get("error") or {}).get("error_code"))

    def test_tool_record_takeout_rejects_malformed_thaw_events(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_bad_events_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            broken = make_record(1, box=1, position=1)
            broken["thaw_events"] = "broken"
            write_raw_yaml(yaml_path, make_data([broken]))

            result = tool_record_takeout(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                date_str="2026-02-10",
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("thaw_events" in err for err in result.get("errors", [])))

    def test_tool_add_entry_rejects_invalid_date_box_and_positions(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_invalid_args_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
            )

            bad_date = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[2],
                frozen_at="2026/02/10",
                fields={"cell_line": "K562"},
            )
            self.assertFalse(bad_date["ok"])
            self.assertEqual("invalid_date", bad_date["error_code"])

            bad_box = tool_add_entry(
                yaml_path=str(yaml_path),
                box=99,
                positions=[2],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )
            self.assertFalse(bad_box["ok"])
            self.assertEqual("invalid_box", bad_box["error_code"])

            bad_pos = tool_record_move(
                yaml_path=str(yaml_path),
                record_id=1,
                from_slot=slot(1, 1),
                to_slot=slot(1, 999),
                date_str="2026-02-10",
            )
            self.assertFalse(bad_pos["ok"])
            self.assertEqual("validation_failed", bad_pos["error_code"])

    def test_tool_add_entry_rejects_existing_position_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_conflict_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_raw_yaml(
                yaml_path,
                make_data(
                    [
                        make_record(1, box=1, position=10),
                        make_record(2, box=1, position=10),
                    ]
                ),
            )

            result = tool_add_entry(
                yaml_path=str(yaml_path),
                box=1,
                positions=[11],
                frozen_at="2026-02-10",
                fields={"cell_line": "K562"},
            )

            self.assertFalse(result["ok"])
            self.assertEqual("integrity_validation_failed", result["error_code"])
            self.assertTrue(any("Position conflict" in err for err in result.get("errors", [])))

    def test_tool_rollback_blocks_invalid_backup(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_rollback_guard_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            good = make_data([make_record(1, box=1, position=1)])
            write_yaml(good, path=str(yaml_path))

            bad_backup = Path(yaml_path).parent / "backups" / "manual_invalid_backup.yaml"
            bad_backup.parent.mkdir(parents=True, exist_ok=True)
            bad_payload = make_data([make_record(1, box=99, position=1)])
            write_raw_yaml(bad_backup, bad_payload)

            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(bad_backup),
            )

            self.assertFalse(result["ok"])
            self.assertEqual("rollback_backup_invalid", result["error_code"])
            self.assertEqual(str(bad_backup.resolve()), str(Path(result["backup_path"]).resolve()))

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 2)
            last = rows[-1]
            self.assertEqual("rollback", last["action"])
            self.assertEqual("failed", last.get("status"))
            self.assertEqual("rollback_backup_invalid", (last.get("error") or {}).get("error_code"))

    def test_tool_rollback_writes_requested_from_event(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_rollback_event_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=9)]),
                path=str(yaml_path),
                audit_meta={"action": "takeout", "source": "tests"},
            )

            source_event = {
                "timestamp": "2026-02-12T09:00:00",
                "action": "takeout",
                "trace_id": "trace-audit-1",
                "session_id": "session-audit-1",
            }
            backup_path = create_yaml_backup(str(yaml_path))
            self.assertIsNotNone(backup_path)
            result = tool_rollback(
                yaml_path=str(yaml_path),
                backup_path=str(backup_path),
                source_event=source_event,
            )

            self.assertTrue(result["ok"])

            rows = read_audit_rows(temp_dir)
            self.assertGreaterEqual(len(rows), 3)
            last = rows[-1]
            self.assertEqual("rollback", last["action"])
            self.assertEqual("success", last.get("status"))

            details = last.get("details") or {}
            requested_from_event = details.get("requested_from_event") or {}
            self.assertEqual("2026-02-12T09:00:00", requested_from_event.get("timestamp"))
            self.assertEqual("takeout", requested_from_event.get("action"))
            self.assertEqual("trace-audit-1", requested_from_event.get("trace_id"))
            self.assertEqual("session-audit-1", requested_from_event.get("session_id"))



class TestToolEditEntry(ManagedPathTestCase):
    def test_edit_entry_updates_allowed_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "2026-02-01"},
            )
            self.assertTrue(result["ok"])
            self.assertEqual("2025-01-01", result["result"]["before"]["frozen_at"])
            self.assertEqual("2026-02-01", result["result"]["after"]["frozen_at"])

            data = load_yaml(str(yaml_path))
            rec = data["inventory"][0]
            self.assertEqual("2026-02-01", rec["frozen_at"])

    def test_edit_entry_rejects_forbidden_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"box": 2, "short_name": "x"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("forbidden_fields", result["error_code"])

    def test_edit_entry_rejects_nonexistent_record(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=999,
                fields={"frozen_at": "2026-02-01"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("record_not_found", result["error_code"])

    def test_edit_entry_validates_date(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "not-a-date"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("invalid_date", result["error_code"])

    def test_edit_entry_writes_audit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={"frozen_at": "2026-02-01"},
                actor_context=build_actor_context(),
            )

            rows = read_audit_rows(temp_dir)
            edit_rows = [r for r in rows if r.get("action") == "edit_entry"]
            self.assertTrue(len(edit_rows) >= 1)
            self.assertEqual("success", edit_rows[-1].get("status"))

    def test_edit_entry_rejects_empty_fields(self):
        with tempfile.TemporaryDirectory(prefix="ln2_edit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_edit_entry(
                yaml_path=str(yaml_path),
                record_id=1,
                fields={},
            )
            self.assertFalse(result["ok"])
            self.assertEqual("no_fields", result["error_code"])


# ---------------------------------------------------------------------------
# Integration tests: non-default box layouts (10x10, 8x12, custom box_count)
# ---------------------------------------------------------------------------
