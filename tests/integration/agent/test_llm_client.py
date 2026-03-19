"""
Module: test_llm_client
Layer: integration/agent
Covers: agent/llm_client.py

LLM client request shaping and response normalization.
"""

import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.llm_client import DeepSeekLLMClient, MiniMaxLLMClient, ZhipuLLMClient


class _FakeUrlopenResponse:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type
        _ = exc
        _ = tb
        return False

    def close(self):
        self.closed = True


def _decode_request_body(req):
    raw_body = req.data if isinstance(req.data, (bytes, bytearray)) else b"{}"
    return json.loads(raw_body.decode("utf-8"))


class LlmContentNormalizationTests(unittest.TestCase):
    def test_normalize_content_handles_nested_blocks(self):
        payload = [
            {"type": "text", "text": "Hello"},
            {"type": "container", "content": [{"text": " world"}]},
        ]

        text = DeepSeekLLMClient._normalize_content(payload)
        self.assertEqual("Hello world", text)

    def test_extract_content_from_choice_uses_reasoning_fallback(self):
        choice = {"message": {}}
        message = {"content": None, "reasoning_content": "fallback text"}

        text = DeepSeekLLMClient._extract_content_from_choice(choice, message)
        self.assertEqual("fallback text", text)


class DeepSeekClientParseTests(unittest.TestCase):
    def test_build_request_enables_thinking_by_default(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}]))
        self.assertEqual({"type": "enabled"}, body.get("thinking"))

    def test_build_request_can_disable_thinking(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat", thinking_enabled=False)

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}]))
        self.assertNotIn("thinking", body)

    def test_stream_chat_yields_incremental_answer_and_tool_call(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        tool_chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_a",
                                "function": {
                                    "name": "query_inventory",
                                    "arguments": '{"cell":"K562"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'Hel'}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'lo'}}]})}",
            f"data: {json.dumps(tool_chunk)}",
            "data: [DONE]",
        ]

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            events = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))

        answer_parts = [evt.get("text") for evt in events if evt.get("type") == "answer"]
        self.assertEqual(["Hel", "lo"], answer_parts)

        tool_events = [evt for evt in events if evt.get("type") == "tool_call"]
        self.assertEqual(1, len(tool_events))
        tool_call = tool_events[0].get("tool_call") or {}
        self.assertEqual("query_inventory", tool_call.get("name"))
        self.assertEqual({"cell": "K562"}, tool_call.get("arguments"))

    def test_stream_chat_yields_thought_chunks(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': 'think '}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': 'step'}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'answer'}}]})}",
            "data: [DONE]",
        ]

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            events = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[]))

        thoughts = [evt.get("text") for evt in events if evt.get("type") == "thought"]
        answers = [evt.get("text") for evt in events if evt.get("type") == "answer"]
        self.assertEqual(["think ", "step"], thoughts)
        self.assertEqual(["answer"], answers)

    def test_chat_parses_sse_content_and_tool_calls(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        tool_call_part1 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "search_records",
                                    "arguments": '{"query":"K562"',
                                },
                            }
                        ]
                    }
                }
            ]
        }
        tool_call_part2 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "arguments": ',"mode":"keywords"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'Hello '}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'world'}}]})}",
            f"data: {json.dumps(tool_call_part1)}",
            f"data: {json.dumps(tool_call_part2)}",
            "data: [DONE]",
        ]

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            response = client.chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

        self.assertEqual("Hello world", response.get("content"))
        tool_calls = response.get("tool_calls") or []
        self.assertEqual(1, len(tool_calls))
        self.assertEqual("search_records", tool_calls[0].get("name"))
        self.assertEqual({"query": "K562", "mode": "keywords"}, tool_calls[0].get("arguments"))

    def test_stream_chat_parses_plain_json_payload(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        payload = {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "plan",
                        "content": [{"type": "text", "text": " answer"}],
                        "tool_calls": [
                            {
                                "id": "call_plain",
                                "function": {
                                    "name": "lookup_box",
                                    "arguments": '{"box": 3}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse([json.dumps(payload)])):
            events = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))

        thoughts = [evt.get("text") for evt in events if evt.get("type") == "thought"]
        answers = [evt.get("text") for evt in events if evt.get("type") == "answer"]
        tool_events = [evt for evt in events if evt.get("type") == "tool_call"]
        self.assertEqual(["plan"], thoughts)
        self.assertEqual([" answer"], answers)
        self.assertEqual(1, len(tool_events))
        self.assertEqual({"box": 3}, tool_events[0]["tool_call"]["arguments"])

    def test_stream_chat_stops_when_stop_event_is_set(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat")

        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'first'}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'second'}}]})}",
            "data: [DONE]",
        ]

        stop_event = threading.Event()
        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            iterator = client.stream_chat(messages=[{"role": "user", "content": "hi"}], stop_event=stop_event)
            first = next(iterator)
            stop_event.set()
            remaining = list(iterator)

        self.assertEqual({"type": "answer", "text": "first"}, first)
        self.assertEqual([], remaining)


