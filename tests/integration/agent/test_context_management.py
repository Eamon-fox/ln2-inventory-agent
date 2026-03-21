"""
Module: test_context_management
Layer: integration/agent
Covers: agent/react_agent.py context management during bulk operations

Verifies that the ReAct agent retains key information from earlier tool
calls when processing large batch operations (100+ entries).
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.react_agent import ReactAgent
from tests.managed_paths import ManagedPathTestCase
from agent.tool_runner import AgentToolRunner


class _BulkAddLLM:
    """Fake LLM that simulates reading bulk add_entry results from history.

    On each call, it inspects the messages to verify that earlier tool results
    are still accessible (not dropped), then returns a direct answer.
    """

    def __init__(self, expected_count: int):
        self.expected_count = expected_count
        self.call_count = 0
        self.messages_received: list = []
        self.tool_results_visible: list[int] = []

    def chat(self, messages, tools=None, temperature=0.0, **kwargs):
        self.call_count += 1
        self.messages_received = list(messages)

        # Count how many tool results with "ok": true are visible.
        visible_ids = set()
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(parsed, dict) or not parsed.get("ok"):
                continue
            # Check both original format (result.items) and compressed format (items).
            items = (parsed.get("result") or {}).get("items") or parsed.get("items") or []
            for item in items:
                if isinstance(item, dict) and "id" in item:
                    visible_ids.add(item["id"])
            # Also check direct id field.
            if "id" in parsed:
                visible_ids.add(parsed["id"])

        self.tool_results_visible = sorted(visible_ids)
        return {
            "role": "assistant",
            "content": f"Found {len(visible_ids)} tool results in context.",
            "tool_calls": [],
        }


class TestBulkOperationContextRetention(ManagedPathTestCase):
    """Verify context is retained during bulk operations."""

    def _build_bulk_history(self, count: int) -> list[dict]:
        """Build a conversation history simulating `count` add_entry calls."""
        history = []
        for i in range(1, count + 1):
            call_id = f"call_{i}"
            tool_result = json.dumps({
                "ok": True,
                "result": {
                    "items": [{
                        "id": i,
                        "action": "add",
                        "box": (i % 5) + 1,
                        "position": i,
                        "cell_line": f"CellLine_{i}",
                        "short_name": f"CL{i}",
                    }]
                },
                "message": f"staged item {i}",
            })
            history.extend([
                {"role": "user", "content": f"Add CellLine_{i}"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "add_entry",
                            "arguments": json.dumps({
                                "cell_line": f"CellLine_{i}",
                                "box": (i % 5) + 1,
                                "position": i,
                            }),
                        },
                    }],
                    "reasoning_content": f"Adding cell line {i}...",
                },
                {"role": "tool", "tool_call_id": call_id, "content": tool_result},
                {"role": "assistant", "content": f"Added CellLine_{i} successfully."},
            ])
        return history

    def test_50_adds_all_results_visible(self):
        """With 50 add cycles (200 messages), all tool results must be visible to LLM."""
        llm = _BulkAddLLM(expected_count=50)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)

        history = self._build_bulk_history(50)
        agent.run("what have I added?", conversation_history=history)

        # All 50 tool result IDs should be visible in messages.
        self.assertEqual(len(llm.tool_results_visible), 50)
        self.assertIn(1, llm.tool_results_visible)
        self.assertIn(50, llm.tool_results_visible)

    def test_100_adds_all_results_visible(self):
        """With 100 add cycles (400 messages), all tool results must be visible."""
        llm = _BulkAddLLM(expected_count=100)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)

        history = self._build_bulk_history(100)
        agent.run("summarize all additions", conversation_history=history)

        self.assertEqual(len(llm.tool_results_visible), 100)
        self.assertIn(1, llm.tool_results_visible)
        self.assertIn(100, llm.tool_results_visible)

    def test_100_adds_early_results_still_retain_key_fields(self):
        """Before checkpointing triggers, early tool results should remain visible with key fields."""
        llm = _BulkAddLLM(expected_count=100)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)

        history = self._build_bulk_history(100)
        agent.run("check", conversation_history=history)

        # Find the first tool message in messages sent to LLM.
        tool_msgs = [m for m in llm.messages_received if m.get("role") == "tool"]
        self.assertGreater(len(tool_msgs), 0)

        # First tool result (oldest) should still have key fields.
        first_tool = tool_msgs[0]
        parsed = json.loads(first_tool["content"])
        self.assertTrue(parsed["ok"])
        items = parsed.get("items", [])
        if not items:
            items = (parsed.get("result") or {}).get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[0]["cell_line"], "CellLine_1")

    def test_reasoning_content_retained_before_checkpoint(self):
        """Without checkpointing, raw history should still carry reasoning content."""
        llm = _BulkAddLLM(expected_count=50)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)

        history = self._build_bulk_history(50)
        agent.run("check", conversation_history=history)

        # Check that old assistant messages (outside recent window) lost reasoning.
        assistant_with_tools = [
            m for m in llm.messages_received
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        # At least some should exist.
        self.assertGreater(len(assistant_with_tools), 0)

        first_assistant = assistant_with_tools[0]
        self.assertIn("reasoning_content", first_assistant)

    def test_recent_messages_verbatim(self):
        """Messages within the recent window must not be altered."""
        llm = _BulkAddLLM(expected_count=50)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)

        history = self._build_bulk_history(50)
        original_last = history[-1].copy()
        agent.run("check", conversation_history=history)

        # The last assistant message before user query should be verbatim.
        # Find it in messages (excluding system and the new user query).
        non_system = [m for m in llm.messages_received if m.get("role") != "system"]
        # Last message is the new user query; second-to-last is from history.
        second_to_last = non_system[-2]
        self.assertEqual(second_to_last["content"], original_last["content"])


if __name__ == "__main__":
    unittest.main()
