from app_gui.i18n import get_language, set_language
from app_gui.ui.plan_item_desc import build_localized_plan_item_desc


class _Panel:
    def __init__(self, layout=None):
        self._current_layout = layout or {}


def test_build_localized_plan_item_desc_uses_record_id_instead_of_question_mark():
    previous = get_language()
    try:
        set_language("en")
        panel = _Panel()

        text = build_localized_plan_item_desc(
            panel,
            {"action": "takeout", "record_id": 123, "box": 1, "position": 76},
        )

        assert text == "Takeout | ID 123 | Box 1:76"
    finally:
        set_language(previous)


def test_build_localized_plan_item_desc_uses_compact_chinese_move_format():
    previous = get_language()
    try:
        set_language("zh-CN")
        panel = _Panel({"indexing": "alphanumeric", "rows": 9, "cols": 9})

        text = build_localized_plan_item_desc(
            panel,
            {"action": "move", "record_id": 123, "box": 2, "position": 1, "to_box": 4, "to_position": 15},
        )

        assert text == "移动｜ID 123｜盒 2·A1 → 盒 4·B6"
    finally:
        set_language(previous)
