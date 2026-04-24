"""LLM client abstractions for ReAct agent runtime."""

import json
import os
import threading
import uuid
from abc import ABC, abstractmethod
from urllib import error as urlerror
from urllib import request as urlrequest


PROVIDER_DEFAULTS = {
    "deepseek": {
        "model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "env_key": "DEEPSEEK_API_KEY",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "help_url": "https://platform.deepseek.com",
    },
    "zhipu": {
        "model": "glm-5",
        "models": ["glm-5", "glm-4.7"],
        "env_key": "ZHIPUAI_API_KEY",
        "display_name": "Zhipu AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "help_url": "https://open.bigmodel.cn",
    },
    "minimax": {
        "model": "MiniMax-M2.7",
        "models": [
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.5",
        ],
        "env_key": "MINIMAX_API_KEY",
        "display_name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "help_url": "https://platform.minimaxi.com",
    },
}

DEFAULT_PROVIDER = "deepseek"


def _is_stop_requested(stop_event):
    try:
        return bool(stop_event is not None and stop_event.is_set())
    except Exception:
        return False


class LLMClient(ABC):
    """Simple chat completion client interface."""

    @abstractmethod
    def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        """Return assistant response payload with optional tool calls."""
        raise NotImplementedError

    def stream_chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        """Yield normalized stream events (answer/tool_call/error)."""
        if _is_stop_requested(stop_event):
            return
        response = self.chat(messages, tools=tools, temperature=temperature, stop_event=stop_event)
        if not isinstance(response, dict):
            yield {"type": "error", "error": "Invalid model response payload"}
            return

        reasoning = str(response.get("reasoning_content") or "")
        if reasoning:
            yield {"type": "thought", "text": reasoning}

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


