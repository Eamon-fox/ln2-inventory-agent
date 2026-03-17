"""
Module: test_context_consistency
Layer: unit
Covers: agent/react_agent.py  _trim_to_consistent_boundary / _normalize_history

Validates that conversation history is never left in a broken state after
truncation or interruption: orphan tool messages are stripped, and incomplete
tool-call groups at the tail are removed.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.react_agent import ReactAgent, _trim_to_consistent_boundary


class TestTrimToConsistentBoundary(unittest.TestCase):
    """Direct tests for _trim_to_consistent_boundary."""

    def test_empty_list_returns_empty(self):
        self.assertEqual([], _trim_to_consistent_boundary([]))

    def test_simple_user_assistant_unchanged(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(msgs, result)

    def test_complete_tool_group_preserved(self):
        msgs = [
            {"role": "user", "content": "find K562"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "found"},
            {"role": "assistant", "content": "done"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(msgs, result)

    def test_incomplete_tool_group_trimmed(self):
        """Assistant with 2 tool_calls but only 1 tool result => group removed."""
        msgs = [
            {"role": "user", "content": "do things"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            # c2 tool result is missing
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual([{"role": "user", "content": "do things"}], result)

    def test_assistant_tool_calls_with_no_results_trimmed(self):
        """Assistant with tool_calls but zero tool results => group removed."""
        msgs = [
            {"role": "user", "content": "query"},
            {
                "role": "assistant",
                "content": "let me check",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
            },
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual([{"role": "user", "content": "query"}], result)

    def test_orphan_tool_messages_at_head_stripped(self):
        """Tool messages at the start with no preceding assistant => stripped."""
        msgs = [
            {"role": "tool", "tool_call_id": "c1", "content": "orphan1"},
            {"role": "tool", "tool_call_id": "c2", "content": "orphan2"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            result,
        )

    def test_orphan_tool_messages_at_tail_stripped(self):
        """Trailing tool messages with no preceding assistant+tool_calls."""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "tool_call_id": "c1", "content": "stray"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            result,
        )

    def test_complete_group_followed_by_plain_assistant(self):
        """Complete tool group + plain assistant at end stays intact."""
        msgs = [
            {"role": "user", "content": "find"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "s", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "data"},
            {"role": "assistant", "content": "final answer"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(msgs, result)

    def test_tool_call_id_from_top_level(self):
        """Tool calls with id at top level (not nested in function)."""
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_1", "name": "search", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "tc_1", "content": "result"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(msgs, result)

    def test_multiple_complete_groups(self):
        """Two complete tool groups in sequence preserved."""
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
            {"role": "assistant", "content": "done"},
        ]
        result = _trim_to_consistent_boundary(list(msgs))
        self.assertEqual(msgs, result)


class TestNormalizeHistoryConsistency(unittest.TestCase):
    """Verify that _normalize_history produces consistent boundaries."""

    def test_truncation_does_not_split_tool_group(self):
        """When max_turns truncation cuts into a tool group, the group is removed."""
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first reply"},
            {"role": "user", "content": "find K562"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "found K562"},
            {"role": "assistant", "content": "Found K562"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "you are welcome"},
        ]
        # Truncate to 4 turns -- this would cut off the assistant+tool_calls
        # and leave orphan tool message at the head.
        result = ReactAgent._normalize_history(history, max_turns=4)
        roles = [m["role"] for m in result]
        # No tool messages should appear without preceding assistant+tool_calls
        if "tool" in roles:
            tool_idx = roles.index("tool")
            self.assertGreater(tool_idx, 0)
            preceding = result[tool_idx - 1]
            self.assertEqual("assistant", preceding["role"])
            self.assertTrue(
                isinstance(preceding.get("tool_calls"), list) and len(preceding["tool_calls"]) > 0,
                "tool message must follow an assistant with tool_calls",
            )

    def test_truncation_preserves_complete_group(self):
        """A complete tool group within the window is preserved."""
        history = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "s", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        result = ReactAgent._normalize_history(history, max_turns=10)
        self.assertEqual(4, len(result))

    def test_empty_history_returns_empty(self):
        self.assertEqual([], ReactAgent._normalize_history(None))
        self.assertEqual([], ReactAgent._normalize_history([]))


class TestEnsureToolResultsConsistent(unittest.TestCase):
    """Test ReactAgent._ensure_tool_results_consistent static method."""

    def test_delegates_to_trim(self):
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1"}],
            },
        ]
        result = ReactAgent._ensure_tool_results_consistent(list(msgs))
        self.assertEqual([{"role": "user", "content": "q"}], result)


if __name__ == "__main__":
    unittest.main()
