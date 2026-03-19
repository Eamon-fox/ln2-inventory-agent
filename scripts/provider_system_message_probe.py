#!/usr/bin/env python3
"""Probe whether providers honor non-leading system messages.

This script sends a small suite of real requests to a configured provider and
checks whether later-inserted `system` messages are actually reflected in the
assistant response.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.llm_client import DeepSeekLLMClient, MiniMaxLLMClient, ZhipuLLMClient  # noqa: E402

try:
    import yaml  # noqa: E402
except Exception as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(f"PyYAML is required: {exc}") from exc


CLIENT_FACTORIES = {
    "deepseek": lambda api_key, model: DeepSeekLLMClient(
        api_key=api_key,
        model=model or "deepseek-chat",
        thinking_enabled=False,
    ),
    "zhipu": lambda api_key, model: ZhipuLLMClient(
        api_key=api_key,
        model=model or "glm-5",
        thinking_enabled=False,
    ),
    "minimax": lambda api_key, model: MiniMaxLLMClient(
        api_key=api_key,
        model=model or "MiniMax-M2.7",
        thinking_enabled=False,
    ),
}


@dataclass(frozen=True)
class ProbeCase:
    name: str
    description: str
    expected: str
    messages: list[dict]
    matcher: Callable[[str, str], bool]


def _load_config() -> dict:
    path = ROOT / "config" / "config.yaml"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _resolve_api_key(provider: str, config: dict) -> str:
    env_keys = {
        "deepseek": ("DEEPSEEK_API_KEY",),
        "zhipu": ("ZHIPUAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY"),
        "minimax": ("MINIMAX_API_KEY",),
    }
    for key in env_keys.get(provider, ()):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value

    api_keys = config.get("api_keys")
    if isinstance(api_keys, dict):
        value = str(api_keys.get(provider) or "").strip()
        if value:
            return value
    return ""


def _resolve_model(provider: str, config: dict, override: str) -> str:
    if override:
        return override
    ai_cfg = config.get("ai")
    if isinstance(ai_cfg, dict):
        configured_provider = str(ai_cfg.get("provider") or "").strip().lower()
        if configured_provider == provider:
            value = str(ai_cfg.get("model") or "").strip()
            if value:
                return value

    defaults = {
        "deepseek": "deepseek-chat",
        "zhipu": "glm-5",
        "minimax": "MiniMax-M2.7",
    }
    return defaults[provider]


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10].upper()}"


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _exact_match(actual: str, expected: str) -> bool:
    normalized = _normalize(actual)
    return normalized == expected


def _contains_token(actual: str, expected: str) -> bool:
    return expected in str(actual or "")


def build_cases() -> list[ProbeCase]:
    head_token = _token("HEAD")
    late_token = _token("LATE")
    fact_token = _token("FACT")
    tail_token = _token("TAIL")
    final_token = _token("FINAL")

    return [
        ProbeCase(
            name="control_head_system_only",
            description="Baseline control: only the leading system message defines the token.",
            expected=head_token,
            matcher=_exact_match,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are under test. When the user asks for the verification token, "
                        f"reply with EXACTLY {head_token}. No extra words."
                    ),
                },
                {"role": "user", "content": "What is the verification token?"},
            ],
        ),
        ProbeCase(
            name="late_system_overrides_head",
            description="Later system message appears mid-history and should override the head system.",
            expected=late_token,
            matcher=_exact_match,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are under test. When the user asks for the verification token, "
                        f"reply with EXACTLY {head_token}. No extra words."
                    ),
                },
                {"role": "user", "content": "This is an earlier turn. Do not answer with any token yet."},
                {"role": "assistant", "content": "Understood. Waiting for the real token question."},
                {
                    "role": "system",
                    "content": (
                        "Temporary instruction update for the next reply only. "
                        f"When asked for the verification token, reply with EXACTLY {late_token}. "
                        "This overrides any previous token instruction."
                    ),
                },
                {"role": "user", "content": "What is the verification token?"},
            ],
        ),
        ProbeCase(
            name="late_system_injects_hidden_fact",
            description="Later system message injects a fact absent from earlier history.",
            expected=fact_token,
            matcher=_contains_token,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are under test. If asked for the migration codename, answer OLD_CODE. "
                        "Keep responses short."
                    ),
                },
                {"role": "user", "content": "We will update the migration plan shortly."},
                {"role": "assistant", "content": "Okay. Waiting for the update."},
                {
                    "role": "system",
                    "content": (
                        "Temporary tool context for the next step: "
                        f"the migration codename is {fact_token}. "
                        "If asked for the migration codename, answer with that codename."
                    ),
                },
                {"role": "user", "content": "What is the migration codename?"},
            ],
        ),
        ProbeCase(
            name="late_system_is_final_message",
            description="The last input message is a later system message, mirroring transient context injection.",
            expected=tail_token,
            matcher=_exact_match,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are under test. If you need a token and there is no later instruction, "
                        f"reply with EXACTLY {head_token}. No extra words."
                    ),
                },
                {"role": "user", "content": "We just completed a tool call."},
                {"role": "assistant", "content": "Tool call completed. Waiting for the next step."},
                {
                    "role": "system",
                    "content": (
                        "Temporary tool context for the next assistant step only. "
                        f"Reply with EXACTLY {tail_token}. No extra words."
                    ),
                },
            ],
        ),
        ProbeCase(
            name="last_system_wins_among_multiple_updates",
            description="When multiple later system messages appear, the last one should win.",
            expected=final_token,
            matcher=_exact_match,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are under test. When asked for the verification token, "
                        f"reply with EXACTLY {head_token}. No extra words."
                    ),
                },
                {"role": "user", "content": "Earlier conversation placeholder."},
                {"role": "assistant", "content": "Placeholder acknowledged."},
                {
                    "role": "system",
                    "content": (
                        "Temporary update: if asked for the verification token, "
                        "reply with EXACTLY INTERMEDIATE_VALUE."
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "More recent temporary update: if asked for the verification token, "
                        f"reply with EXACTLY {final_token}. This is the newest instruction."
                    ),
                },
                {"role": "user", "content": "What is the verification token?"},
            ],
        ),
    ]


def _build_client(provider: str, api_key: str, model: str):
    factory = CLIENT_FACTORIES.get(provider)
    if factory is None:
        raise SystemExit(f"Unsupported provider: {provider}")
    return factory(api_key, model)


def _write_report(report: dict, output_path: Path | None) -> Path:
    target = output_path
    if target is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = ROOT / "debug_output"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"provider_system_probe_{report['provider']}_{stamp}.json"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target


def run_probe(provider: str, model: str, repeat_count: int) -> dict:
    config = _load_config()
    api_key = _resolve_api_key(provider, config)
    if not api_key:
        raise SystemExit(f"No API key configured for provider '{provider}'.")

    client = _build_client(provider, api_key, model)
    runs = []

    for iteration in range(1, repeat_count + 1):
        for case in build_cases():
            started_at = time.time()
            response = client.chat(case.messages, temperature=0.0)
            content = str(response.get("content") or "").strip()
            passed = case.matcher(content, case.expected)
            runs.append(
                {
                    "iteration": iteration,
                    "case": case.name,
                    "description": case.description,
                    "expected": case.expected,
                    "passed": passed,
                    "response_content": content,
                    "elapsed_seconds": round(time.time() - started_at, 3),
                    "messages": case.messages,
                }
            )

    passed_count = sum(1 for row in runs if row.get("passed"))
    return {
        "provider": provider,
        "model": model,
        "repeat_count": repeat_count,
        "run_count": len(runs),
        "passed_count": passed_count,
        "failed_count": len(runs) - passed_count,
        "all_passed": passed_count == len(runs),
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=sorted(CLIENT_FACTORIES),
        default="deepseek",
        help="Provider to probe.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Override model name. Defaults to the provider setting from config/config.yaml.",
    )
    parser.add_argument(
        "--repeat-count",
        type=int,
        default=1,
        help="How many times to run the full probe suite.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = _load_config()
    model = _resolve_model(args.provider, config, args.model)
    report = run_probe(args.provider, model, args.repeat_count)
    report_path = _write_report(report, Path(args.output).resolve() if args.output else None)

    print(f"provider={report['provider']} model={report['model']}")
    print(
        f"passed={report['passed_count']}/{report['run_count']} "
        f"all_passed={str(report['all_passed']).lower()}"
    )
    for row in report["runs"]:
        status = "PASS" if row["passed"] else "FAIL"
        print(
            f"[{status}] iter={row['iteration']} case={row['case']} "
            f"expected={row['expected']} response={json.dumps(row['response_content'], ensure_ascii=False)}"
        )
    print(f"report={report_path}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