class OpenAICompatibleClient(LLMClient, ABC):
    """Shared base for OpenAI-compatible streaming chat clients."""

    PROVIDER_NAME = "OpenAI-compatible"
    MODEL_ENV_VAR = ""
    DEFAULT_MODEL = ""
    BASE_URL_ENV_VAR = ""
    DEFAULT_BASE_URL = ""
    API_KEY_ENV_VARS = ()
    API_KEY_ERROR = "API key is required"
    DEFAULT_THINKING_ENABLED = False
    REQUEST_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "Cline-VSCode-Extension",
    }
    STREAM_PREFIX = "data:"
    STREAM_DONE_TOKEN = "[DONE]"

    def __init__(self, model=None, api_key=None, base_url=None, timeout=180, thinking_enabled=None):
        self._model = (model or os.environ.get(self.MODEL_ENV_VAR) or self.DEFAULT_MODEL).strip()
        self._base_url = (base_url or os.environ.get(self.BASE_URL_ENV_VAR) or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = int(timeout)
        if thinking_enabled is None:
            self._thinking_enabled = bool(self.DEFAULT_THINKING_ENABLED)
        else:
            self._thinking_enabled = bool(thinking_enabled)
        self._api_key = self._resolve_api_key(api_key)
        self._stop_lock = threading.Lock()
        self._active_response = None
        self._local_stop = threading.Event()

        if not self._api_key:
            raise RuntimeError(self.API_KEY_ERROR)

    def _resolve_api_key(self, api_key):
        if api_key:
            return api_key

        for env_var in self.API_KEY_ENV_VARS:
            value = os.environ.get(env_var)
            if value:
                return value
        return None

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
    def _extract_choice_text(cls, choice, message):
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

        return ""

    @classmethod
    def _extract_content_from_choice(cls, choice, message):
        return cls._extract_choice_text(choice, message)

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

    @classmethod
    def _get_choice_parts(cls, chunk):
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not isinstance(choices, list) or not choices:
            return None, {}, {}

        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice, dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        if not isinstance(delta, dict):
            delta = {}
        if not isinstance(message, dict):
            message = {}
        return choice, delta, message

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

    @classmethod
    def _accumulate_tool_calls_from_sources(cls, pending_tool_calls, *sources):
        raw_tool_calls = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            current = source.get("tool_calls")
            if isinstance(current, list) and current:
                raw_tool_calls = current
                break
        for tool_call in raw_tool_calls:
            cls._accumulate_tool_call(pending_tool_calls, tool_call)

    @classmethod
    def _yield_finalized_tool_call_events(cls, pending_tool_calls):
        for tool_call in cls._finalize_tool_calls(pending_tool_calls):
            yield {"type": "tool_call", "tool_call": tool_call}
        pending_tool_calls.clear()

    def _is_stopping(self, stop_event=None):
        return self._local_stop.is_set() or _is_stop_requested(stop_event)

    def request_stop(self):
        self._local_stop.set()
        resp = None
        with self._stop_lock:
            resp = self._active_response
        if resp is not None and hasattr(resp, "close"):
            threading.Thread(
                target=self._close_response_quietly,
                args=(resp,),
                daemon=True,
            ).start()

    @staticmethod
    def _close_response_quietly(resp):
        try:
            resp.close()
        except Exception:
            pass

    def _build_request(self, messages, tools=None, temperature=0.0):
        payload = self._build_request_payload(messages, tools=tools, temperature=temperature)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.REQUEST_HEADERS)
        return urlrequest.Request(
            endpoint,
            data=body,
            method="POST",
            headers=headers,
        )

    @staticmethod
    def _truncate_text(text, limit=600):
        clean = str(text or "")
        if len(clean) <= int(limit):
            return clean
        return clean[: int(limit)] + "..."

    @staticmethod
    def _summarize_exception(exc):
        return {
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }

    def _build_error_event(self, error, *, error_code, details=None):
        payload = {
            "type": "error",
            "error": str(error or f"{self.PROVIDER_NAME} stream failed"),
            "error_code": str(error_code or "llm_stream_failed"),
        }
        if isinstance(details, dict) and details:
            payload["details"] = details
        return payload

    def _build_api_error_event(self, error_payload, *, endpoint):
        if isinstance(error_payload, dict):
            message = error_payload.get("message") or json.dumps(error_payload, ensure_ascii=False)
        else:
            message = str(error_payload)
        return self._build_error_event(
            f"{self.PROVIDER_NAME} API error: {message}",
            error_code="llm_api_error",
            details={
                "provider": self.PROVIDER_NAME,
                "endpoint": endpoint,
                "api_error": error_payload,
            },
        )

    def _build_http_error_event(self, exc, *, endpoint):
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        detail = f"HTTP {exc.code}"
        if body_text:
            detail = f"{detail}: {self._truncate_text(body_text)}"
        return self._build_error_event(
            f"{self.PROVIDER_NAME} request failed ({detail})",
            error_code="llm_http_error",
            details={
                "provider": self.PROVIDER_NAME,
                "endpoint": endpoint,
                "http_status": int(exc.code),
                "response_body": self._truncate_text(body_text),
                **self._summarize_exception(exc),
            },
        )

    def _build_url_error_event(self, exc, *, endpoint):
        reason = getattr(exc, "reason", exc)
        return self._build_error_event(
            f"{self.PROVIDER_NAME} request failed: {reason}",
            error_code="llm_transport_error",
            details={
                "provider": self.PROVIDER_NAME,
                "endpoint": endpoint,
                "reason": str(reason),
                **self._summarize_exception(exc),
            },
        )

    def _build_unexpected_error_event(self, exc, *, endpoint):
        return self._build_error_event(
            f"{self.PROVIDER_NAME} stream failed: {exc}",
            error_code="llm_stream_failed",
            details={
                "provider": self.PROVIDER_NAME,
                "endpoint": endpoint,
                **self._summarize_exception(exc),
            },
        )

    @abstractmethod
    def _build_request_payload(self, messages, tools=None, temperature=0.0):
        raise NotImplementedError

    @abstractmethod
    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        raise NotImplementedError

    def _format_api_error(self, error_payload):
        if isinstance(error_payload, dict):
            message = error_payload.get("message") or json.dumps(error_payload, ensure_ascii=False)
        else:
            message = str(error_payload)
        return f"{self.PROVIDER_NAME} API error: {message}"

    def _format_http_error(self, exc):
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        detail = f"HTTP {exc.code}"
        if body_text:
            detail = f"{detail}: {body_text}"
        return f"{self.PROVIDER_NAME} request failed ({detail})"

    def _format_url_error(self, exc):
        return f"{self.PROVIDER_NAME} request failed: {exc.reason}"

    def stream_chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        self._local_stop.clear()
        req = self._build_request(messages, tools=tools, temperature=temperature)
        endpoint = getattr(req, "full_url", "") or f"{self._base_url}/chat/completions"

        pending_tool_calls = {}
        saw_sse = False
        plain_lines = []

        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                with self._stop_lock:
                    self._active_response = resp
                try:
                    for raw_line in resp:
                        if self._is_stopping(stop_event):
                            return

                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        if not line.startswith(self.STREAM_PREFIX):
                            plain_lines.append(line)
                            continue

                        saw_sse = True
                        data = line[len(self.STREAM_PREFIX) :].strip()
                        if data == self.STREAM_DONE_TOKEN:
                            break

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if isinstance(chunk, dict) and chunk.get("error"):
                            yield self._build_api_error_event(chunk.get("error"), endpoint=endpoint)
                            return

                        for event in self._yield_events_from_chunk(chunk, pending_tool_calls):
                            if self._is_stopping(stop_event):
                                return
                            yield event
                finally:
                    with self._stop_lock:
                        self._active_response = None

            if not saw_sse and plain_lines:
                if self._is_stopping(stop_event):
                    return
                joined = "\n".join(plain_lines)
                try:
                    payload_obj = json.loads(joined)
                    for event in self._yield_events_from_chunk(payload_obj, pending_tool_calls):
                        if self._is_stopping(stop_event):
                            return
                        yield event
                except Exception:
                    pass

            if pending_tool_calls:
                for event in self._yield_finalized_tool_call_events(pending_tool_calls):
                    if self._is_stopping(stop_event):
                        return
                    yield event

        except urlerror.HTTPError as exc:
            yield self._build_http_error_event(exc, endpoint=endpoint)
        except urlerror.URLError as exc:
            yield self._build_url_error_event(exc, endpoint=endpoint)
        except Exception as exc:
            yield self._build_unexpected_error_event(exc, endpoint=endpoint)

    def chat(self, messages, tools=None, temperature=0.0, stop_event=None):
        content_parts = []
        thought_parts = []
        tool_calls = []

        for event in self.stream_chat(messages, tools=tools, temperature=temperature, stop_event=stop_event):
            if self._is_stopping(stop_event):
                break
            if not isinstance(event, dict):
                continue

            event_type = str(event.get("type") or "").strip().lower()
            if event_type == "answer":
                text = str(event.get("text") or "")
                if text:
                    content_parts.append(text)
            elif event_type == "thought":
                text = str(event.get("text") or "")
                if text:
                    thought_parts.append(text)
            elif event_type == "tool_call":
                tool_call = event.get("tool_call")
                if isinstance(tool_call, dict):
                    tool_calls.append(tool_call)
            elif event_type == "error":
                raise RuntimeError(str(event.get("error") or f"{self.PROVIDER_NAME} stream failed"))

        response = {
            "role": "assistant",
            "content": "".join(content_parts).strip(),
            "tool_calls": tool_calls,
        }
        reasoning_content = "".join(thought_parts).strip()
        if reasoning_content:
            response["reasoning_content"] = reasoning_content
        return response


