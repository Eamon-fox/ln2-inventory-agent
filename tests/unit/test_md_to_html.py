"""
Module: test_md_to_html
Layer: unit
Covers: app_gui/ui/utils.md_to_html

Markdown-to-HTML conversion utility used by chat and question dialogs.
"""

from app_gui.ui.utils import md_to_html


class TestMdToHtml:
    def test_empty_string(self):
        assert md_to_html("") == ""

    def test_none_input(self):
        assert md_to_html(None) == ""

    def test_plain_text(self):
        result = md_to_html("hello world")
        assert "hello world" in result

    def test_bold(self):
        result = md_to_html("**bold text**")
        assert "<strong>bold text</strong>" in result

    def test_italic(self):
        result = md_to_html("*italic text*")
        assert "<em>italic text</em>" in result

    def test_heading(self):
        result = md_to_html("# Heading 1")
        assert "<h1>" in result
        assert "Heading 1" in result

    def test_unordered_list(self):
        result = md_to_html("- item A\n- item B")
        assert "<li>" in result
        assert "item A" in result
        assert "item B" in result

    def test_ordered_list(self):
        result = md_to_html("1. first\n2. second")
        assert "<li>" in result
        assert "first" in result
        assert "second" in result

    def test_inline_code(self):
        result = md_to_html("use `print()` here")
        assert "<code>" in result
        assert "print()" in result

    def test_code_block(self):
        result = md_to_html("```\ncode line\n```")
        assert "<code>" in result
        assert "code line" in result

    def test_mixed_content(self):
        text = "## Summary\n\n- **bold** item\n- *italic* item\n\nDone."
        result = md_to_html(text)
        assert "<h2>" in result
        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result
        assert "<li>" in result