class ZhipuClientParseTests(unittest.TestCase):
    def test_build_request_disables_thinking_by_default(self):
        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "test-key"}, clear=False):
            client = ZhipuLLMClient(model="glm-5")

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}]))
        self.assertEqual({"type": "disabled"}, body.get("thinking"))

    def test_build_request_can_enable_thinking(self):
        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "test-key"}, clear=False):
            client = ZhipuLLMClient(model="glm-5", thinking_enabled=True)

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}]))
        self.assertEqual({"type": "enabled"}, body.get("thinking"))

    def test_build_request_uses_project_headers_without_cline_markers(self):
        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "test-key"}, clear=False):
            client = ZhipuLLMClient(model="glm-5")

        headers = {
            str(name or "").casefold(): str(value or "")
            for name, value in client._build_request(messages=[{"role": "user", "content": "hi"}]).header_items()
        }
        self.assertEqual("application/json", headers.get("accept"))
        self.assertEqual("SnowFox/1.2.3", headers.get("user-agent"))
        self.assertNotIn("http-referer", headers)
        self.assertNotIn("x-title", headers)
        self.assertNotIn("x-cline-version", headers)

    def test_stream_chat_yields_answer_thought_and_tool_call(self):
        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "test-key"}, clear=False):
            client = ZhipuLLMClient(model="glm-5")

        tool_chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_zhipu",
                                "function": {
                                    "name": "query_inventory",
                                    "arguments": '{"sample":"A1"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': 'check '}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'ready'}}]})}",
            f"data: {json.dumps(tool_chunk)}",
            "data: [DONE]",
        ]

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            events = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))

        thoughts = [evt.get("text") for evt in events if evt.get("type") == "thought"]
        answers = [evt.get("text") for evt in events if evt.get("type") == "answer"]
        tool_calls = [evt.get("tool_call") for evt in events if evt.get("type") == "tool_call"]
        self.assertEqual(["check "], thoughts)
        self.assertEqual(["ready"], answers)
        self.assertEqual(1, len(tool_calls))
        self.assertEqual("query_inventory", tool_calls[0]["name"])
        self.assertEqual({"sample": "A1"}, tool_calls[0]["arguments"])


class MiniMaxClientParseTests(unittest.TestCase):
    def test_build_request_uses_project_headers_without_cline_markers(self):
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            client = MiniMaxLLMClient(model="MiniMax-M2.5-highspeed")

        headers = {
            str(name or "").casefold(): str(value or "")
            for name, value in client._build_request(messages=[{"role": "user", "content": "hi"}]).header_items()
        }
        self.assertEqual("application/json", headers.get("accept"))
        self.assertEqual("SnowFox/1.2.3", headers.get("user-agent"))
        self.assertNotIn("http-referer", headers)
        self.assertNotIn("x-title", headers)
        self.assertNotIn("x-cline-version", headers)

    def test_build_request_uses_default_temperature_and_reasoning_split(self):
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            client = MiniMaxLLMClient(model="MiniMax-M2.5-highspeed")

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}], temperature=0.0))
        self.assertEqual(1.0, body.get("temperature"))
        self.assertTrue(body.get("reasoning_split"))

    def test_build_request_can_disable_reasoning_split(self):
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            client = MiniMaxLLMClient(model="MiniMax-M2.5-highspeed", thinking_enabled=False)

        body = _decode_request_body(client._build_request(messages=[{"role": "user", "content": "hi"}], temperature=0.25))
        self.assertEqual(0.25, body.get("temperature"))
        self.assertNotIn("reasoning_split", body)

    def test_stream_chat_yields_reasoning_details_and_tool_call(self):
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "test-key"}, clear=False):
            client = MiniMaxLLMClient(model="MiniMax-M2.5-highspeed")

        tool_chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_minimax",
                                "function": {
                                    "name": "reserve_box",
                                    "arguments": '{"box":"B2"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'reasoning_details': [{'text': 'trace'}]}}]})}",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'done'}}]})}",
            f"data: {json.dumps(tool_chunk)}",
            "data: [DONE]",
        ]

        with patch("agent.llm_client.urlrequest.urlopen", return_value=_FakeUrlopenResponse(lines)):
            events = list(client.stream_chat(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))

        thoughts = [evt.get("text") for evt in events if evt.get("type") == "thought"]
        answers = [evt.get("text") for evt in events if evt.get("type") == "answer"]
        tool_calls = [evt.get("tool_call") for evt in events if evt.get("type") == "tool_call"]
        self.assertEqual(["trace"], thoughts)
        self.assertEqual(["done"], answers)
        self.assertEqual(1, len(tool_calls))
        self.assertEqual("reserve_box", tool_calls[0]["name"])
        self.assertEqual({"box": "B2"}, tool_calls[0]["arguments"])


if __name__ == "__main__":
    unittest.main()