class DeepSeekLLMClient(OpenAICompatibleClient):
    """DeepSeek-native client with provider-side streaming parser."""

    PROVIDER_NAME = "DeepSeek"
    MODEL_ENV_VAR = "DEEPSEEK_MODEL"
    DEFAULT_MODEL = "deepseek-v4-flash"
    BASE_URL_ENV_VAR = "DEEPSEEK_BASE_URL"
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    API_KEY_ENV_VARS = ("DEEPSEEK_API_KEY",)
    API_KEY_ERROR = "DEEPSEEK_API_KEY is required"
    DEFAULT_THINKING_ENABLED = True
    REQUEST_HEADERS = {
        "Accept": "text/event-stream",
        "User-Agent": "SnowFox/1.2.3",
    }

    def _build_request_payload(self, messages, tools=None, temperature=0.0):
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if self._thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max"
        else:
            payload["thinking"] = {"type": "disabled"}
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        choice, delta, message = self._get_choice_parts(chunk)
        if choice is None:
            return

        reasoning = self._normalize_content(delta.get("reasoning_content"))
        if not reasoning:
            reasoning = self._extract_reasoning_from_choice(choice, message)
        if reasoning:
            yield {"type": "thought", "text": reasoning}

        content = self._normalize_content(delta.get("content"))
        if not content:
            content = self._extract_choice_text(choice, message)
        if content:
            yield {"type": "answer", "text": content}

        self._accumulate_tool_calls_from_sources(pending_tool_calls, delta, message, choice)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "tool_calls" and pending_tool_calls:
            yield from self._yield_finalized_tool_call_events(pending_tool_calls)


