import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from lib.yaml_ops import write_yaml


def make_data(records):
    return {
        "meta": {"box_layout": {"rows": 9, "cols": 9}},
        "inventory": records,
    }


class _SequenceLLM:
    def __init__(self, outputs):
        self._outputs = list(outputs)

    def chat(self, messages, tools=None, temperature=0.0):
        _ = messages
        _ = tools
        _ = temperature
        if not self._outputs:
            return {"role": "assistant", "content": "done", "tool_calls": []}
        return self._outputs.pop(0)


class _CapturePromptLLM:
    def __init__(self):
        self.last_messages = None
        self.last_tools = None

    def chat(self, messages, tools=None, temperature=0.0):
        _ = temperature
        self.last_messages = messages
        self.last_tools = tools
        return {"role": "assistant", "content": "ok", "tool_calls": []}


class _ToolsSensitiveLLM:
    def __init__(self):
        self.calls = []

    def chat(self, messages, tools=None, temperature=0.0):
        _ = messages
        _ = temperature
        self.calls.append({"tools_enabled": bool(tools)})
        if tools:
            return {"role": "assistant", "content": "", "tool_calls": []}
        return {"role": "assistant", "content": "direct fallback answer", "tool_calls": []}


class _StreamingLLM:
    def stream_chat(self, messages, tools=None, temperature=0.0):
        _ = messages
        _ = tools
        _ = temperature
        yield {"type": "answer", "text": "Hello"}
        yield {"type": "answer", "text": " world"}


class _StreamingThoughtLLM:
    def stream_chat(self, messages, tools=None, temperature=0.0):
        _ = messages
        _ = tools
        _ = temperature
        yield {"type": "thought", "text": "thinking "}
        yield {"type": "thought", "text": "about it"}
        yield {"type": "answer", "text": "Done"}


class _StreamingToolThenAnswerLLM:
    def __init__(self):
        self.calls = 0
        self.second_call_messages = None

    def stream_chat(self, messages, tools=None, temperature=0.0):
        _ = tools
        _ = temperature
        self.calls += 1
        if self.calls == 1:
            yield {"type": "thought", "text": "tool reasoning"}
            yield {
                "type": "tool_call",
                "tool_call": {
                    "id": "call_1",
                    "name": "query_inventory",
                    "arguments": {"cell": "K562"},
                },
            }
            return

        self.second_call_messages = list(messages or [])
        yield {"type": "answer", "text": "done"}


