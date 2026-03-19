"""
Module: test_tool_status_formatter
Layer: unit
Covers: lib/tool_status_formatter.py

测试工具状态消息格式化。
"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.tool_status_formatter import MAX_STATUS_TEXT_LENGTH, format_tool_status


class ToolStatusFormatterTests(unittest.TestCase):
    def test_bash_prefers_description(self):
        status = format_tool_status(
            "bash",
            {"description": "Import xlsx into YAML", "command": "python migrate.py"},
        )
        self.assertEqual("Import xlsx into YAML", status)

    def test_bash_falls_back_when_description_missing(self):
        status = format_tool_status("bash", {"command": "echo test"})
        self.assertEqual("Running bash...", status)

    def test_powershell_prefers_description(self):
        status = format_tool_status(
            "powershell",
            {"description": "Run migration validation", "command": "Write-Output ok"},
        )
        self.assertEqual("Run migration validation", status)

    def test_search_records_uses_query(self):
        status = format_tool_status("search_records", {"query": "K562"})
        self.assertEqual("Search inventory: K562", status)

    def test_filter_records_uses_keyword(self):
        status = format_tool_status("filter_records", {"keyword": "genomic DNA"})
        self.assertEqual("Filter table: genomic DNA", status)

    def test_fs_edit_uses_file_path(self):
        status = format_tool_status("fs_edit", {"filePath": "/tmp/demo.txt"})
        self.assertEqual("Edit text in /tmp/demo.txt", status)

    def test_unknown_tool_uses_running_fallback(self):
        status = format_tool_status("made_up_tool", {"foo": "bar"})
        self.assertEqual("Running made_up_tool...", status)

    def test_status_text_is_truncated_to_limit(self):
        status = format_tool_status("bash", {"description": "x" * 200})
        self.assertLessEqual(len(status), MAX_STATUS_TEXT_LENGTH)
        self.assertTrue(status.endswith("..."))


if __name__ == "__main__":
    unittest.main()