class ZhipuLLMClient(OpenAICompatibleClient):
    """Zhipu AI (GLM) client using the OpenAI-compatible API."""

    PROVIDER_NAME = "Zhipu"
    MODEL_ENV_VAR = "ZHIPU_MODEL"
    DEFAULT_MODEL = "glm-5"
    BASE_URL_ENV_VAR = "ZHIPU_BASE_URL"
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    API_KEY_ENV_VARS = ("ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY")
    API_KEY_ERROR = "ZHIPUAI_API_KEY is required. Set ZHIPU_API_KEY or ZHIPUAI_API_KEY env var."
    DEFAULT_THINKING_ENABLED = False
    REQUEST_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "SnowFox/1.2.3",
    }

    def _build_request_payload(self, messages, tools=None, temperature=0.0):
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
        return payload

    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        choice, delta, message = self._get_choice_parts(chunk)
        if choice is None:
            return

        reasoning = self._normalize_content(delta.get("reasoning_content"))
        if not reasoning:
            reasoning = self._extract_reasoning_from_choice(choice, message)
        if reasoning:
            yield {"type": "thought", "text": reasoning}

        content = self._normalize_content(delta.get("content"))
        if not content:
            content = self._extract_choice_text(choice, message)
        if content:
            yield {"type": "answer", "text": content}

        self._accumulate_tool_calls_from_sources(pending_tool_calls, delta, message, choice)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "tool_calls" and pending_tool_calls:
            yield from self._yield_finalized_tool_call_events(pending_tool_calls)


class MiniMaxLLMClient(OpenAICompatibleClient):
    """MiniMax client using the OpenAI-compatible API."""

    PROVIDER_NAME = "MiniMax"
    MODEL_ENV_VAR = "MINIMAX_MODEL"
    DEFAULT_MODEL = "MiniMax-M2.7"
    BASE_URL_ENV_VAR = "MINIMAX_BASE_URL"
    DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
    API_KEY_ENV_VARS = ("MINIMAX_API_KEY",)
    API_KEY_ERROR = "MINIMAX_API_KEY is required"
    DEFAULT_THINKING_ENABLED = True
    REQUEST_HEADERS = {
        "Accept": "application/json",
        "User-Agent": "SnowFox/1.2.3",
    }

    def _build_request_payload(self, messages, tools=None, temperature=0.0):
        use_temp = temperature if temperature > 0 else 1.0
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": use_temp,
        }
        if self._thinking_enabled:
            payload["reasoning_split"] = True
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _yield_events_from_chunk(self, chunk, pending_tool_calls):
        choice, delta, message = self._get_choice_parts(chunk)
        if choice is None:
            return

        reasoning_details = delta.get("reasoning_details") or message.get("reasoning_details") or choice.get("reasoning_details") or []
        saw_reasoning = False
        if isinstance(reasoning_details, list):
            for reasoning_detail in reasoning_details:
                if not isinstance(reasoning_detail, dict):
                    continue
                reasoning_text = self._normalize_content(reasoning_detail.get("text"))
                if reasoning_text:
                    saw_reasoning = True
                    yield {"type": "thought", "text": reasoning_text}

        if not saw_reasoning:
            reasoning = self._extract_reasoning_from_choice(choice, message)
            if reasoning:
                yield {"type": "thought", "text": reasoning}

        content = self._normalize_content(delta.get("content"))
        if not content:
            content = self._extract_choice_text(choice, message)
        if content:
            yield {"type": "answer", "text": content}

        self._accumulate_tool_calls_from_sources(pending_tool_calls, delta, message, choice)

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if finish_reason == "stop" and pending_tool_calls:
            yield from self._yield_finalized_tool_call_events(pending_tool_calls)
