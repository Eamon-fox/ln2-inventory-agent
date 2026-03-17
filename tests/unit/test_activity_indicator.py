"""Unit tests for activity indicator logic (no Qt dependency for core helpers)."""

import unittest
import time

from app_gui.ui.activity_indicator import _format_elapsed


class TestFormatElapsed(unittest.TestCase):
    """Test the _format_elapsed helper used by the activity indicator."""

    def test_zero_seconds(self):
        self.assertEqual(_format_elapsed(0), "0s")

    def test_negative_clamps_to_zero(self):
        self.assertEqual(_format_elapsed(-5), "0s")

    def test_under_one_minute(self):
        self.assertEqual(_format_elapsed(45), "45s")

    def test_exactly_one_minute(self):
        self.assertEqual(_format_elapsed(60), "1m 00s")

    def test_over_one_minute(self):
        self.assertEqual(_format_elapsed(83), "1m 23s")

    def test_large_value(self):
        self.assertEqual(_format_elapsed(3661), "61m 01s")

    def test_fractional_seconds_truncated(self):
        self.assertEqual(_format_elapsed(5.9), "5s")

    def test_one_second(self):
        self.assertEqual(_format_elapsed(1), "1s")

    def test_fifty_nine_seconds(self):
        self.assertEqual(_format_elapsed(59), "59s")
