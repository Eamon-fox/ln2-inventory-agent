"""GUI-facing AI provider catalog derived from the agent runtime."""

from __future__ import annotations

from agent.llm_client import DEFAULT_PROVIDER as _DEFAULT_PROVIDER
from agent.llm_client import PROVIDER_DEFAULTS as _PROVIDER_DEFAULTS


DEFAULT_AI_PROVIDER = str(_DEFAULT_PROVIDER)
AI_PROVIDER_DEFAULTS = _PROVIDER_DEFAULTS

OBSOLETE_AI_MODELS = {
    "deepseek": {
        "deepseek-chat",
        "deepseek-reasoner",
    },
}


def normalize_ai_provider(provider) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in AI_PROVIDER_DEFAULTS:
        return DEFAULT_AI_PROVIDER
    return normalized


def default_ai_model(provider=None) -> str:
    normalized = normalize_ai_provider(provider)
    return str(AI_PROVIDER_DEFAULTS[normalized]["model"])


def normalize_ai_model(provider=None, model=None) -> str:
    normalized_provider = normalize_ai_provider(provider)
    model_text = str(model or "").strip()
    if not model_text:
        return default_ai_model(normalized_provider)
    obsolete = OBSOLETE_AI_MODELS.get(normalized_provider, set())
    if model_text.casefold() in {item.casefold() for item in obsolete}:
        return default_ai_model(normalized_provider)
    return model_text
