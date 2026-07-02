"""Split from test_tool_api.py."""

from tests.integration.inventory._tool_api_shared import *  # noqa: F401,F403


class ToolApiTimelineTests(ManagedPathTestCase):
    def test_tool_export_inventory_csv_writes_full_inventory(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_export_csv_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            output_path = Path(temp_dir) / "full_inventory.csv"
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [
                        {"key": "cell_line", "label": "Cell Line", "type": "str"},
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                },
                "inventory": [
                    {
                        "id": 2,
                        "cell_line": "HeLa",
                        "short_name": "hela-a",
                        "box": 2,
                        "position": 9,
                        "frozen_at": "2026-02-10",
                        "passage_number": 7,
                    },
                    {
                        "id": 1,
                        "short_name": "k562-a",
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-09",
                        "note": "中文备注",
                    },
                ],
            }
            write_yaml(data, path=str(yaml_path), audit_meta={"action": "seed", "source": "tests"})

            response = tool_export_inventory_csv(
                yaml_path=str(yaml_path),
                output_path=str(output_path),
            )

            self.assertTrue(response["ok"])
            self.assertTrue(output_path.exists())
            self.assertEqual(2, response["result"]["count"])
            self.assertIn("box", response["result"]["columns"])
            self.assertIn("position", response["result"]["columns"])
            self.assertNotIn("location", response["result"]["columns"])
            self.assertIn("cell_line", response["result"]["columns"])
            self.assertIn("passage_number", response["result"]["columns"])

            with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(2, len(rows))
            # Sorted by box/position/id, so id=1 comes first.
            self.assertEqual("1", rows[0]["id"])
            self.assertEqual("1", rows[0]["box"])
            self.assertEqual("2", rows[0]["position"])
            self.assertEqual("", rows[0]["cell_line"])
            self.assertEqual("2", rows[1]["id"])
            self.assertEqual("2", rows[1]["box"])
            self.assertEqual("9", rows[1]["position"])
            self.assertEqual("HeLa", rows[1]["cell_line"])
            self.assertEqual("7", rows[1]["passage_number"])
            self.assertEqual("中文备注", rows[0]["note"])

    def test_tool_export_inventory_csv_requires_output_path(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_export_csv_path_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_export_inventory_csv(
                yaml_path=str(yaml_path),
                output_path="",
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_output_path", response["error_code"])

    def test_tool_query_takeout_events_single_date_and_action(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_thaw_query_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, position=2)
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "takeout", "positions": [1]},
                {"date": "2026-02-11", "action": "takeout", "positions": [2]},
                {"date": "2026-02-12", "action": "move", "positions": [2]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_query_takeout_events(
                str(yaml_path),
                date="2026-02-10",
                action="鍙栧嚭",
            )
            self.assertTrue(response["ok"])
            payload = response["result"]
            self.assertEqual(1, payload["record_count"])
            self.assertEqual(1, payload["event_count"])
            self.assertEqual("takeout", payload["records"][0]["events"][0]["action"])

            move_response = tool_query_takeout_events(
                str(yaml_path),
                date="2026-02-12",
                action="绉诲姩",
            )
            self.assertTrue(move_response["ok"])
            move_payload = move_response["result"]
            self.assertEqual(1, move_payload["event_count"])
            self.assertEqual("move", move_payload["records"][0]["events"][0]["action"])

    def test_tool_collect_timeline_includes_move_counts(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_timeline_move_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            rec = make_record(1, box=1, position=2)
            rec["thaw_events"] = [
                {"date": "2026-02-10", "action": "move", "positions": [1]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
            )

            response = tool_collect_timeline(str(yaml_path), all_history=True)
            self.assertTrue(response["ok"])
            summary = response["result"]["summary"]
            self.assertEqual(1, summary["move"])
            self.assertGreaterEqual(summary["total_ops"], 1)

    def test_tool_list_audit_timeline_defaults_to_latest_50_rows(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_timeline_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            for idx in range(55):
                write_yaml(
                    make_data([make_record(1, box=1, position=1)]),
                    path=str(yaml_path),
                    audit_meta={"action": "touch", "source": "tests", "details": {"seq": idx}},
                )

            response = tool_list_audit_timeline(str(yaml_path))
            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(50, result["limit"])
            self.assertEqual(0, result["offset"])
            self.assertEqual(50, len(result["items"]))
            self.assertGreaterEqual(result["total"], 55)
            self.assertTrue(all(it.get("timestamp") for it in result["items"]))
            seqs = [int(it.get("audit_seq")) for it in result["items"]]
            self.assertEqual(seqs, sorted(seqs, reverse=True))

            all_rows_response = tool_list_audit_timeline(
                str(yaml_path),
                limit=None,
            )
            self.assertTrue(all_rows_response["ok"])
            all_result = all_rows_response["result"]
            self.assertIsNone(all_result["limit"])
            self.assertEqual(all_result["total"], len(all_result["items"]))
            self.assertGreaterEqual(len(all_result["items"]), 55)
            all_seqs = [int(it.get("audit_seq")) for it in all_result["items"]]
            self.assertEqual(all_seqs, sorted(all_seqs, reverse=True))

    def test_tool_list_audit_timeline_streams_page_without_inventory_load(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_timeline_stream_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
                auto_backup=False,
            )

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            rows = []
            for seq in range(1, 10001):
                rows.append(
                    {
                        "audit_seq": seq,
                        "action": "touch",
                        "source": "fixture",
                        "status": "success",
                        "timestamp": "2026-04-25T00:00:00",
                        "yaml_path": str(yaml_path),
                    }
                )
            audit_path.write_text(
                "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows),
                encoding="utf-8",
            )

            with patch(
                "lib.tool_api_impl.read_ops._load_supported_data",
                side_effect=AssertionError("audit timeline should not load inventory YAML"),
            ), patch(
                "lib.tool_api_support.load_yaml",
                side_effect=AssertionError("audit timeline wrapper should not load inventory YAML"),
            ):
                response = tool_list_audit_timeline(str(yaml_path), limit=5)

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(5, result["limit"])
            self.assertEqual(5, len(result["items"]))
            self.assertEqual(10000, result["total"])
            self.assertEqual(
                [10000, 9999, 9998, 9997, 9996],
                [int(row.get("audit_seq")) for row in result["items"]],
            )

    def test_tool_list_audit_timeline_supports_action_filter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_timeline_filter_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "backup", "source": "tests"},
            )

            response = tool_list_audit_timeline(
                str(yaml_path),
                limit=10,
                action_filter="backup",
            )
            self.assertTrue(response["ok"])
            items = response["result"]["items"]
            self.assertGreaterEqual(len(items), 1)
            self.assertTrue(all(str(item.get("action")) == "backup" for item in items))

    def test_tool_list_audit_timeline_sorts_by_audit_seq_not_timestamp(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_audit_seq_sort_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=2)]),
                path=str(yaml_path),
                audit_meta={"action": "touch_1", "source": "tests"},
            )
            write_yaml(
                make_data([make_record(1, box=1, position=3)]),
                path=str(yaml_path),
                audit_meta={"action": "touch_2", "source": "tests"},
            )

            audit_path = Path(get_audit_log_path(str(yaml_path)))
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(rows), 3)
            # Intentionally scramble timestamps to ensure ordering follows audit_seq only.
            rows[0]["timestamp"] = "2099-12-31T23:59:59"
            rows[-1]["timestamp"] = "2000-01-01T00:00:00"
            audit_path.write_text(
                "".join(f"{json.dumps(row, ensure_ascii=False, sort_keys=True)}\n" for row in rows),
                encoding="utf-8",
            )

            response = tool_list_audit_timeline(str(yaml_path), limit=None)
            self.assertTrue(response["ok"])
            items = response["result"]["items"]
            seqs = [int(item.get("audit_seq")) for item in items]
            self.assertEqual(seqs, sorted(seqs, reverse=True))
            self.assertEqual(max(seqs), int(items[0].get("audit_seq")))

    def test_tool_recommend_positions_and_raw_entries(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_misc_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, position=1),
                    make_record(2, box=1, position=2),
                    make_record(3, box=1, position=3),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            rec_response = tool_recommend_positions(str(yaml_path), count=2)
            self.assertTrue(rec_response["ok"])
            self.assertGreaterEqual(len(rec_response["result"]["recommendations"]), 1)

            raw_response = tool_get_raw_entries(str(yaml_path), [1, 99])
            self.assertTrue(raw_response["ok"])
            self.assertEqual([99], raw_response["result"]["missing_ids"])


