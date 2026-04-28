"""Development-only diagnostics for SnowFox hot paths.

Diagnostics are intentionally controlled only by environment variables:

- SNOWFOX_DIAGNOSTICS=1 enables JSONL diagnostics.
- SNOWFOX_EVENT_BUS_TRACE=1 enables event-bus spans, but only when the
  main diagnostics switch is enabled.

The logger writes compact, sanitized JSONL records under the user config
directory and never stores prompts, API keys, full tool inputs, field values,
or YAML document content.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .app_storage import get_user_config_dir


_DIAGNOSTICS_ENV = "SNOWFOX_DIAGNOSTICS"
_EVENT_BUS_TRACE_ENV = "SNOWFOX_EVENT_BUS_TRACE"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3
_LOG_LOCK = threading.Lock()
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "prompt",
    "content",
    "tool_input",
    "fields",
    "yaml_content",
    "document",
)


def _truthy_env(name: str) -> bool:
    value = str(os.environ.get(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "on", "debug"}


def diagnostics_enabled() -> bool:
    return _truthy_env(_DIAGNOSTICS_ENV)


def event_bus_trace_enabled() -> bool:
    return diagnostics_enabled() and _truthy_env(_EVENT_BUS_TRACE_ENV)


def new_trace_id(prefix: str = "trace") -> str:
    safe_prefix = str(prefix or "trace").strip() or "trace"
    return f"{safe_prefix}-{uuid.uuid4().hex}"


def _log_dir() -> Path:
    return Path(get_user_config_dir()) / "dev_logs"


def diagnostics_log_path() -> str:
    return str(_log_dir() / "snowfox-diagnostics.jsonl")


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < _LOG_MAX_BYTES:
            return
        for idx in range(_LOG_BACKUP_COUNT - 1, 0, -1):
            src = path.with_name(f"{path.name}.{idx}")
            dst = path.with_name(f"{path.name}.{idx + 1}")
            if src.exists():
                if idx + 1 > _LOG_BACKUP_COUNT:
                    src.unlink(missing_ok=True)
                else:
                    src.replace(dst)
        path.replace(path.with_name(f"{path.name}.1"))
    except Exception:
        return


def _looks_sensitive(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return os.path.basename(text) or text
    except Exception:
        return text


def _sanitize_value(key: str, value: Any, depth: int = 0) -> Any:
    if _looks_sensitive(key):
        return "[redacted]"

    key_lower = str(key or "").lower()
    if key_lower.endswith("_path") or key_lower == "path":
        return _sanitize_path(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) > 160:
            return f"{text[:157]}..."
        return text
    if depth >= 2:
        return f"[{type(value).__name__}]"
    if isinstance(value, dict):
        cleaned = {}
        for item_key, item_value in list(value.items())[:20]:
            cleaned[str(item_key)] = _sanitize_value(str(item_key), item_value, depth + 1)
        if len(value) > 20:
            cleaned["_truncated"] = len(value) - 20
        return cleaned
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        cleaned = [_sanitize_value(key, item, depth + 1) for item in values[:20]]
        if len(values) > 20:
            cleaned.append({"_truncated": len(values) - 20})
        return cleaned
    return str(value)


def _sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _sanitize_value(str(key), value) for key, value in fields.items()}


def log_event(event: str, **fields: Any) -> None:
    if not diagnostics_enabled():
        return

    payload = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "event": str(event or "diagnostic"),
    }
    payload.update(_sanitize_fields(dict(fields or {})))

    path = Path(diagnostics_log_path())
    with _LOG_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        except Exception:
            return


@contextmanager
def span(name: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Record one duration span when diagnostics are enabled."""

    if not diagnostics_enabled():
        yield {}
        return

    start = time.perf_counter()
    context = dict(fields or {})
    try:
        yield context
        status = context.pop("status", "ok")
    except Exception as exc:
        context["exception_type"] = type(exc).__name__
        context["exception"] = str(exc)
        status = "error"
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        log_event(
            str(name or "span"),
            duration_ms=round(duration_ms, 3),
            status=status,
            **context,
        )

