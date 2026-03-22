import unittest

from lib.box_layout_requests import (
    normalize_box_layout_indexing_request,
    normalize_box_layout_indexing_value,
    normalize_box_tag_request,
    normalize_box_tags,
    normalize_box_tag_value,
    normalize_manage_boxes_operation,
    normalize_manage_boxes_renumber_mode,
    normalize_manage_boxes_request,
)


class ManageBoxesNormalizationTests(unittest.TestCase):
    def test_normalize_manage_boxes_operation_accepts_aliases(self):
        self.assertEqual("add", normalize_manage_boxes_operation("increase"))
        self.assertEqual("remove", normalize_manage_boxes_operation("remove_box"))
        self.assertIsNone(normalize_manage_boxes_operation("set_tag"))

    def test_normalize_manage_boxes_renumber_mode_accepts_aliases(self):
        self.assertEqual("keep_gaps", normalize_manage_boxes_renumber_mode("keep"))
        self.assertEqual("renumber_contiguous", normalize_manage_boxes_renumber_mode("compact"))
        self.assertIsNone(normalize_manage_boxes_renumber_mode("middle_only"))

    def test_normalize_manage_boxes_request_normalizes_add_payload(self):
        issue, normalized = normalize_manage_boxes_request(
            {"action": "increase", "count": "2"}
        )
        self.assertIsNone(issue)
        self.assertEqual(
            {
                "op": "add",
                "operation": "add",
                "renumber_mode": None,
                "count": 2,
            },
            normalized,
        )

    def test_normalize_manage_boxes_request_normalizes_remove_payload(self):
        issue, normalized = normalize_manage_boxes_request(
            {"operation": "delete", "box": "3", "renumber_mode": "compact"}
        )
        self.assertIsNone(issue)
        self.assertEqual(
            {
                "op": "remove",
                "operation": "remove",
                "renumber_mode": "renumber_contiguous",
                "box": 3,
            },
            normalized,
        )

    def test_normalize_manage_boxes_request_rejects_invalid_count(self):
        issue, normalized = normalize_manage_boxes_request({"operation": "add", "count": 0})
        self.assertEqual({}, normalized)
        self.assertEqual("invalid_count", issue.get("error_code"))


class BoxTagNormalizationTests(unittest.TestCase):
    def test_normalize_box_tag_value_trims_and_allows_clear(self):
        value, error = normalize_box_tag_value(" shelf A ")
        self.assertEqual("shelf A", value)
        self.assertIsNone(error)

        cleared, clear_error = normalize_box_tag_value("   ")
        self.assertEqual("", cleared)
        self.assertIsNone(clear_error)

    def test_normalize_box_tag_value_rejects_multiline(self):
        value, error = normalize_box_tag_value("line1\nline2")
        self.assertIsNone(value)
        self.assertIn("single line", error)

    def test_normalize_box_tag_request_returns_normalized_box_and_tag(self):
        issue, normalized = normalize_box_tag_request({"box": "2", "tag": " frozen "})
        self.assertIsNone(issue)
        self.assertEqual({"box": 2, "tag": "frozen"}, normalized)

    def test_normalize_box_tags_filters_unknown_and_empty_values(self):
        normalized = normalize_box_tags(
            {"1": " A ", "2": "", "bad": "skip", "4": "later"},
            [1, 2, 3],
        )
        self.assertEqual({"1": "A"}, normalized)


class BoxLayoutIndexingNormalizationTests(unittest.TestCase):
    def test_normalize_box_layout_indexing_value_rejects_invalid_mode(self):
        value, error = normalize_box_layout_indexing_value("letters_first")
        self.assertIsNone(value)
        self.assertIn("numeric", error)

    def test_normalize_box_layout_indexing_request_normalizes_valid_mode(self):
        issue, normalized = normalize_box_layout_indexing_request({"indexing": " AlPhAnUmErIc "})
        self.assertIsNone(issue)
        self.assertEqual({"indexing": "alphanumeric"}, normalized)


if __name__ == "__main__":
    unittest.main()
