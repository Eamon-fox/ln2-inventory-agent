"""LLM client abstractions for ReAct agent runtime."""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path


_DEFAULT_OPENCODE_AUTH_FILE = Path.home() / ".local" / "share" / "opencode" / "auth.json"


def load_opencode_auth_env(auth_file=None, force=False):
    """Load provider API keys from opencode auth file into env vars.

    This keeps secrets out of the repository and allows GUI/CLI runtime to
    reuse already-authenticated local provider credentials.
    """
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
        # Kimi / Moonshot aliases
        "moonshotai-cn": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "moonshot": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "kimi": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        # GLM / Zhipu aliases
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
    def complete(self, messages, temperature=0.0):
        """Return assistant text response for given chat messages."""


class LiteLLMClient(LLMClient):
    """LiteLLM-backed client.

    Notes:
    - Requires `litellm` package installed.
    - API key/env handling is delegated to provider SDK/env conventions.
    """

    def __init__(self, model, **kwargs):
        self._model = model
        self._kwargs = kwargs
        # Best-effort key loading from local opencode auth store.
        self._auth_load = load_opencode_auth_env()

    def complete(self, messages, temperature=0.0):
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError(
                "litellm is not installed. Install with: pip install litellm"
            ) from exc

        response = completion(
            model=self._model,
            messages=messages,
            temperature=temperature,
            **self._kwargs,
        )
        return response["choices"][0]["message"]["content"]


class MockLLMClient(LLMClient):
    """Fallback mock client for dry runs and local wiring tests."""

    def complete(self, messages, temperature=0.0):
        _ = temperature
        # Minimal deterministic response to unblock local tests.
        return (
            '{"thought":"mock mode","action":"finish","action_input":{},'
            '"final":"Mock client enabled. No real LLM call was made."}'
        )