class ReactAgentTests(unittest.TestCase):
    def test_react_agent_calls_tool_then_finishes(self):
        with tempfile.TemporaryDirectory(prefix="ln2_react_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([
                    {
                        "id": 1,
                        "cell_line": "K562",
                        "short_name": "k562-a",
                        "box": 1,
                        "position": 1,
                        "frozen_at": "2026-02-10",
                    }
                ]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            llm = _SequenceLLM(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "name": "search_records",
                                "arguments": {"query": "K562"},
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": "Found one K562 record.",
                        "tool_calls": [],
                    },
                ]
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=4)
            events = []
            result = agent.run("Find K562 entries", on_event=lambda e: events.append(dict(e)))

            self.assertTrue(result["ok"])
            self.assertEqual("Found one K562 record.", result["final"])
            self.assertNotIn("scratchpad", result)

            tool_end_events = [e for e in events if e.get("event") == "tool_end"]
            self.assertGreaterEqual(len(tool_end_events), 1)
            obs = tool_end_events[0].get("observation") or {}
            self.assertTrue(obs["ok"])
            result_payload = obs.get("result") or {}
            self.assertEqual(1, result_payload.get("total_count"))

            tool_start = next((e for e in events if e.get("event") == "tool_start"), None)
            if not isinstance(tool_start, dict):
                self.fail("tool_start event should be emitted")
            self.assertIn("tool_call_id", (tool_start.get("data") or {}).get("input", {}))

            tool_end_data = tool_end_events[0].get("data") or {}
            output = tool_end_data.get("output") or {}
            self.assertIn("tool_call_id", output)
            self.assertIsInstance(output.get("content"), str)

            event_names = [e.get("event") for e in events]
            self.assertIn("run_start", event_names)
            self.assertIn("step_start", event_names)
            self.assertIn("tool_start", event_names)
            self.assertIn("tool_end", event_names)
            self.assertIn("final", event_names)
            self.assertIn("stream_end", event_names)

    def test_react_agent_unknown_tool_observation_has_hint(self):
        llm = _SequenceLLM(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_unknown",
                            "name": "made_up_tool",
                            "arguments": {},
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": [],
                },
            ]
        )
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=3)
        events = []

        result = agent.run("do something", on_event=lambda e: events.append(dict(e)))

        self.assertTrue(result["ok"])
        self.assertNotIn("scratchpad", result)

        tool_end_events = [e for e in events if e.get("event") == "tool_end"]
        self.assertGreaterEqual(len(tool_end_events), 1)
        obs = tool_end_events[0].get("observation") or {}
        self.assertFalse(obs["ok"])
        self.assertEqual("unknown_tool", obs["error_code"])
        self.assertTrue(obs.get("_hint"))

    def test_react_agent_manage_boxes_waits_for_gui_confirmation(self):
        llm = _SequenceLLM(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_manage_boxes",
                            "name": "manage_boxes",
                            "arguments": {"action": "add", "count": 1},
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": [],
                },
            ]
        )

        with tempfile.TemporaryDirectory(prefix="ln2_react_manage_boxes_") as temp_dir:
            yaml_path = Path(temp_dir) / "inventory.yaml"
            write_yaml(
                make_data([]),
                path=str(yaml_path),
                audit_meta={"action": "seed", "source": "tests"},
            )

            runner = AgentToolRunner(yaml_path=str(yaml_path))
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=3)
            events = []

            def _on_event(evt):
                payload = dict(evt or {})
                events.append(payload)
                if payload.get("type") == "manage_boxes_confirm":
                    runner._set_answer(
                        {
                            "ok": True,
                            "result": {"confirmed": True},
                            "message": "confirmed by user",
                        }
                    )

            result = agent.run("add one box", on_event=_on_event)

            self.assertTrue(result["ok"])
            self.assertEqual("done", result["final"])
            self.assertTrue(any(e.get("type") == "manage_boxes_confirm" for e in events))

    def test_react_agent_question_returns_answer_and_index(self):
        llm = _SequenceLLM(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_question",
                            "name": "question",
                            "arguments": {
                                "question": "Proceed with takeout?",
                                "options": ["yes", "no"],
                            },
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "ok",
                    "tool_calls": [],
                },
            ]
        )

        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=3)
        events = []

        def _on_event(evt):
            payload = dict(evt or {})
            events.append(payload)
            if payload.get("type") == "question":
                runner._set_answer("no")

        result = agent.run("confirm", on_event=_on_event)

        self.assertTrue(result["ok"])
        self.assertEqual("ok", result["final"])
        tool_end = next(
            (
                e
                for e in events
                if e.get("event") == "tool_end" and e.get("action") == "question"
            ),
            None,
        )
        if not isinstance(tool_end, dict):
            self.fail("question tool_end event should exist")
        obs = tool_end.get("observation") or {}
        self.assertTrue(obs.get("ok"))
        self.assertEqual("no", obs.get("answer"))
        self.assertEqual(1, obs.get("index"))

    def test_react_agent_includes_conversation_history_in_prompt(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=2)

        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
            {"role": "tool", "content": "ignored"},
        ]
        result = agent.run("repeat your last response", conversation_history=history)

        self.assertTrue(result["ok"])
        self.assertEqual(2, result.get("conversation_history_used"))
        messages = llm.last_messages
        if not isinstance(messages, list):
            self.fail("LLM should receive a message list")
        self.assertGreaterEqual(len(messages), 4)

        self.assertEqual("system", messages[0].get("role"))

        tools = llm.last_tools
        if not isinstance(tools, list):
            self.fail("tools should be provided for native tool-calling")
        self.assertGreater(len(tools), 0)
        search_schema = next((item for item in tools if item.get("function", {}).get("name") == "search_records"), None)
        if not isinstance(search_schema, dict):
            self.fail("search_records schema should be exposed")
        mode_schema = (
            search_schema.get("function", {})
            .get("parameters", {})
            .get("properties", {})
            .get("mode", {})
        )
        self.assertEqual(["fuzzy", "exact", "keywords"], mode_schema.get("enum"))

        memory = [m for m in messages if m.get("role") in {"user", "assistant"}]
        self.assertEqual("user", memory[0]["role"])
        self.assertEqual("hi", memory[0]["content"])
        self.assertEqual("assistant", memory[1]["role"])
        self.assertEqual("hello there", memory[1]["content"])

    def test_react_agent_retries_when_final_text_empty(self):
        llm = _SequenceLLM(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "query_inventory",
                            "arguments": {"cell": "K562"},
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [],
                },
                {
                    "role": "assistant",
                    "content": "final reply",
                    "tool_calls": [],
                },
            ]
        )
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=4)

        result = agent.run("say something")

        self.assertTrue(result["ok"])
        self.assertEqual("final reply", result["final"])
        self.assertGreaterEqual(result.get("steps", 0), 2)

    def test_react_agent_uses_direct_answer_when_tool_mode_returns_empty(self):
        llm = _ToolsSensitiveLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=2)

        result = agent.run("say hello")

        self.assertTrue(result["ok"])
        self.assertEqual("direct fallback answer", result["final"])
        self.assertGreaterEqual(len(llm.calls), 2)
        self.assertTrue(llm.calls[0]["tools_enabled"])
        self.assertFalse(llm.calls[-1]["tools_enabled"])

    def test_react_agent_emits_incremental_chunk_events_from_stream_chat(self):
        llm = _StreamingLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=2)
        events = []

        result = agent.run("say hello", on_event=lambda e: events.append(dict(e)))

        self.assertTrue(result["ok"])
        self.assertEqual("Hello world", result["final"])

        chunks = [e.get("data") for e in events if e.get("event") == "chunk"]
        self.assertEqual(["Hello", " world"], chunks)

    def test_react_agent_emits_thought_chunks_on_thought_channel(self):
        llm = _StreamingThoughtLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=2)
        events = []

        result = agent.run("think", on_event=lambda e: events.append(dict(e)))

        self.assertTrue(result["ok"])
        self.assertEqual("Done", result["final"])
        thought_chunks = [
            e.get("data")
            for e in events
            if e.get("event") == "chunk" and ((e.get("meta") or {}).get("channel") == "thought")
        ]
        self.assertEqual(["thinking ", "about it"], thought_chunks)

    def test_react_agent_keeps_reasoning_content_in_tool_assistant_message(self):
        llm = _StreamingToolThenAnswerLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=3)

        result = agent.run("lookup")

        self.assertTrue(result["ok"])
        self.assertEqual("done", result["final"])
        self.assertIsInstance(llm.second_call_messages, list)
        second_messages = llm.second_call_messages if isinstance(llm.second_call_messages, list) else []

        assistant_tool_msg = next(
            (
                msg
                for msg in second_messages
                if isinstance(msg, dict)
                and msg.get("role") == "assistant"
                and isinstance(msg.get("tool_calls"), list)
                and msg.get("tool_calls")
            ),
            None,
        )
        self.assertIsNotNone(assistant_tool_msg)
        assistant_tool_msg = assistant_tool_msg if isinstance(assistant_tool_msg, dict) else {}
        self.assertEqual("tool reasoning", assistant_tool_msg.get("reasoning_content"))

    def test_react_agent_final_uses_last_answer_after_tool_steps(self):
        llm = _SequenceLLM(
            [
                {
                    "role": "assistant",
                    "content": "I will check stats first.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "generate_stats",
                            "arguments": {},
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Final answer only.",
                    "tool_calls": [],
                },
            ]
        )
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=3)

        result = agent.run("overview")

        self.assertTrue(result["ok"])
        self.assertEqual("Final answer only.", result["final"])

    def test_custom_prompt_appended_to_system_message(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(
            llm_client=llm, tool_runner=runner,
            custom_prompt="请用中文回答所有问题",
        )

        agent.run("hello")

        system_msg = llm.last_messages[0]
        self.assertEqual("system", system_msg["role"])
        self.assertIn("Additional user instructions:", system_msg["content"])
        self.assertIn("请用中文回答所有问题", system_msg["content"])
        # Core rules must still be present
        self.assertIn("LN2 inventory assistant", system_msg["content"])
        self.assertIn("Non-overridable execution policy", system_msg["content"])
        self.assertIn("single source of truth", system_msg["content"])
        self.assertNotIn("single language only", system_msg["content"])

    def test_system_prompt_avoids_hardcoded_v2_parameter_templates(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner)

        agent.run("check prompt")

        system_msg = llm.last_messages[0]
        self.assertEqual("system", system_msg["role"])
        self.assertIn("tool_schemas", system_msg["content"])
        self.assertNotIn("`record_takeout`: {record_id", system_msg["content"])
        self.assertNotIn("`record_move`: {record_id", system_msg["content"])
        self.assertNotIn("`batch_takeout`: {entries", system_msg["content"])
        self.assertNotIn("`batch_move`: {entries", system_msg["content"])

    def test_system_prompt_includes_current_inventory_yaml_path(self):
        llm = _CapturePromptLLM()
        yaml_path = "/tmp/current_inventory.yaml"
        runner = AgentToolRunner(yaml_path=yaml_path)
        agent = ReactAgent(llm_client=llm, tool_runner=runner)

        agent.run("check prompt context")

        system_msg = llm.last_messages[0]
        self.assertEqual("system", system_msg["role"])
        content = str(system_msg.get("content") or "")
        self.assertIn("Current time:", content)
        self.assertIn(f"Current inventory (yaml_path): {yaml_path}", content)
        self.assertLess(content.index("Current time:"), content.index("Current inventory (yaml_path):"))

    def test_numeric_option_reply_is_expanded_from_recent_assistant_options(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner)

        history = [
            {
                "role": "assistant",
                "content": "1) Inspect current value\n2) Edit record #16 to valid cell_line",
            }
        ]

        agent.run("2", conversation_history=history)

        user_msg = next((m for m in reversed(llm.last_messages) if m.get("role") == "user"), None)
        if not isinstance(user_msg, dict):
            self.fail("User message should exist in prompt payload")
        self.assertEqual("user", user_msg["role"])
        self.assertIn("choose option 2", user_msg["content"].lower())
        self.assertIn("edit record #16", user_msg["content"].lower())

    def test_empty_custom_prompt_not_appended(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner, custom_prompt="")

        agent.run("hello")

        system_msg = llm.last_messages[0]
        self.assertNotIn("Additional user instructions:", system_msg["content"])

    def test_no_custom_prompt_by_default(self):
        llm = _CapturePromptLLM()
        runner = AgentToolRunner(yaml_path="/tmp/nonexistent.yaml")
        agent = ReactAgent(llm_client=llm, tool_runner=runner)

        agent.run("hello")

        system_msg = llm.last_messages[0]
        self.assertNotIn("Additional user instructions:", system_msg["content"])


if __name__ == "__main__":
    unittest.main()
