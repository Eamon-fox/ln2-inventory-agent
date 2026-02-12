"""Extended tests for lib/tool_api.py.

Tests for:
- tool_recent_frozen: days, count parameters
- tool_recommend_positions: box_preference, strategy
- tool_query_inventory: filter combinations, case sensitivity
- tool_query_thaw_events: date range queries
- tool_collect_timeline: all_history parameter
- tool_generate_stats: stats output structure
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.tool_api import (
    tool_collect_timeline,
    tool_generate_stats,
    tool_query_inventory,
    tool_query_thaw_events,
    tool_recent_frozen,
    tool_recommend_positions,
)
from lib.yaml_ops import load_yaml, write_yaml


def make_record(rec_id=1, box=1, positions=None, **kwargs):
    base = {
        "id": rec_id,
        "parent_cell_line": "NCCIT",
        "short_name": f"rec-{rec_id}",
        "box": box,
        "positions": positions if positions is not None else [1],
        "frozen_at": "2025-01-01",
    }
    base.update(kwargs)
    return base


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


# ── tool_recent_frozen Tests ─────────────────────────────────────


class RecentFrozenTests(unittest.TestCase):
    """Tests for tool_recent_frozen."""

    def test_recent_frozen_with_days_parameter(self):
        """Test recent_frozen with days parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, frozen_at="2026-01-01", positions=[1]),
                    make_record(2, frozen_at="2026-01-15", positions=[2]),
                    make_record(3, frozen_at="2026-01-30", positions=[3]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recent_frozen(str(yaml_path), days=60)
            self.assertTrue(result["ok"])
            self.assertGreater(result["result"]["count"], 0)

    def test_recent_frozen_with_count_parameter(self):
        """Test recent_frozen with count parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, positions=[1]),
                    make_record(2, positions=[2]),
                    make_record(3, positions=[3]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recent_frozen(str(yaml_path), count=2)
            self.assertTrue(result["ok"])
            self.assertEqual(2, result["result"]["count"])

    def test_recent_frozen_empty_inventory(self):
        """Test recent_frozen with empty inventory."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recent_frozen(str(yaml_path))
            self.assertTrue(result["ok"])
            self.assertEqual(0, result["result"]["count"])

    def test_recent_frozen_no_results_in_range(self):
        """Test recent_frozen when no records match date range."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, frozen_at="2024-01-01")]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            # Query for last 7 days, record is from Jan 2024
            result = tool_recent_frozen(str(yaml_path), days=7)
            self.assertTrue(result["ok"])
            self.assertEqual(0, result["result"]["count"])


# ── tool_recommend_positions Tests ──────────────────────────────


class RecommendPositionsTests(unittest.TestCase):
    """Tests for tool_recommend_positions."""

    def test_recommend_positions_with_box_preference(self):
        """Test box_preference parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[50]),
                    make_record(2, box=1, positions=[51]),
                    make_record(3, box=2, positions=[1]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recommend_positions(str(yaml_path), box_preference=2, count=1)
            self.assertTrue(result["ok"])
            # Should recommend position in box 2 (the preferred box)
            self.assertEqual(2, result["result"]["recommendations"][0]["box"])

    def test_recommend_positions_consecutive_strategy(self):
        """Test strategy=consecutive."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[3]),
                    make_record(3, box=1, positions=[5]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recommend_positions(str(yaml_path), strategy="consecutive", count=2)
            self.assertTrue(result["ok"])
            self.assertGreater(len(result["result"]["recommendations"]), 0)

    def test_recommend_positions_same_row_strategy(self):
        """Test strategy=same_row."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[9]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recommend_positions(str(yaml_path), strategy="same_row", count=1)
            self.assertTrue(result["ok"])

    def test_recommend_positions_any_strategy(self):
        """Test strategy=any."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recommend_positions(str(yaml_path), strategy="any", count=5)
            self.assertTrue(result["ok"])
            self.assertEqual(5, len(result["result"]["recommendations"]))

    def test_recommend_positions_full_box(self):
        """Test when preferred box is full."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            # Fill box 1
            write_yaml(
                make_data([make_record(i, box=1, positions=[i]) for i in range(1, 82)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_recommend_positions(str(yaml_path), box_preference=1, count=2)
            self.assertTrue(result["ok"])
            # Should still find positions in other boxes


# ── tool_query_inventory Tests ─────────────────────────────────


class QueryInventoryExtendedTests(unittest.TestCase):
    """Extended tests for tool_query_inventory."""

    def test_query_inventory_cell_and_box_combination(self):
        """Test filtering by both cell and box."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, parent_cell_line="K562"),
                    make_record(2, box=2, parent_cell_line="K562"),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(str(yaml_path), cell="K562", box=2)
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["result"]["count"])
            self.assertEqual(2, result["result"]["records"][0]["id"])

    def test_query_inventory_case_insensitive(self):
        """Test case-insensitive filtering."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, parent_cell_line="k562")]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(str(yaml_path), cell="k562")
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["result"]["count"])

            result_upper = tool_query_inventory(str(yaml_path), cell="K562")
            self.assertTrue(result_upper["ok"])
            self.assertEqual(1, result_upper["result"]["count"])

    def test_query_inventory_position_filter(self):
        """Test filtering by position."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[5]),
                    make_record(2, box=1, positions=[10]),
                    make_record(3, box=1, positions=[15]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(str(yaml_path), position=10)
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["result"]["count"])

    def test_query_inventory_plasmid_filter(self):
        """Test filtering by plasmid."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1], plasmid_name="pX"),
                    make_record(2, box=1, positions=[2], plasmid_name="pY"),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(str(yaml_path), plasmid="pX")
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["result"]["count"])

    def test_query_inventory_no_results(self):
        """Test query with no matching results."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, parent_cell_line="NCCIT")]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_inventory(str(yaml_path), cell="K562")
            self.assertTrue(result["ok"])
            self.assertEqual(0, result["result"]["count"])


# ── tool_query_thaw_events Tests ───────────────────────────────


class QueryThawEventsExtendedTests(unittest.TestCase):
    """Extended tests for tool_query_thaw_events."""

    def test_query_thaw_events_start_end_date(self):
        """Test date range query with start_date and end_date."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1)
            rec["thaw_events"] = [
                {"date": "2025-01-10", "action": "takeout", "positions": [1]},
                {"date": "2025-01-15", "action": "takeout", "positions": [2]},
                {"date": "2025-01-20", "action": "takeout", "positions": [3]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_thaw_events(
                str(yaml_path), start_date="2025-01-12", end_date="2025-01-18"
            )
            self.assertTrue(result["ok"])
            # Should only include event from Jan 15
            self.assertEqual(1, result["result"]["event_count"])

    def test_query_thaw_events_date_range_outside(self):
        """Test date range with no matching events."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1)
            rec["thaw_events"] = [
                {"date": "2025-01-10", "action": "takeout", "positions": [1]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_thaw_events(
                str(yaml_path), start_date="2025-02-01", end_date="2025-02-28"
            )
            self.assertTrue(result["ok"])
            self.assertEqual(0, result["result"]["event_count"])

    def test_query_thaw_events_with_max_records(self):
        """Test max_records parameter."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[1])
            rec["thaw_events"] = [
                {"date": f"2026-01-{i:02d}", "action": "takeout", "positions": [i]} for i in range(1, 11)
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_thaw_events(str(yaml_path), max_records=3)
            self.assertTrue(result["ok"])
            self.assertEqual(3, result["result"]["event_count"])

    def test_query_thaw_events_all_actions(self):
        """Test querying for all action types."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1, box=1, positions=[5])
            rec["thaw_events"] = [
                {"date": "2026-01-10", "action": "takeout", "positions": [1]},
                {"date": "2026-01-15", "action": "thaw", "positions": [2]},
                {"date": "2026-01-20", "action": "discard", "positions": [3]},
                {"date": "2026-01-25", "action": "move", "positions": [1], "from_position": 1, "to_position": 5},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_query_thaw_events(str(yaml_path))
            self.assertTrue(result["ok"])
            # All events should be returned
            self.assertEqual(4, result["result"]["event_count"])


# ── tool_collect_timeline Tests ─────────────────────────────────


class CollectTimelineExtendedTests(unittest.TestCase):
    """Extended tests for tool_collect_timeline."""

    def test_collect_timeline_all_history_true(self):
        """Test all_history=True returns all events."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1)
            rec["thaw_events"] = [
                {"date": "2024-01-01", "action": "takeout", "positions": [1]},
                {"date": "2025-01-01", "action": "takeout", "positions": [2]},
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_collect_timeline(str(yaml_path), all_history=True, days=30)
            self.assertTrue(result["ok"])
            # Should include events from 2024 (outside 30-day window)
            self.assertGreaterEqual(result["result"]["summary"]["takeout"], 1)

    def test_collect_timeline_days_limit(self):
        """Test days parameter limits timeline."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            rec = make_record(1)
            rec["thaw_events"] = [
                {"date": f"2025-01-{i:02d}", "action": "takeout", "positions": [1]} for i in range(1, 11)
            ]
            write_yaml(
                make_data([rec]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_collect_timeline(str(yaml_path), all_history=False, days=7)
            self.assertTrue(result["ok"])
            # Should limit to recent 7 days

    def test_collect_timeline_no_events(self):
        """Test timeline with no thaw events."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1)]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_collect_timeline(str(yaml_path))
            self.assertTrue(result["ok"])
            self.assertEqual(0, result["result"]["summary"]["takeout"])


# ── tool_generate_stats Tests ─────────────────────────────────────


class GenerateStatsTests(unittest.TestCase):
    """Tests for tool_generate_stats."""

    def test_generate_stats_structure(self):
        """Test stats output has expected structure."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[2]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_generate_stats(str(yaml_path))
            self.assertTrue(result["ok"])
            stats = result["result"]

            # Check expected keys
            self.assertIn("total_slots", stats)
            self.assertIn("total_occupied", stats)
            self.assertIn("total_empty", stats)
            self.assertIn("boxes", stats)

    def test_generate_stats_empty_inventory(self):
        """Test stats with empty inventory."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_generate_stats(str(yaml_path))
            self.assertTrue(result["ok"])
            stats = result["result"]
            self.assertEqual(0, stats["total_occupied"])
            self.assertEqual(0, stats["record_count"])

    def test_generate_stats_per_box(self):
        """Test per-box statistics."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([
                    make_record(1, box=1, positions=[1]),
                    make_record(2, box=1, positions=[2]),
                    make_record(3, box=2, positions=[3]),
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_generate_stats(str(yaml_path))
            self.assertTrue(result["ok"])
            stats = result["result"]

            self.assertIn("1", stats["boxes"])
            self.assertIn("2", stats["boxes"])
            self.assertEqual(2, stats["boxes"]["1"]["occupied"])

    def test_generate_stats_capacity_calculation(self):
        """Test capacity calculation."""
        with tempfile.TemporaryDirectory() as td:
            yaml_path = Path(td) / "inventory.yaml"
            write_yaml(
                make_data([make_record(1, box=1, positions=[1])]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            result = tool_generate_stats(str(yaml_path))
            self.assertTrue(result["ok"])
            stats = result["result"]

            # Default is 5 boxes x 81 positions = 405
            self.assertEqual(405, stats["total_slots"])


if __name__ == "__main__":
    unittest.main()
