"""LLM client abstractions for ReAct agent runtime."""

import json
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest


_DEFAULT_OPENCODE_AUTH_FILE = Path.home() / ".local" / "share" / "opencode" / "auth.json"


def load_opencode_auth_env(auth_file=None, force=False):
    """Load provider API keys from opencode auth file into env vars."""
    path = Path(auth_file or os.environ.get("OPENCODE_AUTH_FILE") or _DEFAULT_OPENCODE_AUTH_FILE)
    if not path.exists() or not path.is_file():
        return {
            "ok": False,
            "path": str(path),
            "reason": "missing_auth_file",
            "loaded_env": [],
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ok": False,
            "path": str(path),
            "reason": "invalid_json",
            "loaded_env": [],
        }

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "path": str(path),
            "reason": "invalid_payload",
            "loaded_env": [],
        }

    loaded_env = []
    provider_env_map = {
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "moonshotai-cn": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "moonshot": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "kimi": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "zhipuai-coding-plan": ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"],
        "zhipuai": ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"],
        "zhipu": ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"],
        "glm": ["ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"],
    }

    for provider, env_keys in provider_env_map.items():
        info = payload.get(provider)
        if not isinstance(info, dict):
            continue
        key = info.get("key")
        if not key:
            continue

        for env_name in env_keys:
            if force or not os.environ.get(env_name):
                os.environ[env_name] = str(key)
                loaded_env.append(env_name)

    return {
        "ok": True,
        "path": str(path),
        "loaded_env": loaded_env,
    }


class LLMClient(ABC):
    """Simple chat completion client interface."""

    @abstractmethod
    def chat(self, messages, tools=None, temperature=0.0):
        """Return assistant response payload with optional tool calls."""
        raise NotImplementedError

    def complete(self, messages, temperature=0.0):
        """Compatibility wrapper returning assistant text only."""
        response = self.chat(messages, tools=None, temperature=temperature)
        if isinstance(response, dict):
            return str(response.get("content") or "")
        return str(response or "")


class DeepSeekLLMClient(LLMClient):
    """DeepSeek-native client with provider-side streaming parser."""

    def __init__(self, model=None, api_key=None, base_url=None, timeout=180):
        self._model = (model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        self._base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self._timeout = int(timeout)
        self._auth_load = load_opencode_auth_env()
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

    def chat(self, messages, tools=None, temperature=0.0):
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = f"{self._base_url}/chat/completions"
        req = urlrequest.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        answer_chunks = []
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
                        raise RuntimeError(f"DeepSeek API error: {message}")

                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if not isinstance(choices, list) or not choices:
                        continue

                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta = choice.get("delta") if isinstance(choice, dict) else {}
                    message = choice.get("message") if isinstance(choice, dict) else {}
                    delta = delta if isinstance(delta, dict) else {}
                    message = message if isinstance(message, dict) else {}

                    content = self._normalize_content(delta.get("content"))
                    if not content:
                        content = self._extract_content_from_choice(choice, message)
                    if content:
                        answer_chunks.append(content)

                    raw_tool_calls = delta.get("tool_calls") or message.get("tool_calls") or []
                    if isinstance(raw_tool_calls, list):
                        for tool_call in raw_tool_calls:
                            self._accumulate_tool_call(pending_tool_calls, tool_call)

            if not saw_sse and plain_lines:
                joined = "\n".join(plain_lines)
                try:
                    payload_obj = json.loads(joined)
                    choices = payload_obj.get("choices") if isinstance(payload_obj, dict) else None
                    if isinstance(choices, list) and choices:
                        choice = choices[0] if isinstance(choices[0], dict) else {}
                        message = choice.get("message") if isinstance(choice, dict) else {}
                        message = message if isinstance(message, dict) else {}

                        content = self._extract_content_from_choice(choice, message)
                        if content:
                            answer_chunks.append(content)

                        raw_tool_calls = message.get("tool_calls") or choice.get("tool_calls") or []
                        if isinstance(raw_tool_calls, list):
                            for tool_call in raw_tool_calls:
                                self._accumulate_tool_call(pending_tool_calls, tool_call)
                except Exception:
                    pass

        except urlerror.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            detail = f"HTTP {exc.code}"
            if body_text:
                detail = f"{detail}: {body_text}"
            raise RuntimeError(f"DeepSeek request failed ({detail})") from exc
        except urlerror.URLError as exc:
            raise RuntimeError(f"DeepSeek request failed: {exc.reason}") from exc

        content = "".join(answer_chunks).strip()
        tool_calls = self._finalize_tool_calls(pending_tool_calls)
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }


class MockLLMClient(LLMClient):
    """Fallback mock client for dry runs and local wiring tests."""

    def chat(self, messages, tools=None, temperature=0.0):
        _ = messages
        _ = tools
        _ = temperature
        return {
            "role": "assistant",
            "content": "Mock client enabled. No real LLM call was made.",
            "tool_calls": [],
        }
