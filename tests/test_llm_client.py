import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.llm_client import DeepSeekLLMClient, load_opencode_auth_env


class _FakeUrlopenResponse:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type
        _ = exc
        _ = tb
        return False


def write_auth_json(path):
    payload = {
        "deepseek": {"type": "api", "key": "deepseek-test-key"},
        "moonshotai-cn": {"type": "api", "key": "kimi-test-key"},
        "zhipuai-coding-plan": {"type": "api", "key": "zhipu-test-key"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class LlmClientAuthTests(unittest.TestCase):
    def test_load_opencode_auth_env_sets_provider_keys(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "",
                    "MOONSHOT_API_KEY": "",
                    "KIMI_API_KEY": "",
                    "ZHIPUAI_API_KEY": "",
                    "ZHIPU_API_KEY": "",
                    "GLM_API_KEY": "",
                },
                clear=False,
            ):
                result = load_opencode_auth_env(auth_file=str(auth_path))
                self.assertTrue(result["ok"])
                self.assertEqual("deepseek-test-key", os.environ.get("DEEPSEEK_API_KEY"))
                self.assertEqual("kimi-test-key", os.environ.get("MOONSHOT_API_KEY"))
                self.assertEqual("kimi-test-key", os.environ.get("KIMI_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("ZHIPUAI_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("ZHIPU_API_KEY"))
                self.assertEqual("zhipu-test-key", os.environ.get("GLM_API_KEY"))

    def test_load_opencode_auth_env_does_not_override_by_default(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_no_override_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "existing"}, clear=False):
                result = load_opencode_auth_env(auth_file=str(auth_path), force=False)
                self.assertTrue(result["ok"])
                self.assertEqual("existing", os.environ.get("DEEPSEEK_API_KEY"))

    def test_load_opencode_auth_env_force_overrides(self):
        with tempfile.TemporaryDirectory(prefix="ln2_auth_force_") as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            write_auth_json(auth_path)

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "existing"}, clear=False):
                result = load_opencode_auth_env(auth_file=str(auth_path), force=True)
                self.assertTrue(result["ok"])
                self.assertEqual("deepseek-test-key", os.environ.get("DEEPSEEK_API_KEY"))

    def test_load_opencode_auth_env_handles_missing_file(self):
        result = load_opencode_auth_env(auth_file="/tmp/non-existent-opencode-auth.json")
        self.assertFalse(result["ok"])
        self.assertEqual("missing_auth_file", result.get("reason"))


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

        req = client._build_request(messages=[{"role": "user", "content": "hi"}])
        raw_body = req.data if isinstance(req.data, (bytes, bytearray)) else b"{}"
        body = json.loads(raw_body.decode("utf-8"))

        self.assertEqual({"type": "enabled"}, body.get("thinking"))

    def test_build_request_can_disable_thinking(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            client = DeepSeekLLMClient(model="deepseek-chat", thinking_enabled=False)

        req = client._build_request(messages=[{"role": "user", "content": "hi"}])
        raw_body = req.data if isinstance(req.data, (bytes, bytearray)) else b"{}"
        body = json.loads(raw_body.decode("utf-8"))

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


if __name__ == "__main__":
    unittest.main()
