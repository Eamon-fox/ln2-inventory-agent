"""Compact/expand operation events for AI context without losing information."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compact_plan_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Deduplicate repeated per-item `response` payloads into a response pool."""
    payload = dict(report or {})
    items = payload.get("items")
    if not isinstance(items, list):
        return payload

    response_pool = []
    response_index = {}
    compact_items = []
    deduped = 0

    for entry in items:
        if not isinstance(entry, Mapping):
            compact_items.append(entry)
            continue

        row = dict(entry)
        response = row.get("response")
        if isinstance(response, Mapping):
            response_obj = dict(response)
            key = _canonical_json(response_obj)
            idx = response_index.get(key)
            if idx is None:
                idx = len(response_pool)
                response_pool.append(response_obj)
                response_index[key] = idx
            else:
                deduped += 1
            row.pop("response", None)
            row["response_ref"] = idx
        compact_items.append(row)

    if not response_pool:
        return payload

    payload["items"] = compact_items
    payload["response_pool"] = response_pool
    payload["_compact_meta"] = {
        "scheme": "response_pool_v1",
        "pool_size": len(response_pool),
        "deduped_responses": deduped,
    }
    return payload


def expand_plan_report(compact_report: Mapping[str, Any]) -> Dict[str, Any]:
    """Rehydrate a compact report back to original per-item `response` shape."""
    payload = dict(compact_report or {})
    pool = payload.get("response_pool")
    items = payload.get("items")
    if not isinstance(pool, list) or not isinstance(items, list):
        return payload

    expanded_items = []
    for entry in items:
        if not isinstance(entry, Mapping):
            expanded_items.append(entry)
            continue

        row = dict(entry)
        ref = row.pop("response_ref", None)
        if isinstance(ref, int) and 0 <= ref < len(pool):
            response = pool[ref]
            if isinstance(response, Mapping):
                row["response"] = dict(response)
            else:
                row["response"] = response
        expanded_items.append(row)

    payload["items"] = expanded_items
    payload.pop("response_pool", None)
    payload.pop("_compact_meta", None)
    return payload


def compact_operation_event_for_context(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact large operation events for model context windows."""
    payload = dict(event or {})
    event_type = payload.get("type")
    report = payload.get("report")
    if event_type in ("plan_executed", "plan_execute_blocked") and isinstance(report, Mapping):
        payload["report"] = compact_plan_report(report)
    return payload
