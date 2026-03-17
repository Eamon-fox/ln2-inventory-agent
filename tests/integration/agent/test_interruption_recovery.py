"""
Module: test_interruption_recovery
Layer: integration/agent
Covers: agent/react_agent.py + agent/react_agent_runtime.py

Simulates user interruption mid-run and verifies that the emitted
conversation history (stream_end messages) is always in a consistent state
-- no orphan assistant+tool_calls without results, no orphan tool messages.
"""

import sys
import threading
import unittest
from pathlib import Path

from tests.managed_paths import ManagedPathTestCase

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner


class _SlowToolLLM:
    """LLM that emits tool calls; tool execution can be delayed via barrier."""

    def __init__(self, tool_call_count=1):
        self._tool_call_count = tool_call_count
        self._calls = 0

    def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        _ = tools
        _ = temperature
        self._calls += 1
        if self._calls == 1:
            tool_calls = [
                {
                    "id": f"call_{i}",
                    "name": "generate_stats",
                    "arguments": {},
                }
                for i in range(self._tool_call_count)
            ]
            return {"role": "assistant", "content": "", "tool_calls": tool_calls}
        return {"role": "assistant", "content": "final answer after tools", "tool_calls": []}


class _MultiStepLLM:
    """LLM that performs multiple tool-call steps before final answer."""

    def __init__(self):
        self._calls = 0

    def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        _ = tools
        _ = temperature
        self._calls += 1
        if self._calls <= 2:
            return {
                "role": "assistant",
                "content": f"Step {self._calls} thinking",
                "tool_calls": [
                    {
                        "id": f"call_step{self._calls}",
                        "name": "generate_stats",
                        "arguments": {},
                    }
                ],
            }
        return {"role": "assistant", "content": "multi-step done", "tool_calls": []}


def _validate_message_consistency(messages):
    """Assert that messages form valid tool-call/result groups.

    Returns list of error descriptions (empty means consistent).
    """
    errors = []
    if not messages:
        return errors

    # Check for orphan tool messages at the start
    if messages[0].get("role") == "tool":
        errors.append("orphan tool message at start")

    # Check each assistant+tool_calls has all results
    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        tc = msg.get("tool_calls")
        if not isinstance(tc, list) or not tc:
            continue

        expected_ids = set()
        for call in tc:
            if isinstance(call, dict):
                cid = str(call.get("id") or "").strip()
                if not cid:
                    fn = call.get("function")
                    if isinstance(fn, dict):
                        cid = str(fn.get("id") or "").strip()
                if cid:
                    expected_ids.add(cid)

        found_ids = set()
        for subsequent in messages[idx + 1:]:
            if subsequent.get("role") == "tool":
                tid = str(subsequent.get("tool_call_id") or "").strip()
                if tid:
                    found_ids.add(tid)
            elif subsequent.get("role") == "assistant":
                break

        missing = expected_ids - found_ids
        if missing:
            errors.append(
                f"assistant at index {idx} missing tool results for: {missing}"
            )

    return errors


class TestInterruptionRecovery(ManagedPathTestCase):
    """Integration tests for interruption + context recovery."""

    def test_stop_during_tool_execution_yields_consistent_history(self):
        """Stop event set while tools are running -- stream_end messages must be consistent."""
        llm = _SlowToolLLM(tool_call_count=2)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=5)

        stop_event = threading.Event()
        stream_end_data = {}

        def _on_event(evt):
            evt = dict(evt or {})
            # Stop after the first tool_start event
            if evt.get("event") == "tool_start":
                stop_event.set()
            if evt.get("event") == "stream_end":
                stream_end_data.update(evt.get("data") or {})

        result = agent.run("run stats", on_event=_on_event, stop_event=stop_event)

        self.assertFalse(result.get("ok", True))
        self.assertEqual("run_stopped", result.get("error_code"))

        messages = stream_end_data.get("messages") or []
        errors = _validate_message_consistency(messages)
        self.assertEqual(
            [],
            errors,
            f"stream_end messages are inconsistent: {errors}",
        )

    def test_stop_between_steps_yields_consistent_history(self):
        """Stop event set between LLM steps -- history should be clean."""
        llm = _MultiStepLLM()
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=10)

        stop_event = threading.Event()
        stream_end_data = {}
        tool_end_count = 0

        def _on_event(evt):
            nonlocal tool_end_count
            evt = dict(evt or {})
            if evt.get("event") == "tool_end":
                tool_end_count += 1
                if tool_end_count >= 1:
                    # Stop after the first complete tool round
                    stop_event.set()
            if evt.get("event") == "stream_end":
                stream_end_data.update(evt.get("data") or {})

        result = agent.run("multi step", on_event=_on_event, stop_event=stop_event)

        self.assertFalse(result.get("ok", True))
        messages = stream_end_data.get("messages") or []
        errors = _validate_message_consistency(messages)
        self.assertEqual(
            [],
            errors,
            f"stream_end messages are inconsistent: {errors}",
        )

    def test_interrupted_history_usable_in_next_run(self):
        """History from an interrupted run can be passed to a new run without errors."""
        llm = _SlowToolLLM(tool_call_count=1)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=5)

        stop_event = threading.Event()
        stream_end_messages = []

        def _on_event(evt):
            evt = dict(evt or {})
            if evt.get("event") == "tool_start":
                stop_event.set()
            if evt.get("event") == "stream_end":
                stream_end_messages.extend((evt.get("data") or {}).get("messages") or [])

        agent.run("first run", on_event=_on_event, stop_event=stop_event)

        # Now use that history in a new run
        class _EchoLLM:
            def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
                return {"role": "assistant", "content": "resumed ok", "tool_calls": []}

        new_llm = _EchoLLM()
        agent2 = ReactAgent(llm_client=new_llm, tool_runner=runner, max_steps=3)
        result = agent2.run("continue", conversation_history=stream_end_messages)

        self.assertTrue(result["ok"])
        self.assertEqual("resumed ok", result["final"])

    def test_normal_completion_history_is_consistent(self):
        """Normal (non-interrupted) run also produces consistent history."""
        llm = _SlowToolLLM(tool_call_count=1)
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=5)

        stream_end_data = {}

        def _on_event(evt):
            evt = dict(evt or {})
            if evt.get("event") == "stream_end":
                stream_end_data.update(evt.get("data") or {})

        result = agent.run("normal run", on_event=_on_event)

        self.assertTrue(result["ok"])
        messages = stream_end_data.get("messages") or []
        errors = _validate_message_consistency(messages)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
