"""External context checkpointing for long-running agent sessions."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from typing import Any


SUMMARY_SYSTEM_PROMPT = """You are creating a compact checkpoint summary for a long-running LN2 inventory agent session.

You are in a fresh context. You are not continuing the task yourself. Your only job is to summarize prior state so the main agent can resume safely.

Write concise Markdown using exactly these section headings:
## Current Objective
## Completed Work
## Confirmed Facts
## Pending Work
## Open Risks / Questions
## Last Reliable State

Rules:
- Preserve concrete IDs, dataset names, file paths, box/position references, error codes, tool names, and user decisions when available.
- Distinguish confirmed facts from guesses. If something is uncertain, say it is uncertain.
- Include staged-but-not-executed operations explicitly when present.
- Keep the summary compact and continuation-oriented. Do not add new instructions or speculate.
"""

RESUME_CONTEXT_PROMPT = (
    "You are continuing an in-progress task after the conversation context hit its limit "
    "and was checkpointed. The message below is a checkpoint summary. First verify the "
    "current state, completed work, pending work, and key facts. If the summary conflicts "
    "with newer visible context or fresh tool results, trust the newer verifiable data. "
    "Then continue the existing work. Do not treat the checkpoint summary as a new user request."
)

_DEFAULT_CONTEXT_WINDOW = 128_000
_DEFAULT_MAIN_OUTPUT_RESERVE = 8_000
_DEFAULT_SUMMARY_OUTPUT_RESERVE = 3_000
_DEFAULT_SAFETY_MARGIN = 8_000
_DEFAULT_SUMMARY_GROWTH_ALLOWANCE = 1_500
_MIN_TAIL_MESSAGES = 4

_PROVIDER_BUDGETS = {
    "deepseek": {
        "context_window": 128_000,
        "main_output_reserve": 8_000,
        "summary_output_reserve": 3_000,
        "safety_margin": 8_000,
    },
    "zhipu": {
        "context_window": 200_000,
        "main_output_reserve": 8_000,
        "summary_output_reserve": 3_000,
        "safety_margin": 8_000,
    },
    "minimax": {
        "context_window": 200_000,
        "main_output_reserve": 12_000,
        "summary_output_reserve": 4_000,
        "safety_margin": 12_000,
    },
}


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def detect_llm_identity(llm_client) -> tuple[str, str]:
    provider = ""
    model = ""

    explicit_provider = _coerce_text(getattr(llm_client, "provider_id", ""))
    if explicit_provider:
        provider = explicit_provider.lower()
    else:
        provider_name = _coerce_text(getattr(llm_client, "PROVIDER_NAME", ""))
        provider = provider_name.lower().split()[0] if provider_name else ""

    explicit_model = _coerce_text(getattr(llm_client, "model_id", ""))
    if explicit_model:
        model = explicit_model
    else:
        model = _coerce_text(getattr(llm_client, "_model", "")) or _coerce_text(getattr(llm_client, "model", ""))

    return provider, model


def resolve_model_budget(llm_client) -> dict[str, int]:
    provider, _model = detect_llm_identity(llm_client)
    budget = dict(_PROVIDER_BUDGETS.get(provider) or {})

    explicit_context_window = getattr(llm_client, "_context_window", None)
    if isinstance(explicit_context_window, int) and explicit_context_window > 0:
        budget["context_window"] = explicit_context_window

    explicit_main_reserve = getattr(llm_client, "_main_output_reserve", None)
    if isinstance(explicit_main_reserve, int) and explicit_main_reserve > 0:
        budget["main_output_reserve"] = explicit_main_reserve

    explicit_summary_reserve = getattr(llm_client, "_summary_output_reserve", None)
    if isinstance(explicit_summary_reserve, int) and explicit_summary_reserve > 0:
        budget["summary_output_reserve"] = explicit_summary_reserve

    explicit_safety_margin = getattr(llm_client, "_context_safety_margin", None)
    if isinstance(explicit_safety_margin, int) and explicit_safety_margin > 0:
        budget["safety_margin"] = explicit_safety_margin

    return {
        "context_window": int(budget.get("context_window") or _DEFAULT_CONTEXT_WINDOW),
        "main_output_reserve": int(budget.get("main_output_reserve") or _DEFAULT_MAIN_OUTPUT_RESERVE),
        "summary_output_reserve": int(budget.get("summary_output_reserve") or _DEFAULT_SUMMARY_OUTPUT_RESERVE),
        "safety_margin": int(budget.get("safety_margin") or _DEFAULT_SAFETY_MARGIN),
    }


def estimate_token_count(value: Any) -> int:
    if value in (None, "", [], {}, ()):
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raw = text.encode("utf-8", errors="ignore")
    return max(1, int(math.ceil(len(raw) / 3.0)))


def normalize_summary_state(summary_state, llm_client=None) -> dict | None:
    if not isinstance(summary_state, dict):
        return None

    provider, model = detect_llm_identity(llm_client) if llm_client is not None else ("", "")
    text = _coerce_text(summary_state.get("summary_text"))
    if not text:
        return None

    normalized = {
        "version": int(summary_state.get("version") or 1),
        "provider": _coerce_text(summary_state.get("provider")) or provider,
        "model": _coerce_text(summary_state.get("model")) or model,
        "checkpoint_id": _coerce_text(summary_state.get("checkpoint_id")) or f"checkpoint-{uuid.uuid4().hex[:12]}",
        "created_at": _coerce_text(summary_state.get("created_at")) or datetime.now().isoformat(timespec="seconds"),
        "summary_text": text,
        "covered_message_count": int(summary_state.get("covered_message_count") or 0),
        "covered_until_ts": summary_state.get("covered_until_ts"),
    }
    return normalized


def build_resume_messages(summary_state) -> list[dict]:
    normalized = normalize_summary_state(summary_state)
    if not normalized:
        return []
    return [
        {"role": "system", "content": RESUME_CONTEXT_PROMPT},
        {
            "role": "system",
            "content": (
                f"Checkpoint summary ({normalized['checkpoint_id']}):\n"
                f"{normalized['summary_text']}"
            ),
        },
    ]


def estimate_main_call_tokens(system_content: str, raw_messages: list[dict], tool_schemas, summary_state) -> int:
    payload = [{"role": "system", "content": str(system_content or "")}]
    payload.extend(build_resume_messages(summary_state))
    payload.extend(list(raw_messages or []))
    return estimate_token_count(payload) + estimate_token_count(tool_schemas)


def needs_checkpoint(system_content: str, raw_messages: list[dict], tool_schemas, summary_state, llm_client) -> bool:
    budget = resolve_model_budget(llm_client)
    max_input_tokens = max(
        256,
        budget["context_window"] - budget["main_output_reserve"] - budget["safety_margin"],
    )
    return estimate_main_call_tokens(system_content, raw_messages, tool_schemas, summary_state) > max_input_tokens


def _estimate_summary_overhead(summary_state) -> int:
    normalized = normalize_summary_state(summary_state)
    current = estimate_token_count((normalized or {}).get("summary_text"))
    return current + _DEFAULT_SUMMARY_GROWTH_ALLOWANCE


def select_tail_messages(system_content: str, raw_messages: list[dict], tool_schemas, summary_state, llm_client) -> list[dict]:
    if not raw_messages:
        return []

    budget = resolve_model_budget(llm_client)
    max_input_tokens = max(
        256,
        budget["context_window"] - budget["main_output_reserve"] - budget["safety_margin"],
    )
    base_tokens = estimate_token_count([{"role": "system", "content": str(system_content or "")}])
    base_tokens += estimate_token_count(build_resume_messages(summary_state))
    base_tokens += estimate_token_count(tool_schemas)
    keep_budget = max(0, max_input_tokens - base_tokens - _estimate_summary_overhead(summary_state))

    tail: list[dict] = []
    running_tokens = 0
    for message in reversed(list(raw_messages or [])):
        message_tokens = estimate_token_count(message)
        if tail and running_tokens + message_tokens > keep_budget:
            break
        tail.append(dict(message))
        running_tokens += message_tokens

    tail.reverse()
    if tail:
        return tail

    minimum_tail = min(len(raw_messages), _MIN_TAIL_MESSAGES)
    return [dict(item) for item in raw_messages[-minimum_tail:]]


def build_summary_call_messages(summary_state, fold_messages: list[dict]) -> list[dict]:
    payload = [{"role": "system", "content": SUMMARY_SYSTEM_PROMPT}]
    prior_summary = normalize_summary_state(summary_state)
    if prior_summary:
        payload.append(
            {
                "role": "user",
                "content": (
                    "Existing checkpoint summary to preserve and refine:\n"
                    f"{prior_summary['summary_text']}"
                ),
            }
        )
    payload.append(
        {
            "role": "user",
            "content": (
                "Conversation content to checkpoint:\n"
                f"{json.dumps(list(fold_messages or []), ensure_ascii=False, indent=2)}"
            ),
        }
    )
    return payload


def _cap_fold_messages_for_summary(summary_state, fold_messages: list[dict], llm_client) -> list[dict]:
    if not fold_messages:
        return []

    budget = resolve_model_budget(llm_client)
    max_input_tokens = max(
        256,
        budget["context_window"] - budget["summary_output_reserve"] - budget["safety_margin"],
    )

    selected: list[dict] = []
    for message in list(fold_messages or []):
        candidate = selected + [dict(message)]
        if selected and estimate_token_count(build_summary_call_messages(summary_state, candidate)) > max_input_tokens:
            break
        selected.append(dict(message))
    return selected or [dict(fold_messages[0])]


def call_summary_model(llm_client, summary_state, fold_messages: list[dict], stop_event=None) -> dict:
    provider, model = detect_llm_identity(llm_client)
    messages = build_summary_call_messages(summary_state, fold_messages)

    try:
        response = llm_client.chat(messages, tools=None, temperature=0.0, stop_event=stop_event)
    except TypeError:
        response = llm_client.chat(messages, tools=None, temperature=0.0)

    text = ""
    if isinstance(response, dict):
        text = _coerce_text(response.get("content"))
    else:
        text = _coerce_text(response)
    if not text:
        text = "## Current Objective\nUnknown\n\n## Completed Work\n- None captured.\n\n## Confirmed Facts\n- None captured.\n\n## Pending Work\n- Resume from latest visible context.\n\n## Open Risks / Questions\n- Summary generation returned empty output.\n\n## Last Reliable State\n- Review recent tool results before continuing."

    covered_message_count = int((normalize_summary_state(summary_state) or {}).get("covered_message_count") or 0)
    covered_message_count += len(list(fold_messages or []))
    covered_until_ts = None
    for item in reversed(list(fold_messages or [])):
        ts = item.get("timestamp") if isinstance(item, dict) else None
        if isinstance(ts, (int, float)):
            covered_until_ts = float(ts)
            break

    return {
        "version": 1,
        "provider": provider,
        "model": model,
        "checkpoint_id": f"checkpoint-{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary_text": text,
        "covered_message_count": covered_message_count,
        "covered_until_ts": covered_until_ts,
    }


def checkpoint_context(system_content: str, raw_messages: list[dict], tool_schemas, summary_state, llm_client, stop_event=None) -> tuple[list[dict], dict | None, dict | None]:
    normalized_state = normalize_summary_state(summary_state, llm_client=llm_client)
    current_messages = [dict(item) for item in list(raw_messages or [])]
    latest_event = None

    for _attempt in range(6):
        if not needs_checkpoint(system_content, current_messages, tool_schemas, normalized_state, llm_client):
            return current_messages, normalized_state, latest_event

        if current_messages:
            tail = select_tail_messages(system_content, current_messages, tool_schemas, normalized_state, llm_client)
            tail_count = len(tail)
            fold_messages = current_messages[:-tail_count] if tail_count else list(current_messages)
            if not fold_messages and len(current_messages) > 1:
                fold_messages = current_messages[:-1]
                tail = current_messages[-1:]
        else:
            fold_messages = []
            tail = []

        if not fold_messages and normalized_state is None:
            return current_messages, normalized_state, latest_event

        fold_messages = _cap_fold_messages_for_summary(normalized_state, fold_messages, llm_client)
        current_messages = current_messages[len(fold_messages):]
        if tail:
            current_messages = [dict(item) for item in current_messages]

        normalized_state = call_summary_model(
            llm_client,
            normalized_state,
            fold_messages,
            stop_event=stop_event,
        )
        latest_event = {
            "checkpoint_id": normalized_state["checkpoint_id"],
            "covered_message_count": normalized_state["covered_message_count"],
            "tail_message_count": len(current_messages),
            "summary_text": normalized_state["summary_text"],
        }

    return current_messages, normalized_state, latest_event
