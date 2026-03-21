"""GUI-facing AI provider catalog derived from the agent runtime."""

from __future__ import annotations

from agent.llm_client import DEFAULT_PROVIDER as _DEFAULT_PROVIDER
from agent.llm_client import PROVIDER_DEFAULTS as _PROVIDER_DEFAULTS


DEFAULT_AI_PROVIDER = str(_DEFAULT_PROVIDER)
AI_PROVIDER_DEFAULTS = _PROVIDER_DEFAULTS


def normalize_ai_provider(provider) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in AI_PROVIDER_DEFAULTS:
        return DEFAULT_AI_PROVIDER
    return normalized


def default_ai_model(provider=None) -> str:
    normalized = normalize_ai_provider(provider)
    return str(AI_PROVIDER_DEFAULTS[normalized]["model"])
