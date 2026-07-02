"""Split from test_tool_api.py."""

from tests.integration.inventory._tool_api_shared import *  # noqa: F401,F403


class ToolApiSearchStatsTests(ManagedPathTestCase):
    def test_tool_search_records_keywords(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "dTAG clone",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(str(yaml_path), query="k562 clone", mode="keywords")
            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(2, response["result"]["records"][0]["id"])

    def test_tool_search_records_keywords_normalize_separator_variants(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_sep_keywords_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB-dTAG_clone3",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2025-01-01",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB control",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2025-01-01",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            spaced = tool_search_records(str(yaml_path), query="RTCB dTAG clone3", mode="keywords")
            underscored = tool_search_records(str(yaml_path), query="RTCB_dTAG_clone3", mode="keywords")

            self.assertTrue(spaced["ok"])
            self.assertEqual([1], [item["id"] for item in spaced["result"]["records"]])
            self.assertEqual(["rtcb", "dtag", "clone3"], spaced["result"]["keywords"])
            self.assertTrue(underscored["ok"])
            self.assertEqual([1], [item["id"] for item in underscored["result"]["records"]])

    def test_tool_search_records_keywords_matches_suffixed_token(self):
        # A short, hyphenated query (NT-sg -> [nt, sg]) should still match a
        # record whose field carries an extra suffix (NT-sg2 -> tokens nt/sg2),
        # matching what fuzzy already finds. Regression for keyword exact-token gap.
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_kw_suffix_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "NT-sg2",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2025-01-01",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "control",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2025-01-01",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            keywords = tool_search_records(str(yaml_path), query="NT-sg", mode="keywords")
            fuzzy = tool_search_records(str(yaml_path), query="NT-sg", mode="fuzzy")

            self.assertTrue(keywords["ok"])
            self.assertEqual([1], [item["id"] for item in keywords["result"]["records"]])
            self.assertEqual(
                [item["id"] for item in fuzzy["result"]["records"]],
                [item["id"] for item in keywords["result"]["records"]],
            )

    def test_tool_search_records_exact_matches_normalized_scalar_values_only(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_exact_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB-dTAG",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2025-01-01",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "RTCB-dTAG clone3",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2025-01-01",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            exact_response = tool_search_records(str(yaml_path), query="RTCB dTAG", mode="exact")
            fuzzy_response = tool_search_records(str(yaml_path), query="RTCB dTAG", mode="fuzzy")

            self.assertTrue(exact_response["ok"])
            self.assertEqual([1], [item["id"] for item in exact_response["result"]["records"]])
            self.assertEqual("rtcb dtag", exact_response["result"]["normalized_query"])
            self.assertTrue(fuzzy_response["ok"])
            self.assertEqual(2, fuzzy_response["result"]["total_count"])

    def test_tool_search_records_by_box_and_position(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_slot_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=2, position=15),
                        make_record(2, box=2, position=14),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="rec-1",
                box=2,
                position=15,
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["records"][0]["id"])
            self.assertEqual("occupied", response["result"]["slot_lookup"]["status"])
            self.assertEqual([1], response["result"]["slot_lookup"]["record_ids"])

    def test_tool_generate_stats_with_box_returns_active_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [2],
                                }
                            ],
                        },
                        make_record(4, box=2, position=1),
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=1,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(1, result.get("box"))
            self.assertEqual(81, result.get("box_total_slots"))
            self.assertEqual(2, result.get("box_occupied"))
            self.assertEqual(79, result.get("box_empty"))
            self.assertAlmostEqual(2 / 81 * 100, float(result.get("box_occupancy_rate") or 0.0), places=6)
            self.assertEqual(2, result.get("box_record_count"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2], ids)
            self.assertNotIn("occupancy_rate", result)
            self.assertNotIn("stats", result)
            self.assertNotIn("occupancy", result)

    def test_tool_generate_stats_include_inactive_returns_taken_out_records(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_inactive_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [
                                {
                                    "date": "2026-02-11",
                                    "action": "takeout",
                                    "positions": [2],
                                }
                            ],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=1,
                include_inactive=True,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(1, result.get("box"))
            self.assertEqual(2, result.get("box_occupied"))
            self.assertEqual(3, result.get("box_record_count"))
            self.assertTrue(result.get("include_inactive"))
            ids = [item.get("id") for item in result.get("box_records", [])]
            self.assertEqual([1, 2, 3], ids)
            self.assertNotIn("occupancy_rate", result)
            self.assertNotIn("stats", result)

    def test_tool_generate_stats_default_record_count_excludes_taken_out(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_record_count_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        make_record(1, box=1, position=1),
                        make_record(2, box=1, position=2),
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "taken-out",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-11", "action": "takeout", "positions": [2]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(2, result.get("record_count"))
            preview = result.get("inventory_preview", [])
            self.assertEqual([1, 2], [item.get("id") for item in preview])
            self.assertFalse(result.get("include_inactive"))

    def test_tool_generate_stats_rejects_invalid_box(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=99,
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_box", response["error_code"])

    def test_tool_generate_stats_includes_inventory_preview_when_within_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_preview_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = [make_record(i, box=1, position=i) for i in range(1, 6)]
            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(5, result.get("record_count"))
            self.assertFalse(result.get("inventory_omitted"))
            self.assertEqual(100, result.get("inventory_limit"))
            self.assertEqual(5, len(result.get("inventory_preview", [])))
            self.assertNotIn("inventory", (result.get("data") or {}))

    def test_tool_generate_stats_omits_inventory_preview_when_over_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_omit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = []
            for idx in range(1, 102):
                box = ((idx - 1) // 81) + 1
                position = ((idx - 1) % 81) + 1
                records.append(make_record(idx, box=box, position=position))

            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(101, result.get("record_count"))
            self.assertTrue(result.get("inventory_omitted"))
            self.assertEqual("record_count_exceeds_limit", result.get("inventory_omitted_reason"))
            self.assertEqual(100, result.get("inventory_limit"))
            self.assertNotIn("inventory_preview", result)
            self.assertNotIn("inventory", (result.get("data") or {}))
            self.assertGreaterEqual(len(result.get("next_actions", [])), 2)

    def test_tool_generate_stats_returns_full_preview_when_gui_flag_enabled(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_full_preview_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = []
            for idx in range(1, 202):
                box = ((idx - 1) // 81) + 1
                position = ((idx - 1) % 81) + 1
                records.append(make_record(idx, box=box, position=position))

            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                full_records_for_gui=True,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(201, result.get("record_count"))
            self.assertFalse(result.get("inventory_omitted"))
            self.assertEqual(100, result.get("inventory_limit"))
            self.assertEqual(201, len(result.get("inventory_preview", [])))
            self.assertTrue(result.get("full_records_for_gui"))

    def test_tool_generate_stats_rejects_invalid_gui_flag(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_invalid_gui_flag_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                full_records_for_gui="not-a-bool",
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response.get("error_code"))
            self.assertIn("full_records_for_gui", str(response.get("message") or ""))

    def test_tool_generate_stats_box_records_still_return_when_over_limit(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_stats_box_large_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            records = []
            for idx in range(1, 131):
                box = ((idx - 1) // 65) + 1
                position = ((idx - 1) % 65) + 1
                records.append(make_record(idx, box=box, position=position))

            write_yaml(
                make_data(records),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_generate_stats(
                yaml_path=str(yaml_path),
                box=2,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(2, result.get("box"))
            self.assertEqual(65, result.get("box_occupied"))
            self.assertEqual(65, result.get("box_record_count"))
            self.assertEqual(65, len(result.get("box_records", [])))
            self.assertFalse(result.get("inventory_omitted"))
            self.assertEqual(65, len(result.get("inventory_preview", [])))
            self.assertNotIn("stats", result)

    def test_tool_search_records_allows_empty_query_and_asterisk(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_query_optional_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            empty_response = tool_search_records(
                yaml_path=str(yaml_path),
                query="   ",
            )
            wildcard_response = tool_search_records(
                yaml_path=str(yaml_path),
                query="*",
            )

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

    def test_tool_search_records_supports_location_shortcut_query(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_shortcut_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=2, position=15)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="2:15",
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["records"][0]["id"])
            self.assertEqual("2:15", response["result"]["applied_filters"]["query_shortcut"])
            self.assertEqual(2, response["result"]["applied_filters"]["box"])
            self.assertEqual("15", response["result"]["applied_filters"]["position"])

    def test_tool_search_records_record_id_with_query_filter(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_rid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 7,
                            "parent_cell_line": "K562",
                            "short_name": "K562_main",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 8,
                            "parent_cell_line": "NCCIT",
                            "short_name": "NCCIT_main",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                record_id=7,
                query="K562",
                mode="keywords",
            )

            self.assertTrue(response["ok"])
            self.assertEqual(1, response["result"]["total_count"])
            self.assertEqual(7, response["result"]["records"][0]["id"])

    def test_tool_search_records_text_query_does_not_match_record_id(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_no_rid_text_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 907,
                            "parent_cell_line": "K562",
                            "short_name": "clone-main",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            for mode in ("fuzzy", "exact", "keywords"):
                response = tool_search_records(
                    yaml_path=str(yaml_path),
                    query="907",
                    mode=mode,
                )

                self.assertTrue(response["ok"])
                self.assertEqual(0, response["result"]["total_count"], mode)

            by_id = tool_search_records(yaml_path=str(yaml_path), record_id=907)
            self.assertTrue(by_id["ok"])
            self.assertEqual([907], [item["id"] for item in by_id["result"]["records"]])

    def test_tool_search_records_status_filters_active_and_inactive(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_active_default_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 7,
                            "parent_cell_line": "K562",
                            "short_name": "K562_active",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 8,
                            "parent_cell_line": "K562",
                            "short_name": "K562_taken",
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

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
            )
            self.assertTrue(response["ok"])
            self.assertEqual(2, response["result"]["total_count"])
            self.assertEqual([8, 7], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("all", response["result"]["applied_filters"]["status"])

            active_only = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                status="active",
            )
            self.assertTrue(active_only["ok"])
            self.assertEqual(1, active_only["result"]["total_count"])
            self.assertEqual([7], [item.get("id") for item in active_only["result"]["records"]])
            self.assertEqual("active", active_only["result"]["applied_filters"]["status"])

            inactive_only = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                status="inactive",
            )
            self.assertTrue(inactive_only["ok"])
            self.assertEqual(1, inactive_only["result"]["total_count"])
            self.assertEqual([8], [item.get("id") for item in inactive_only["result"]["records"]])
            self.assertEqual("inactive", inactive_only["result"]["applied_filters"]["status"])

    def test_tool_search_records_default_sort_is_recent_stored_desc(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_default_sort_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "older",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "newer",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-11",
                        },
                        {
                            "id": 3,
                            "parent_cell_line": "K562",
                            "short_name": "newer-high-id",
                            "box": 1,
                            "position": 3,
                            "frozen_at": "2026-02-11",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
            )

            self.assertTrue(response["ok"])
            self.assertEqual([3, 2, 1], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("stored_at", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("desc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("last", response["result"]["applied_filters"]["sort_nulls"])

    def test_tool_search_records_canonicalizes_legacy_sort_alias_in_response(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_legacy_sort_alias_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "older",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "newer",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-11",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                sort_by="frozen_at",
            )

            self.assertTrue(response["ok"])
            self.assertEqual([2, 1], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("stored_at", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("desc", response["result"]["applied_filters"]["sort_order"])

    def test_tool_search_records_supports_sort_by_position_with_nulls_last(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_sort_position_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 11,
                            "parent_cell_line": "K562",
                            "short_name": "p2",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 12,
                            "parent_cell_line": "K562",
                            "short_name": "p1",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-10",
                        },
                        {
                            "id": 13,
                            "parent_cell_line": "K562",
                            "short_name": "p-none",
                            "box": 1,
                            "position": None,
                            "frozen_at": "2026-02-10",
                            "thaw_events": [{"date": "2026-02-12", "action": "takeout", "positions": [3]}],
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                sort_by="position",
                sort_order="asc",
            )

            self.assertTrue(response["ok"])
            self.assertEqual([12, 11, 13], [item.get("id") for item in response["result"]["records"]])
            self.assertEqual("position", response["result"]["applied_filters"]["sort_by"])
            self.assertEqual("asc", response["result"]["applied_filters"]["sort_order"])
            self.assertEqual("last", response["result"]["applied_filters"]["sort_nulls"])

    def test_tool_search_records_applies_sort_before_max_results(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_sort_limit_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data(
                    [
                        {
                            "id": 1,
                            "parent_cell_line": "K562",
                            "short_name": "old",
                            "box": 1,
                            "position": 1,
                            "frozen_at": "2026-02-09",
                        },
                        {
                            "id": 2,
                            "parent_cell_line": "K562",
                            "short_name": "new",
                            "box": 1,
                            "position": 2,
                            "frozen_at": "2026-02-11",
                        },
                    ]
                ),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="K562",
                max_results=1,
            )

            self.assertTrue(response["ok"])
            self.assertEqual(2, response["result"]["total_count"])
            self.assertEqual(1, response["result"]["display_count"])
            self.assertEqual([2], [item.get("id") for item in response["result"]["records"]])

    def test_tool_search_records_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_status_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_search_records(
                yaml_path=str(yaml_path),
                query="rec-1",
                status="archived",
            )

            self.assertFalse(response["ok"])
            self.assertEqual("invalid_tool_input", response.get("error_code"))
            self.assertIn("status", str(response.get("message") or ""))

    def test_tool_search_records_rejects_invalid_sort_options(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_search_sort_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, position=1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bad_field = tool_search_records(
                yaml_path=str(yaml_path),
                query="rec-1",
                sort_by="created_at",
            )
            self.assertFalse(bad_field["ok"])
            self.assertEqual("invalid_tool_input", bad_field.get("error_code"))
            self.assertIn("sort_by", str(bad_field.get("message") or ""))

            bad_order = tool_search_records(
                yaml_path=str(yaml_path),
                query="rec-1",
                sort_order="newest",
            )
            self.assertFalse(bad_order["ok"])
            self.assertEqual("invalid_tool_input", bad_order.get("error_code"))
            self.assertIn("sort_order", str(bad_order.get("message") or ""))

    def test_tool_filter_records_applies_table_filters_sorting_and_pagination(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_filter_records_") as temp_dir:
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
                    {
                        "id": 4,
                        "sample_type": "genomic_dna",
                        "passage_number": 12,
                        "box": 1,
                        "position": None,
                        "frozen_at": "2026-02-09",
                        "thaw_events": [{"date": "2026-02-12", "action": "takeout", "positions": [3]}],
                    },
                ],
            }
            write_yaml(
                data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            response = tool_filter_records(
                yaml_path=str(yaml_path),
                keyword="dna",
                color_value="genomic_dna",
                column_filters={
                    "sample_type": {"type": "list", "values": ["genomic_dna"]},
                    "passage_number": {"type": "number", "min": 5, "max": 10},
                    "frozen_at": {"type": "date", "from": "2026-02-10", "to": "2026-02-11"},
                },
                sort_by="passage_number",
                sort_order="desc",
                limit=1,
                offset=1,
            )

            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(
                ["id", "location", "frozen_at", "note", "sample_type", "passage_number", "thaw_events"],
                result["columns"],
            )
            self.assertEqual("sample_type", result["color_key"])
            self.assertEqual(2, result["total_count"])
            self.assertEqual(1, result["display_count"])
            self.assertEqual([1], result["matched_boxes"])
            self.assertEqual("number", result["column_types"]["passage_number"])
            self.assertEqual("date", result["column_types"]["frozen_at"])
            self.assertEqual([2], [row.get("record_id") for row in result["rows"]])
            self.assertEqual("passage_number", result["applied_filters"]["sort_by"])
            self.assertEqual("desc", result["applied_filters"]["sort_order"])
            self.assertEqual("last", result["applied_filters"]["sort_nulls"])
            self.assertEqual(1, result["limit"])
            self.assertEqual(1, result["offset"])
            self.assertFalse(result["has_more"])

    def test_tool_filter_records_keyword_does_not_match_id_column(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_filter_no_id_keyword_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = {
                "meta": {"box_layout": {"rows": 9, "cols": 9}},
                "inventory": [
                    {
                        "id": 907,
                        "cell_line": "K562",
                        "short_name": "clone-main",
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

            keyword = tool_filter_records(yaml_path=str(yaml_path), keyword="907")
            self.assertTrue(keyword["ok"])
            self.assertEqual(0, keyword["result"]["total_count"])

            id_filter = tool_filter_records(
                yaml_path=str(yaml_path),
                column_filters={"id": {"type": "list", "values": ["907"]}},
            )
            self.assertTrue(id_filter["ok"])
            self.assertEqual([907], [row.get("record_id") for row in id_filter["result"]["rows"]])

    def test_tool_filter_records_rejects_invalid_sort_and_filter_columns(self):
        with tempfile.TemporaryDirectory(prefix="ln2_tool_filter_records_invalid_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            data = {
                "meta": {
                    "box_layout": {"rows": 9, "cols": 9},
                    "custom_fields": [{"key": "sample_type", "label": "Sample Type", "type": "str"}],
                },
                "inventory": [
                    {
                        "id": 1,
                        "sample_type": "genomic_dna",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-11",
                    }
                ],
            }
            write_yaml(
                data,
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            bad_sort = tool_filter_records(
                yaml_path=str(yaml_path),
                sort_by="created_at",
            )
            self.assertFalse(bad_sort["ok"])
            self.assertEqual("invalid_tool_input", bad_sort.get("error_code"))
            self.assertIn("sort_by", str(bad_sort.get("message") or ""))

            bad_filter = tool_filter_records(
                yaml_path=str(yaml_path),
                column_filters={"missing_column": {"type": "text", "text": "dna"}},
            )
            self.assertFalse(bad_filter["ok"])
            self.assertEqual("invalid_tool_input", bad_filter.get("error_code"))
            self.assertIn("missing_column", str(bad_filter.get("message") or ""))

