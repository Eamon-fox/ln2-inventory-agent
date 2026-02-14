"""LLM client abstractions for ReAct agent runtime."""

import json
import os
import uuid
from abc import ABC, abstractmethod
from urllib import error as urlerror
from urllib import request as urlrequest


PROVIDER_DEFAULTS = {
    "deepseek": {
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
    },
    "zhipu": {
        "model": "glm-5",
        "env_key": "ZHIPUAI_API_KEY",
        "display_name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
}

DEFAULT_PROVIDER = "deepseek"


class LLMClient(ABC):
    """Simple chat completion client interface."""

    @abstractmethod
    def chat(self, messages, tools=None, temperature=0.0):
        """Return assistant response payload with optional tool calls."""
        raise NotImplementedError

    def stream_chat(self, messages, tools=None, temperature=0.0):
        """Yield normalized stream events (answer/tool_call/error)."""
        response = self.chat(messages, tools=tools, temperature=temperature)
        if not isinstance(response, dict):
            yield {"type": "error", "error": "Invalid model response payload"}
            return

        content = str(response.get("content") or "")
        if content:
            yield {"type": "answer", "text": content}

        tool_calls = response.get("tool_calls") or []
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                yield {"type": "tool_call", "tool_call": tool_call}

    def complete(self, messages, temperature=0.0):
        """Compatibility wrapper returning assistant text only."""
        response = self.chat(messages, tools=None, temperature=temperature)
        if isinstance(response, dict):
            return str(response.get("content") or "")
        return str(response or "")


class DeepSeekLLMClient(LLMClient):
    """DeepSeek-native client with provider-side streaming parser."""

    def __init__(self, model=None, api_key=None, base_url=None, timeout=180, thinking_enabled=True):
        self._model = (model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        self._base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self._timeout = int(timeout)
        self._thinking_enabled = bool(thinking_enabled)
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")

        if not self._api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required")

    @classmethod
    def _normalize_content(cls, raw_content):
        if raw_content is None:
            return ""

        if isinstance(raw_content, str):
            return raw_content

        if isinstance(raw_content, dict):
            for key in ("text", "content", "output_text", "value"):
                text = cls._normalize_content(raw_content.get(key))
                if text:
                    return text
            return ""

        if isinstance(raw_content, list):
            chunks = []
            for item in raw_content:
                text = cls._normalize_content(item)
                if text:
                    chunks.append(text)
            return "".join(chunks)

        return ""

    @classmethod
    def _extract_content_from_choice(cls, choice, message):
        content = cls._normalize_content(message.get("content"))
        if content:
            return content

        if isinstance(choice, dict):
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = cls._normalize_content(delta.get("content"))
                if content:
                    return content

            for key in ("text", "output_text"):
                content = cls._normalize_content(choice.get(key))
                if content:
                    return content

        reasoning = cls._normalize_content(message.get("reasoning_content"))
        if reasoning:
            return reasoning
        return ""

    @classmethod
    def _extract_reasoning_from_choice(cls, choice, message):
        reasoning = cls._normalize_content(message.get("reasoning_content"))
        if reasoning:
            return reasoning

        if isinstance(choice, dict):
            delta = choice.get("delta")
            if isinstance(delta, dict):
                reasoning = cls._normalize_content(delta.get("reasoning_content"))
                if reasoning:
                    return reasoning

            reasoning = cls._normalize_content(choice.get("reasoning_content"))
            if reasoning:
                return reasoning

        return ""

    @staticmethod
    def _accumulate_tool_call(pending, tool_call):
        if not isinstance(tool_call, dict):
            return

        index = tool_call.get("index")
        tool_call_id = tool_call.get("id")
        if index is not None:
            key = f"index_{index}"
        elif tool_call_id:
            key = str(tool_call_id)
        else:
            key = f"auto_{len(pending)}"

        if key not in pending:
            pending[key] = {
                "id": tool_call_id,
                "function": {
                    "name": "",
                    "arguments": "",
                },
            }

        entry = pending[key]
        if tool_call_id:
            entry["id"] = tool_call_id

        func = tool_call.get("function") or {}

        name_part = func.get("name")
        if name_part:
            name_text = str(name_part)
            if not entry["function"]["name"]:
                entry["function"]["name"] = name_text
            elif not entry["function"]["name"].endswith(name_text):
                entry["function"]["name"] += name_text

        args_part = func.get("arguments")
        if args_part is not None:
            if isinstance(args_part, (dict, list)):
                args_text = json.dumps(args_part, ensure_ascii=False)
            else:
                args_text = str(args_part)
            entry["function"]["arguments"] += args_text

    @staticmethod
    def _parse_tool_arguments(raw_args):
        if isinstance(raw_args, dict):
            return raw_args

        text = str(raw_args or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            return {"_raw_arguments": parsed}
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                maybe_json = text[start : end + 1]
                try:
                    parsed = json.loads(maybe_json)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            return {"_raw_arguments": text}

    @classmethod
    def _finalize_tool_calls(cls, pending):
        finalized = []
        for index, entry in enumerate(pending.values()):
            func = entry.get("function") if isinstance(entry, dict) else None
            if not isinstance(func, dict):
                continue

            name = str(func.get("name") or "").strip()
            if not name:
                continue

            call_id = str(entry.get("id") or f"call_{uuid.uuid4().hex[:12]}_{index}")
            arguments = cls._parse_tool_arguments(func.get("arguments"))
            finalized.append(
                {
                    "id": call_id,
                    "name": name,
                    "arguments": arguments,
                }
            )
        return finalized

    def _build_request(self, messages, tools=None, temperature=0.0):
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        if self._thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = f"{self._base_url}/chat/completions"
        return urlrequest.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not isinstance(choices, list) or not choices:
            return

        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice, dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        delta = delta if isinstance(delta, dict) else {}
        message = message if isinstance(message, dict) else {}

        reasoning = self._normalize_content(delta.get("reasoning_content"))
        if not reasoning:
            reasoning = self._normalize_content(message.get("reasoning_content"))
        if reasoning:
            yield {"type": "thought", "text": reasoning}

        # Stream mode should prefer incremental delta chunks.
        content = self._normalize_content(delta.get("content"))
        if not content:
            content = self._normalize_content(message.get("content"))
        if content:
            yield {"type": "answer", "text": content}

        raw_tool_calls = delta.get("tool_calls") or message.get("tool_calls") or []
        if isinstance(raw_tool_calls, list):
            for tool_call in raw_tool_calls:
                self._accumulate_tool_call(pending_tool_calls, tool_call)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "tool_calls" and pending_tool_calls:
            for tool_call in self._finalize_tool_calls(pending_tool_calls):
                yield {"type": "tool_call", "tool_call": tool_call}
            pending_tool_calls.clear()

    def _yield_events_from_plain_payload(self, payload_obj, pending_tool_calls):
        choices = payload_obj.get("choices") if isinstance(payload_obj, dict) else None
        if not isinstance(choices, list) or not choices:
            return

        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        message = message if isinstance(message, dict) else {}

        reasoning = self._extract_reasoning_from_choice(choice, message)
        if reasoning:
            yield {"type": "thought", "text": reasoning}

        content = self._normalize_content(message.get("content"))
        if not content and isinstance(choice, dict):
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = self._normalize_content(delta.get("content"))

            if not content:
                for key in ("text", "output_text"):
                    content = self._normalize_content(choice.get(key))
                    if content:
                        break
        if content:
            yield {"type": "answer", "text": content}

        raw_tool_calls = message.get("tool_calls") or choice.get("tool_calls") or []
        if isinstance(raw_tool_calls, list):
            for tool_call in raw_tool_calls:
                self._accumulate_tool_call(pending_tool_calls, tool_call)

    def stream_chat(self, messages, tools=None, temperature=0.0):
        req = self._build_request(messages, tools=tools, temperature=temperature)

        pending_tool_calls = {}
        saw_sse = False
        plain_lines = []

        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    if not line.startswith("data:"):
                        plain_lines.append(line)
                        continue

                    saw_sse = True
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict) and chunk.get("error"):
                        err = chunk.get("error")
                        if isinstance(err, dict):
                            message = err.get("message") or json.dumps(err, ensure_ascii=False)
                        else:
                            message = str(err)
                        yield {"type": "error", "error": f"DeepSeek API error: {message}"}
                        return

                    for event in self._yield_events_from_chunk(chunk, pending_tool_calls):
                        yield event

            if not saw_sse and plain_lines:
                joined = "\n".join(plain_lines)
                try:
                    payload_obj = json.loads(joined)
                    for event in self._yield_events_from_plain_payload(payload_obj, pending_tool_calls):
                        yield event
                except Exception:
                    pass

            if pending_tool_calls:
                for tool_call in self._finalize_tool_calls(pending_tool_calls):
                    yield {"type": "tool_call", "tool_call": tool_call}

        except urlerror.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            detail = f"HTTP {exc.code}"
            if body_text:
                detail = f"{detail}: {body_text}"
            yield {"type": "error", "error": f"DeepSeek request failed ({detail})"}
        except urlerror.URLError as exc:
            yield {"type": "error", "error": f"DeepSeek request failed: {exc.reason}"}

    def chat(self, messages, tools=None, temperature=0.0):
        content_parts = []
        tool_calls = []

        for event in self.stream_chat(messages, tools=tools, temperature=temperature):
            if not isinstance(event, dict):
                continue

            event_type = str(event.get("type") or "").strip().lower()
            if event_type == "answer":
                text = str(event.get("text") or "")
                if text:
                    content_parts.append(text)
            elif event_type == "tool_call":
                tool_call = event.get("tool_call")
                if isinstance(tool_call, dict):
                    tool_calls.append(tool_call)
            elif event_type == "error":
                raise RuntimeError(str(event.get("error") or "DeepSeek stream failed"))

        return {
            "role": "assistant",
            "content": "".join(content_parts).strip(),
            "tool_calls": tool_calls,
        }


class ZhipuLLMClient(LLMClient):
    """智谱 AI (GLM) 客户端，OpenAI 兼容接口。"""

    def __init__(self, model=None, api_key=None, base_url=None, timeout=180, thinking_enabled=False):
        self._model = (model or os.environ.get("ZHIPU_MODEL") or "glm-5").strip()
        self._base_url = (base_url or os.environ.get("ZHIPU_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        self._timeout = int(timeout)
        self._thinking_enabled = bool(thinking_enabled)
        self._api_key = api_key or os.environ.get("ZHIPUAI_API_KEY") or os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")

        if not self._api_key:
            raise RuntimeError("ZHIPUAI_API_KEY is required. Set ZHIPU_API_KEY or ZHIPUAI_API_KEY env var.")

    def _build_request(self, messages, tools=None, temperature=0.0):
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = f"{self._base_url}/chat/completions"
        return urlrequest.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Cline-VSCode-Extension",
                "HTTP-Referer": "https://cline.bot",
                "X-Title": "Cline",
                "X-Cline-Version": "3.42.0",
            },
        )

    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not isinstance(choices, list) or not choices:
            return

        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice, dict) else {}
        delta = delta if isinstance(delta, dict) else {}

        reasoning = DeepSeekLLMClient._normalize_content(delta.get("reasoning_content"))
        if reasoning:
            yield {"type": "thought", "text": reasoning}

        content = DeepSeekLLMClient._normalize_content(delta.get("content"))
        if content:
            yield {"type": "answer", "text": content}

        raw_tool_calls = delta.get("tool_calls") or []
        if isinstance(raw_tool_calls, list):
            for tool_call in raw_tool_calls:
                DeepSeekLLMClient._accumulate_tool_call(pending_tool_calls, tool_call)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "tool_calls" and pending_tool_calls:
            for tool_call in DeepSeekLLMClient._finalize_tool_calls(pending_tool_calls):
                yield {"type": "tool_call", "tool_call": tool_call}
            pending_tool_calls.clear()

    def stream_chat(self, messages, tools=None, temperature=0.0):
        req = self._build_request(messages, tools=tools, temperature=temperature)

        pending_tool_calls = {}
        saw_sse = False
        plain_lines = []

        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    if not line.startswith("data:"):
                        plain_lines.append(line)
                        continue

                    saw_sse = True
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(chunk, dict) and chunk.get("error"):
                        err = chunk.get("error")
                        if isinstance(err, dict):
                            message = err.get("message") or json.dumps(err, ensure_ascii=False)
                        else:
                            message = str(err)
                        yield {"type": "error", "error": f"Zhipu API error: {message}"}
                        return

                    for event in self._yield_events_from_chunk(chunk, pending_tool_calls):
                        yield event

            if not saw_sse and plain_lines:
                joined = "\n".join(plain_lines)
                try:
                    payload_obj = json.loads(joined)
                    for event in self._yield_events_from_chunk(payload_obj, pending_tool_calls):
                        yield event
                except Exception:
                    pass

            if pending_tool_calls:
                for tool_call in DeepSeekLLMClient._finalize_tool_calls(pending_tool_calls):
                    yield {"type": "tool_call", "tool_call": tool_call}

        except urlerror.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            detail = f"HTTP {exc.code}"
            if body_text:
                detail = f"{detail}: {body_text}"
            yield {"type": "error", "error": f"Zhipu request failed ({detail})"}
        except urlerror.URLError as exc:
            yield {"type": "error", "error": f"Zhipu request failed: {exc.reason}"}

    def chat(self, messages, tools=None, temperature=0.0):
        content_parts = []
        tool_calls = []

        for event in self.stream_chat(messages, tools=tools, temperature=temperature):
            if not isinstance(event, dict):
                continue

            event_type = str(event.get("type") or "").strip().lower()
            if event_type == "answer":
                text = str(event.get("text") or "")
                if text:
                    content_parts.append(text)
            elif event_type == "tool_call":
                tool_call = event.get("tool_call")
                if isinstance(tool_call, dict):
                    tool_calls.append(tool_call)
            elif event_type == "error":
                raise RuntimeError(str(event.get("error") or "Zhipu stream failed"))

        return {
            "role": "assistant",
            "content": "".join(content_parts).strip(),
            "tool_calls": tool_calls,
        }
