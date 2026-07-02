"""Split from test_tool_api.py."""

from tests.integration.inventory._tool_api_shared import *  # noqa: F401,F403


class TestCustomLayout10x10(ManagedPathTestCase):
    """Integration: 10x10 grid with 8 boxes."""

    def _seed(self, records, rows=10, cols=10, box_count=8):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inventory.yaml")
        write_raw_yaml(p, make_data_custom(records, rows, cols, box_count))
        return p, d

    def test_add_entry_position_100(self):
        """Position 100 should be valid in a 10x10 grid."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[100],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_position_101_rejected(self):
        """Position 101 should be rejected in a 10x10 grid."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[101],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertFalse(result["ok"])

    def test_add_entry_box_8_valid(self):
        """Box 8 should be valid with box_count=8."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=8, positions=[1],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_box_9_rejected(self):
        """Box 9 should be rejected with box_count=8."""
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=9, positions=[1],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "K562"},
        )
        self.assertFalse(result["ok"])

    def test_stats_reports_correct_capacity(self):
        """Stats should report 10x10x8 = 800 total capacity."""
        p, _ = self._seed([make_record(1, box=1, position=1)])
        result = tool_generate_stats(p)
        self.assertTrue(result["ok"])
        self.assertEqual(800, result["result"]["total_capacity"])

    def test_list_empty_box_8(self):
        """list_empty_positions should work for box 8."""
        p, _ = self._seed([])
        result = tool_list_empty_positions(p, box=8)
        self.assertTrue(result["ok"])
        self.assertEqual(100, result["result"]["boxes"][0]["empty_count"])

    def test_list_empty_box_9_rejected(self):
        """list_empty_positions should reject box 9."""
        p, _ = self._seed([])
        result = tool_list_empty_positions(p, box=9)
        self.assertFalse(result["ok"])

    def test_recommend_positions_10x10(self):
        """recommend_positions should work with 10x10 grid."""
        p, _ = self._seed([])
        result = tool_recommend_positions(p, count=3)
        self.assertTrue(result["ok"])
        for rec in result["result"]["recommendations"]:
            for pos in rec["positions"]:
                self.assertLessEqual(int(pos), 100)

    def test_thaw_then_move_high_position(self):
        """Record at position 95 can be moved to position 100."""
        rec = make_record(1, box=1, position=95)
        p, _ = self._seed([rec])
        result = tool_record_move(
            p,
            record_id=1,
            from_slot=slot(1, 95),
            to_slot=slot(1, 100),
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))
        data = load_yaml(p)
        self.assertEqual(100, data["inventory"][0]["position"])


class TestCustomLayout8x12(ManagedPathTestCase):
    """Integration: 8x12 grid (96 slots, like microplates)."""

    def _seed(self, records):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inventory.yaml")
        write_raw_yaml(p, make_data_custom(records, rows=8, cols=12, box_count=3))
        return p, d

    def test_add_entry_position_96(self):
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[96],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "HeLa"},
        )
        self.assertTrue(result["ok"], result.get("message"))

    def test_add_entry_position_97_rejected(self):
        p, _ = self._seed([])
        result = tool_add_entry(
            p, box=1, positions=[97],
            frozen_at="2025-06-01", auto_backup=False,
            fields={"cell_line": "HeLa"},
        )
        self.assertFalse(result["ok"])

    def test_stats_capacity_288(self):
        """8x12x3 = 288 total capacity."""
        p, _ = self._seed([])
        result = tool_generate_stats(p)
        self.assertTrue(result["ok"])
        self.assertEqual(288, result["result"]["total_capacity"])

    def test_batch_takeout_high_positions(self):
        """Batch thaw records at positions > 81 (old default limit)."""
        recs = [
            make_record(1, box=1, position=85),
            make_record(2, box=1, position=90),
        ]
        p, _ = self._seed(recs)
        result = tool_batch_takeout(
            p,
            entries=[takeout_entry(1, 1, 85), takeout_entry(2, 1, 90)],
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual(2, result["result"]["count"])


class TestValidatorsWithLayout(ManagedPathTestCase):
    """Integration: validators respect per-dataset layout."""

    def test_validate_inventory_10x10(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=1, position=100)
        data = make_data_custom([rec], rows=10, cols=10, box_count=5)
        errors, warnings = validate_inventory(data)
        self.assertEqual([], errors)

    def test_validate_inventory_rejects_101_in_10x10(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=1, position=101)
        data = make_data_custom([rec], rows=10, cols=10, box_count=5)
        errors, _ = validate_inventory(data)
        self.assertTrue(any("101" in e for e in errors))

    def test_validate_inventory_rejects_box_6_with_box_count_5(self):
        from lib.validators import validate_inventory
        rec = make_record(1, box=6, position=1)
        data = make_data_custom([rec], rows=9, cols=9, box_count=5)
        errors, _ = validate_inventory(data)
        self.assertTrue(any("box" in e.lower() for e in errors))

    def test_parse_positions_alphanumeric(self):
        from lib.validators import parse_positions
        layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        result = parse_positions("A1,B3", layout)
        self.assertEqual([1, 12], result)

    def test_parse_positions_alphanumeric_rejects_numeric_input(self):
        from lib.validators import parse_positions
        layout = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
        with self.assertRaises(ValueError):
            parse_positions("1,2", layout)


class TestAdjustBoxCount(ManagedPathTestCase):
    def _seed(self, records, layout):
        d = tempfile.mkdtemp()
        p = str(Path(d) / "inventory.yaml")
        write_raw_yaml(p, {"meta": {"box_layout": dict(layout)}, "inventory": list(records)})
        return p, d

    def test_add_boxes_updates_box_numbers_and_count(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="add",
            count=2,
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 3, 4, 5, 6, 7], layout.get("box_numbers"))
        self.assertEqual(7, layout.get("box_count"))
        self.assertEqual(9, layout.get("rows"))
        self.assertEqual(9, layout.get("cols"))

    def test_remove_middle_box_requires_mode(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=3,
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("renumber_mode_required", result.get("error_code"))

    def test_remove_middle_box_keep_gaps(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=3,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 4, 5], layout.get("box_numbers"))
        self.assertEqual(4, layout.get("box_count"))

        empty = tool_list_empty_positions(p)
        self.assertTrue(empty["ok"])
        self.assertEqual(["1", "2", "4", "5"], [b["box"] for b in empty["result"]["boxes"]])

    def test_add_boxes_preserves_existing_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 3,
                "box_tags": {"1": "LN2-A", "2": "Virus"},
            },
        )
        result = tool_manage_boxes(
            p,
            operation="add",
            count=2,
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"1": "LN2-A", "2": "Virus"}, layout.get("box_tags"))

    def test_remove_middle_box_keep_gaps_updates_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_tags": {"2": "A", "3": "B", "4": "C"},
            },
        )
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=3,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"2": "A", "4": "C"}, layout.get("box_tags"))

    def test_remove_middle_box_renumber_remaps_box_tags(self):
        p, _ = self._seed(
            [],
            {
                "rows": 9,
                "cols": 9,
                "box_count": 5,
                "box_tags": {"2": "A", "4": "C", "5": "D"},
            },
        )
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=3,
            renumber_mode="renumber_contiguous",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 3, 4], layout.get("box_numbers"))
        self.assertEqual({"2": "A", "3": "C", "4": "D"}, layout.get("box_tags"))

    def test_remove_middle_box_accepts_delete_and_compact_aliases(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="delete",
            box=3,
            renumber_mode="compact",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual("remove", result["preview"]["operation"])
        self.assertEqual("renumber_contiguous", result["preview"]["renumber_mode"])

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual([1, 2, 3, 4], layout.get("box_numbers"))
        self.assertEqual(4, layout.get("box_count"))

    def test_set_box_tag_updates_and_clears(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 3})
        result = tool_set_box_tag(
            p,
            box=2,
            tag=" -80 second shelf ",
            auto_backup=False,
        )
        self.assertTrue(result["ok"], result.get("message"))

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual({"2": "-80 second shelf"}, layout.get("box_tags"))

        clear_result = tool_set_box_tag(
            p,
            box=2,
            tag="",
            auto_backup=False,
        )
        self.assertTrue(clear_result["ok"], clear_result.get("message"))
        data_after = load_yaml(p)
        self.assertNotIn("box_tags", data_after["meta"]["box_layout"])

    def test_set_box_tag_rejects_multiline(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 2})
        result = tool_set_box_tag(
            p,
            box=1,
            tag="line1\nline2",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tag", result.get("error_code"))

    def test_set_box_tag_rejects_too_long(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 2})
        result = tool_set_box_tag(
            p,
            box=1,
            tag="x" * 81,
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_tag", result.get("error_code"))

    def test_set_box_layout_indexing_updates_meta_only(self):
        p, _ = self._seed(
            [make_record(1, box=1, position=10)],
            {"rows": 9, "cols": 9, "box_count": 3},
        )

        result = tool_set_box_layout_indexing(
            p,
            indexing="alphanumeric",
            auto_backup=False,
        )

        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual("numeric", result["result"]["indexing_before"])
        self.assertEqual("alphanumeric", result["result"]["indexing_after"])

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertEqual("alphanumeric", layout.get("indexing"))
        self.assertEqual(10, data["inventory"][0]["position"])

    def test_set_box_layout_indexing_numeric_removes_default_field(self):
        p, _ = self._seed(
            [make_record(1, box=1, position=10)],
            {"rows": 9, "cols": 9, "box_count": 3, "indexing": "alphanumeric"},
        )

        result = tool_set_box_layout_indexing(
            p,
            indexing="numeric",
            auto_backup=False,
        )

        self.assertTrue(result["ok"], result.get("message"))
        self.assertEqual("alphanumeric", result["result"]["indexing_before"])
        self.assertEqual("numeric", result["result"]["indexing_after"])

        data = load_yaml(p)
        layout = data["meta"]["box_layout"]
        self.assertNotIn("indexing", layout)
        self.assertEqual(10, data["inventory"][0]["position"])

    def test_set_box_layout_indexing_rejects_invalid_value(self):
        p, _ = self._seed([], {"rows": 9, "cols": 9, "box_count": 3})

        result = tool_set_box_layout_indexing(
            p,
            indexing="letters_first",
            auto_backup=False,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("invalid_indexing", result.get("error_code"))

    def test_remove_non_empty_box_blocked(self):
        records = [make_record(1, box=2, position=1)]
        p, _ = self._seed(records, {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=2,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("box_not_empty", result.get("error_code"))

    def test_remove_box_with_only_historical_records_reports_reason(self):
        records = [
            {
                "id": 1,
                "parent_cell_line": "NCCIT",
                "short_name": "hist-only",
                "box": 2,
                "position": None,
                "frozen_at": "2025-01-01",
                "thaw_events": [
                    {"date": "2025-01-10", "action": "takeout", "positions": [1]},
                ],
            }
        ]
        p, _ = self._seed(records, {"rows": 9, "cols": 9, "box_count": 5})
        result = tool_manage_boxes(
            p,
            operation="remove",
            box=2,
            renumber_mode="keep_gaps",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("box_not_empty", result.get("error_code"))
        self.assertIn("historical", str(result.get("message", "")).lower())
        self.assertEqual([], result.get("active_blocking_record_ids"))
        self.assertEqual([1], result.get("historical_blocking_record_ids"))

    def test_record_takeout_cross_box_respects_box_numbers(self):
        records = [make_record(1, box=1, position=1)]
        p, _ = self._seed(
            records,
            {"rows": 9, "cols": 9, "box_count": 4, "box_numbers": [1, 2, 4, 5]},
        )
        result = tool_record_move(
            p,
            record_id=1,
            from_slot=slot(1, 1),
            to_slot=slot(3, 2),
            date_str="2025-06-01",
            auto_backup=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual("invalid_box", result.get("error_code"))


if __name__ == "__main__":
    unittest.main()
