"""
Module: test_context_compressor
Layer: unit
Covers: agent/context_compressor.py

Context compression: summarization of tool results, sliding window behavior.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.context_compressor import (
    _parse_tool_content,
    _summarize_tool_result,
    compress_history,
)


class TestParseToolContent(unittest.TestCase):
    """_parse_tool_content edge cases."""

    def test_valid_json_dict(self):
        self.assertEqual(_parse_tool_content('{"ok": true}'), {"ok": True})

    def test_non_dict_json(self):
        self.assertIsNone(_parse_tool_content('[1, 2]'))

    def test_invalid_json(self):
        self.assertIsNone(_parse_tool_content('not json'))

    def test_empty_string(self):
        self.assertIsNone(_parse_tool_content(''))

    def test_none(self):
        self.assertIsNone(_parse_tool_content(None))


class TestSummarizeToolResult(unittest.TestCase):
    """_summarize_tool_result for various result shapes."""

    def test_success_with_items(self):
        content = json.dumps({
            "ok": True,
            "result": {
                "items": [
                    {"id": 1, "box": 1, "position": 5, "cell_line": "HeLa", "extra_field": "ignored"},
                    {"id": 2, "box": 1, "position": 6, "cell_line": "293T", "extra_field": "ignored"},
                ]
            },
            "message": "staged 2 items",
        })
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["count"], 2)
        # Key fields preserved.
        self.assertEqual(parsed["items"][0]["id"], 1)
        self.assertEqual(parsed["items"][0]["cell_line"], "HeLa")
        # Extra fields stripped.
        self.assertNotIn("extra_field", parsed["items"][0])

    def test_error_result(self):
        content = json.dumps({
            "ok": False,
            "error_code": "position_conflict",
            "message": "Position 5 in box 1 is occupied.",
        })
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error_code"], "position_conflict")
        self.assertIn("occupied", parsed["message"])

    def test_query_with_records_truncated(self):
        records = [{"id": i, "cell_line": f"line_{i}"} for i in range(10)]
        content = json.dumps({
            "ok": True,
            "result": {"records": records},
        })
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["count"], 10)
        self.assertTrue(parsed["truncated"])
        self.assertEqual(len(parsed["records"]), 2)

    def test_query_with_few_records_kept(self):
        records = [{"id": 1}, {"id": 2}]
        content = json.dumps({
            "ok": True,
            "result": {"records": records},
        })
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertEqual(parsed["count"], 2)
        self.assertNotIn("truncated", parsed)

    def test_success_with_direct_fields(self):
        content = json.dumps({
            "ok": True,
            "result": {"id": 42, "box": 2, "position": 10},
        })
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["id"], 42)

    def test_success_with_message_only(self):
        content = json.dumps({"ok": True, "message": "done"})
        summary = _summarize_tool_result(content)
        parsed = json.loads(summary)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["message"], "done")

    def test_non_json_truncated(self):
        long_text = "x" * 500
        summary = _summarize_tool_result(long_text)
        self.assertTrue(summary.endswith("...(truncated)"))
        self.assertLess(len(summary), 250)

    def test_non_json_short_kept(self):
        short_text = "small output"
        self.assertEqual(_summarize_tool_result(short_text), short_text)

    def test_large_json_fallback_truncated(self):
        content = json.dumps({"ok": True, "data": "y" * 500})
        summary = _summarize_tool_result(content)
        self.assertTrue(summary.endswith("...(truncated)"))


class TestCompressHistory(unittest.TestCase):
    """compress_history sliding window + compression."""

    def test_short_history_unchanged(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = compress_history(msgs, recent_window=10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "hello")

    def test_empty_history(self):
        self.assertEqual(compress_history([], recent_window=5), [])

    def test_recent_window_kept_verbatim(self):
        """Messages within the recent window must not be modified."""
        tool_content = json.dumps({
            "ok": True,
            "result": {"items": [{"id": 1, "box": 1, "position": 1, "cell_line": "X"}]},
        })
        msgs = [
            {"role": "user", "content": "add entry"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "add_entry", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": tool_content},
            {"role": "assistant", "content": "done"},
        ]
        result = compress_history(msgs, recent_window=4)
        # All within window — kept verbatim.
        self.assertEqual(len(result), 4)
        self.assertEqual(result[2]["content"], tool_content)

    def test_older_tool_results_compressed(self):
        """Tool results outside the window should be summarized."""
        verbose_result = json.dumps({
            "ok": True,
            "result": {
                "items": [
                    {"id": 1, "box": 1, "position": 1, "cell_line": "HeLa", "frozen_at": "2024-01-01", "notes": "long note " * 50},
                ]
            },
            "message": "staged 1 item",
        })
        older_msgs = [
            {"role": "user", "content": "add HeLa"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "add_entry", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": verbose_result},
            {"role": "assistant", "content": "Added HeLa."},
        ]
        recent_msgs = [
            {"role": "user", "content": "what did I add?"},
            {"role": "assistant", "content": "You added HeLa."},
        ]
        msgs = older_msgs + recent_msgs
        result = compress_history(msgs, recent_window=2)

        # Recent 2 kept verbatim.
        self.assertEqual(result[-1]["content"], "You added HeLa.")
        self.assertEqual(result[-2]["content"], "what did I add?")

        # The old tool result should be compressed (shorter than original).
        old_tool_msg = result[2]
        self.assertEqual(old_tool_msg["role"], "tool")
        self.assertLess(len(old_tool_msg["content"]), len(verbose_result))

        # But key fields preserved.
        parsed = json.loads(old_tool_msg["content"])
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["items"][0]["id"], 1)
        self.assertEqual(parsed["items"][0]["cell_line"], "HeLa")

    def test_reasoning_stripped_from_old_assistant(self):
        """Old assistant messages with tool_calls should drop reasoning_content."""
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "add_entry", "arguments": "{}"}}
            ], "reasoning_content": "I should add this entry..."},
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true, "message": "done"}'},
            # Recent window:
            {"role": "user", "content": "ok"},
        ]
        result = compress_history(msgs, recent_window=1)
        old_assistant = result[0]
        self.assertNotIn("reasoning_content", old_assistant)

    def test_long_user_message_truncated(self):
        long_content = "x" * 1000
        msgs = [
            {"role": "user", "content": long_content},
            # Recent:
            {"role": "user", "content": "short"},
        ]
        result = compress_history(msgs, recent_window=1)
        self.assertLess(len(result[0]["content"]), len(long_content))
        self.assertTrue(result[0]["content"].endswith("...(truncated)"))


class TestBulkOperationScenario(unittest.TestCase):
    """Simulate bulk add operations to verify context retention."""

    def _make_add_cycle(self, idx: int) -> list[dict]:
        """Generate one add_entry tool call cycle (4 messages)."""
        call_id = f"call_{idx}"
        result = json.dumps({
            "ok": True,
            "result": {
                "items": [{
                    "id": idx,
                    "action": "add",
                    "box": (idx % 5) + 1,
                    "position": idx,
                    "cell_line": f"CellLine_{idx}",
                    "short_name": f"CL{idx}",
                }]
            },
            "message": f"staged item {idx}",
        })
        return [
            {"role": "user", "content": f"Add CellLine_{idx} to box {(idx % 5) + 1} position {idx}"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": call_id, "type": "function", "function": {
                    "name": "add_entry",
                    "arguments": json.dumps({"cell_line": f"CellLine_{idx}", "box": (idx % 5) + 1, "position": idx}),
                }}
            ], "reasoning_content": f"I need to add CellLine_{idx}..."},
            {"role": "tool", "tool_call_id": call_id, "content": result},
            {"role": "assistant", "content": f"Added CellLine_{idx}."},
        ]

    def test_100_adds_all_messages_retained(self):
        """With 100 add cycles (400 messages), all messages should be present after compression."""
        all_msgs = []
        for i in range(1, 101):
            all_msgs.extend(self._make_add_cycle(i))

        result = compress_history(all_msgs, recent_window=48)

        # All messages should still be present (compressed, not dropped).
        self.assertEqual(len(result), 400)

    def test_100_adds_key_fields_preserved(self):
        """Key fields from early operations must survive compression."""
        all_msgs = []
        for i in range(1, 101):
            all_msgs.extend(self._make_add_cycle(i))

        result = compress_history(all_msgs, recent_window=48)

        # Check the first tool result (oldest, definitely compressed).
        first_tool = result[2]
        self.assertEqual(first_tool["role"], "tool")
        parsed = json.loads(first_tool["content"])
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["items"][0]["id"], 1)
        self.assertEqual(parsed["items"][0]["cell_line"], "CellLine_1")

    def test_100_adds_recent_verbatim(self):
        """Recent messages (within window) must be unchanged."""
        all_msgs = []
        for i in range(1, 101):
            all_msgs.extend(self._make_add_cycle(i))

        result = compress_history(all_msgs, recent_window=48)

        # Last 48 messages should be identical to original.
        for j in range(48):
            original = all_msgs[-(48 - j)]
            compressed = result[-(48 - j)]
            self.assertEqual(original["role"], compressed["role"])
            if original["role"] == "tool":
                self.assertEqual(original["content"], compressed["content"])

    def test_100_adds_reasoning_stripped_from_old(self):
        """Old assistant messages should not have reasoning_content."""
        all_msgs = []
        for i in range(1, 101):
            all_msgs.extend(self._make_add_cycle(i))

        result = compress_history(all_msgs, recent_window=48)

        # Check an old assistant message (index 1 = first assistant tool-call msg).
        old_assistant = result[1]
        self.assertEqual(old_assistant["role"], "assistant")
        self.assertNotIn("reasoning_content", old_assistant)


class TestNormalizeHistoryIntegration(unittest.TestCase):
    """Verify ReactAgent._normalize_history uses compression."""

    def test_large_history_not_truncated(self):
        """History exceeding max_turns should be compressed, not dropped."""
        from agent.react_agent import ReactAgent

        # Build 60 messages (exceeds default 48).
        history = []
        for i in range(15):
            call_id = f"call_{i}"
            history.extend([
                {"role": "user", "content": f"do thing {i}"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": call_id, "type": "function", "function": {
                        "name": "add_entry", "arguments": "{}",
                    }}
                ]},
                {"role": "tool", "tool_call_id": call_id, "content": json.dumps({
                    "ok": True, "result": {"items": [{"id": i, "box": 1, "position": i}]},
                })},
                {"role": "assistant", "content": f"done {i}"},
            ])
        self.assertEqual(len(history), 60)

        result = ReactAgent._normalize_history(history, max_turns=48)

        # All 60 messages should be retained (compressed, not truncated to 48).
        self.assertEqual(len(result), 60)

        # First tool result should be compressed but present.
        first_tool = [m for m in result if m["role"] == "tool"][0]
        parsed = json.loads(first_tool["content"])
        self.assertTrue(parsed["ok"])


if __name__ == "__main__":
    unittest.main()
