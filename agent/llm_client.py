"""LLM client abstractions for ReAct agent runtime."""

from abc import ABC, abstractmethod


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
