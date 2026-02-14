"""Tests for lib/position_fmt.py — position/box display conversion."""

import pytest
from lib.position_fmt import (
    pos_to_display,
    display_to_pos,
    box_to_display,
    display_to_box,
    get_box_count,
    get_box_numbers,
    get_total_slots,
    get_position_range,
)


class TestNumericMode:
    """Default numeric indexing (no layout or indexing=numeric)."""

    def test_pos_to_display_no_layout(self):
        assert pos_to_display(1) == "1"
        assert pos_to_display(81) == "81"

    def test_pos_to_display_explicit_numeric(self):
        layout = {"rows": 9, "cols": 9, "indexing": "numeric"}
        assert pos_to_display(1, layout) == "1"
        assert pos_to_display(42, layout) == "42"

    def test_display_to_pos_numeric(self):
        assert display_to_pos("1") == 1
        assert display_to_pos("81") == 81
        assert display_to_pos(" 42 ") == 42

    def test_roundtrip_numeric(self):
        layout = {"rows": 9, "cols": 9}
        for pos in range(1, 82):
            assert display_to_pos(pos_to_display(pos, layout), layout) == pos


class TestAlphanumericMode:
    """Alphanumeric indexing (A1, B2, etc.)."""

    LAYOUT_9x9 = {"rows": 9, "cols": 9, "indexing": "alphanumeric"}
    LAYOUT_8x12 = {"rows": 8, "cols": 12, "indexing": "alphanumeric"}

    def test_pos_1_is_A1(self):
        assert pos_to_display(1, self.LAYOUT_9x9) == "A1"

    def test_pos_9_is_A9(self):
        assert pos_to_display(9, self.LAYOUT_9x9) == "A9"

    def test_pos_10_is_B1(self):
        assert pos_to_display(10, self.LAYOUT_9x9) == "B1"

    def test_pos_81_is_I9(self):
        assert pos_to_display(81, self.LAYOUT_9x9) == "I9"

    def test_display_to_pos_A1(self):
        assert display_to_pos("A1", self.LAYOUT_9x9) == 1

    def test_display_to_pos_B1(self):
        assert display_to_pos("B1", self.LAYOUT_9x9) == 10

    def test_display_to_pos_I9(self):
        assert display_to_pos("I9", self.LAYOUT_9x9) == 81

    def test_display_to_pos_case_insensitive(self):
        assert display_to_pos("a1", self.LAYOUT_9x9) == 1
        assert display_to_pos("b3", self.LAYOUT_9x9) == 12

    def test_roundtrip_9x9(self):
        for pos in range(1, 82):
            display = pos_to_display(pos, self.LAYOUT_9x9)
            assert display_to_pos(display, self.LAYOUT_9x9) == pos

    def test_roundtrip_8x12(self):
        for pos in range(1, 97):
            display = pos_to_display(pos, self.LAYOUT_8x12)
            assert display_to_pos(display, self.LAYOUT_8x12) == pos

    def test_8x12_pos_12_is_A12(self):
        assert pos_to_display(12, self.LAYOUT_8x12) == "A12"

    def test_8x12_pos_13_is_B1(self):
        assert pos_to_display(13, self.LAYOUT_8x12) == "B1"

    def test_invalid_col_raises(self):
        with pytest.raises(ValueError):
            display_to_pos("A0", self.LAYOUT_9x9)

    def test_invalid_row_raises(self):
        with pytest.raises(ValueError):
            display_to_pos("Z1", self.LAYOUT_9x9)


class TestBoxDisplay:
    """Box label conversion."""

    def test_default_numeric(self):
        assert box_to_display(1) == "1"
        assert box_to_display(5) == "5"

    def test_custom_labels(self):
        layout = {"box_labels": ["A", "B", "C"]}
        assert box_to_display(1, layout) == "A"
        assert box_to_display(3, layout) == "C"

    def test_custom_labels_out_of_range(self):
        layout = {"box_labels": ["A", "B"]}
        assert box_to_display(5, layout) == "5"

    def test_display_to_box_numeric(self):
        assert display_to_box("3") == 3

    def test_display_to_box_label(self):
        layout = {"box_labels": ["A", "B", "C"]}
        assert display_to_box("B", layout) == 2

    def test_box_labels_with_explicit_box_numbers(self):
        layout = {
            "box_numbers": [1, 2, 4],
            "box_labels": ["A", "B", "D"],
        }
        assert box_to_display(4, layout) == "D"
        assert display_to_box("D", layout) == 4


class TestLayoutHelpers:
    """get_box_count, get_total_slots, get_position_range."""

    def test_defaults(self):
        assert get_total_slots() == 81
        assert get_position_range() == (1, 81)

    def test_custom_layout(self):
        layout = {"rows": 10, "cols": 10, "box_count": 8}
        assert get_total_slots(layout) == 100
        assert get_position_range(layout) == (1, 100)
        assert get_box_count(layout) == 8

    def test_box_count_fallback(self):
        # No box_count in layout → falls back to BOX_RANGE default (5)
        assert get_box_count({}) == 5

    def test_box_numbers_override_box_count(self):
        layout = {"box_count": 8, "box_numbers": [1, 2, 4, 5]}
        assert get_box_numbers(layout) == [1, 2, 4, 5]
        assert get_box_count(layout) == 4

    def test_8x12(self):
        layout = {"rows": 8, "cols": 12}
        assert get_total_slots(layout) == 96
        assert get_position_range(layout) == (1, 96)
