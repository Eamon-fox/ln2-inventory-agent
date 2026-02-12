"""Shared helpers for plan execution outcomes across GUI panels."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_blocked_items(report: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    """Return blocked per-item report entries."""
    payload = report if isinstance(report, Mapping) else {}
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    blocked: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("blocked"):
            blocked.append(item)
    return blocked


def summarize_plan_execution(
    report: Mapping[str, Any] | None,
    rollback: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compute canonical execution stats, including rollback-adjusted applied count."""
    payload = report if isinstance(report, Mapping) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), Mapping) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []

    total_count = _to_int(stats.get("total"), default=len(items))
    ok_count = _to_int(
        stats.get("ok"),
        default=sum(1 for item in items if isinstance(item, Mapping) and item.get("ok")),
    )
    blocked_count = _to_int(
        stats.get("blocked"),
        default=sum(1 for item in items if isinstance(item, Mapping) and item.get("blocked")),
    )
    fail_count = max(blocked_count, total_count - ok_count)

    rollback_payload = rollback if isinstance(rollback, Mapping) else {}
    rollback_attempted = bool(rollback_payload.get("attempted"))
    rollback_ok = bool(rollback_payload.get("ok"))
    rollback_message = str(rollback_payload.get("message") or "").strip()

    applied_count = 0 if rollback_ok else ok_count

    return {
        "total_count": total_count,
        "ok_count": ok_count,
        "blocked_count": blocked_count,
        "fail_count": fail_count,
        "applied_count": applied_count,
        "rollback_attempted": rollback_attempted,
        "rollback_ok": rollback_ok,
        "rollback_message": rollback_message,
    }
