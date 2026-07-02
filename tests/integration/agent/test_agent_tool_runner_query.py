"""Split from test_agent_tool_runner.py."""

from tests.integration.agent._agent_tool_runner_shared import *  # noqa: F401,F403


class AgentToolRunnerQueryTests(AgentToolRunnerBaseCase):
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

    def test_search_records_keywords_normalize_separator_variants(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_sep_keywords_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB-dTAG_clone3",
                            "box": 2,
                            "position": 15,
                            "frozen_at": "2024-01-02",
                        },
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB control",
                            "box": 2,
                            "position": 16,
                            "frozen_at": "2024-01-01",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "search_records",
                {"query": "RTCB_dTAG_clone3", "mode": "keywords"},
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual([2], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual(["rtcb", "dtag", "clone3"], response["result"]["keywords"])

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

    def test_search_records_query_does_not_match_record_id_text(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_no_rid_text_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 907,
                        "parent_cell_line": "K562",
                        "short_name": "clone-main",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    },
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            by_query = runner.run("search_records", {"query": "907"})
            by_id = runner.run("search_records", {"record_id": 907})

            self.assertTrue(by_query["ok"])
            self.assertEqual(0, by_query["result"]["total_count"])
            self.assertTrue(by_id["ok"])
            self.assertEqual([907], [item.get("id") for item in by_id["result"]["records"]])

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

    def test_search_records_default_returns_active_records(self):
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
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual([1], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("active", response["result"]["applied_filters"]["status"])
            self.assertEqual("stored_at", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("desc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("last", response["result"]["applied_filters"]["sort_nulls"])

            all_records = runner.run("search_records", {"query": "K562", "status": "all"})
            self.assertTrue(all_records["ok"])
            self.assertEqual([2, 1], [item.get("id") for item in all_records["result"]["records"]])
            self.assertEqual("all", all_records["result"]["applied_filters"]["status"])

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

    def test_search_records_truncated_results_add_hint(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_search_truncated_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "newest",
                            "box": 1,
                            "position": 3,
                            "frozen_at": "2026-02-12",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "middle",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-11",
                        },
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "oldest",
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
                    "max_results": 1,
                },
            )

            self.assertTrue(response["ok"])
            self.assertEqual(3, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["display_count"])
            self.assertEqual([3], [item.get("id") for item in response["result"]["records"]])
            hint = str(response.get("_hint") or "")
            self.assertIn("showing 1 of 3 matches", hint)
            self.assertIn("max_results", hint)
            self.assertIn("Do not conclude", hint)

    def test_filter_records_supports_table_filters_and_sorting(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_filter_records_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "color_key": "sample_type",
                    "custom_fields": [
                        {"key": "sample_type", "label": "Sample Type", "type": "str"},
                        {"key": "passage_number", "label": "Passage #", "type": "int"},
                    ],
                },
                "inventory": [
                    {
                        "id": 1,
                        "sample_type": "genomic_dna",
                        "passage_number": 10,
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-11",
                    },
                    {
                        "id": 2,
                        "sample_type": "genomic_dna",
                        "passage_number": 6,
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-10",
                    },
                    {
                        "id": 3,
                        "sample_type": "gene_fragment",
                        "passage_number": 8,
                        "box": 2,
                        "position": 1,
                        "frozen_at": "2026-02-11",
                    },
                ],
            }
            write_yaml(
                data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "filter_records",
                {
                    "keyword": "dna",
                    "color_value": "genomic_dna",
                    "column_filters": {
                        "sample_type": {"type": "list", "values": ["genomic_dna"]},
                        "passage_number": {"type": "number", "min": 5, "max": 10},
                    },
                    "sort_by": "passage_number",
                    "sort_order": "desc",
                },
            )

            self.assertTrue(response["ok"])
            self.assertEqual([1, 2], [item.get("record_id") for item in response["result"]["rows"]])
            self.assertEqual(2, response["result"]["total_count"])
            self.assertEqual("passage_number", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("desc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("sample_type", response["result"]["color_key"])

    def test_filter_records_truncated_results_add_hint(self):
        with tempfile.TemporaryDirectory(prefix="ln2_agent_filter_truncated_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [{"key": "sample_type", "label": "Sample Type", "type": "str"}],
                },
                "inventory": [
                    {
                        "id": 3,
                        "sample_type": "genomic_dna",
                        "box": 1,
                        "position": 3,
                        "frozen_at": "2026-02-12",
                    },
                    {
                        "id": 2,
                        "sample_type": "genomic_dna",
                        "box": 1,
                        "position": 2,
                        "frozen_at": "2026-02-11",
                    },
                    {
                        "id": 1,
                        "sample_type": "genomic_dna",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    },
                ],
            }
            write_yaml(
                data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            response = runner.run(
                "filter_records",
                {
                    "keyword": "dna",
                    "limit": 1,
                },
            )

            self.assertTrue(response["ok"])
            self.assertEqual(3, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["display_count"])
            hint = str(response.get("_hint") or "")
            self.assertIn("showing 1 of 3 matches", hint)
            self.assertIn("filter_records", hint)
            self.assertIn("limit", hint)

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

