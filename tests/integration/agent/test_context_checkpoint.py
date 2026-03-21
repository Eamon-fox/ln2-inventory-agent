"""
Module: test_context_checkpoint
Layer: integration/agent
Covers: agent/context_checkpoint.py + agent/react_agent_runtime.py

External checkpoint summaries should be generated with the active model and
re-attached to the main agent call via a fixed resume prompt.
"""

import sys
import unittest
from pathlib import Path

from tests.managed_paths import ManagedPathTestCase


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.context_checkpoint import RESUME_CONTEXT_PROMPT, SUMMARY_SYSTEM_PROMPT
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner


class _CheckpointAwareLLM:
    PROVIDER_NAME = "Zhipu"

    def __init__(self):
        self._model = "glm-5"
        self._context_window = 2_000
        self._main_output_reserve = 300
        self._summary_output_reserve = 300
        self._context_safety_margin = 300
        self.calls = []

    def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        _ = temperature
        _ = stop_event
        first_system = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                first_system = str(msg.get("content") or "")
                break

        if first_system == SUMMARY_SYSTEM_PROMPT:
            self.calls.append({"kind": "summary", "messages": list(messages or []), "tools": tools})
            return {
                "role": "assistant",
                "content": (
                    "## Current Objective\nContinue import validation.\n\n"
                    "## Completed Work\n- Reviewed previous steps.\n\n"
                    "## Confirmed Facts\n- Dataset path is known.\n\n"
                    "## Pending Work\n- Continue the current request.\n\n"
                    "## Open Risks / Questions\n- None.\n\n"
                    "## Last Reliable State\n- Resume from the latest tool-visible state."
                ),
                "tool_calls": [],
            }

        self.calls.append({"kind": "main", "messages": list(messages or []), "tools": tools})
        return {"role": "assistant", "content": "continued", "tool_calls": []}


class ContextCheckpointTests(ManagedPathTestCase):
    def _build_long_history(self):
        chunk = "A" * 320
        history = []
        for idx in range(1, 8):
            history.extend(
                [
                    {"role": "user", "content": f"user-{idx} {chunk}"},
                    {"role": "assistant", "content": f"assistant-{idx} {chunk}"},
                ]
            )
        return history

    def test_run_creates_external_checkpoint_before_main_call(self):
        llm = _CheckpointAwareLLM()
        runner = AgentToolRunner(yaml_path=self.fake_yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=1)
        events = []

        result = agent.run(
            "continue the long-running task",
            conversation_history=self._build_long_history(),
            on_event=lambda event: events.append(dict(event)),
        )

        self.assertTrue(result["ok"])
        self.assertEqual("continued", result["final"])
        self.assertEqual("zhipu", (result.get("summary_state") or {}).get("provider"))
        self.assertEqual("glm-5", (result.get("summary_state") or {}).get("model"))

        summary_calls = [call for call in llm.calls if call["kind"] == "summary"]
        self.assertGreaterEqual(len(summary_calls), 1)
        self.assertTrue(all(call["tools"] is None for call in summary_calls))
        self.assertTrue(
            all(call["messages"][0]["content"] == SUMMARY_SYSTEM_PROMPT for call in summary_calls)
        )

        main_calls = [call for call in llm.calls if call["kind"] == "main"]
        self.assertEqual(1, len(main_calls))
        main_messages = list(main_calls[0]["messages"] or [])
        self.assertTrue(any(str(msg.get("content") or "") == RESUME_CONTEXT_PROMPT for msg in main_messages))
        self.assertTrue(
            any("Checkpoint summary (" in str(msg.get("content") or "") for msg in main_messages),
            "Main call should include checkpoint summary message.",
        )

        checkpoint_events = [event for event in events if event.get("event") == "context_checkpoint"]
        self.assertGreaterEqual(len(checkpoint_events), 1)

        stream_end = next((event for event in events if event.get("event") == "stream_end"), None)
        if not isinstance(stream_end, dict):
            self.fail("stream_end event should be emitted")
        self.assertEqual(
            "glm-5",
            ((stream_end.get("data") or {}).get("summary_state") or {}).get("model"),
        )


if __name__ == "__main__":
    unittest.main()
