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

from agent.tool_runner import AgentToolRunner
from agent.tool_status_formatter import MAX_STATUS_TEXT_LENGTH
from tests.managed_paths import ManagedPathTestCase


class ToolStatusFormatterTests(ManagedPathTestCase):
    def setUp(self):
        super().setUp()
        self.runner = AgentToolRunner(yaml_path=self.fake_yaml_path)

    def test_shell_prefers_description(self):
        status = self.runner.format_tool_status(
            "shell",
            {"description": "Import xlsx into YAML", "command": "python migrate.py"},
        )
        self.assertEqual("Import xlsx into YAML", status)

    def test_shell_falls_back_when_description_missing(self):
        status = self.runner.format_tool_status("shell", {"command": "echo test"})
        self.assertEqual("Running shell...", status)

    def test_shell_accepts_engine_description(self):
        status = self.runner.format_tool_status(
            "shell",
            {"description": "Run migration validation", "command": "Write-Output ok"},
        )
        self.assertEqual("Run migration validation", status)

    def test_search_records_uses_query(self):
        status = self.runner.format_tool_status("search_records", {"query": "K562"})
        self.assertEqual("Search inventory: K562", status)

    def test_filter_records_uses_keyword(self):
        status = self.runner.format_tool_status("filter_records", {"keyword": "genomic DNA"})
        self.assertEqual("Filter table: genomic DNA", status)

    def test_fs_edit_uses_file_path(self):
        status = self.runner.format_tool_status("fs_edit", {"filePath": "/tmp/demo.txt"})
        self.assertEqual("Edit text in /tmp/demo.txt", status)

    def test_unknown_tool_uses_running_fallback(self):
        status = self.runner.format_tool_status("made_up_tool", {"foo": "bar"})
        self.assertEqual("Running made_up_tool...", status)

    def test_status_text_is_truncated_to_limit(self):
        status = self.runner.format_tool_status("shell", {"description": "x" * 200})
        self.assertLessEqual(len(status), MAX_STATUS_TEXT_LENGTH)
        self.assertTrue(status.endswith("..."))


if __name__ == "__main__":
    unittest.main()
