"""Compact/expand operation events for AI context without losing information."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from typing import Any, Dict, List, Mapping


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _truncate_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _single_line(value: Any, limit: int = 240) -> str:
    text = _truncate_text(value, limit=limit)
    return " | ".join(part.strip() for part in text.splitlines() if part.strip())


def _extract_record_ids(*values: Any) -> List[int]:
    ids = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, Mapping):
            iterable = value.values()
        elif isinstance(value, (list, tuple, set)):
            iterable = value
        else:
            iterable = [value]

        for item in iterable:
            if isinstance(item, (Mapping, list, tuple, set)):
                nested = _extract_record_ids(item)
                ids.update(nested)
                continue
            for raw in re.findall(r"id\s*=\s*(\d+)", str(item), flags=re.IGNORECASE):
                with suppress(Exception):
                    ids.add(int(raw))
    return sorted(ids)


def _compact_stage_blocked_notice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Compact verbose plan.stage.blocked payloads for model context."""
    out = dict(payload)
    out["text"] = _single_line(out.get("text"), limit=220)
    if "details" in out:
        out["details"] = _single_line(out.get("details"), limit=360)

    data = out.get("data")
    if not isinstance(data, Mapping):
        return out

    compact_data = dict(data)

    blocked_items = compact_data.get("blocked_items")
    if isinstance(blocked_items, list):
        compact_blocked = []
        for item in blocked_items[:6]:
            if not isinstance(item, Mapping):
                continue
            compact_blocked.append(
                {
                    "action": item.get("action"),
                    "record_id": item.get("record_id"),
                    "box": item.get("box"),
                    "position": item.get("position"),
                    "to_box": item.get("to_box"),
                    "to_position": item.get("to_position"),
                    "error_code": item.get("error_code"),
                    "message": _single_line(item.get("message"), limit=160),
                }
            )
        compact_data["blocked_items"] = compact_blocked

    errors = compact_data.get("errors")
    if isinstance(errors, list):
        compact_errors = []
        for item in errors[:6]:
            if not isinstance(item, Mapping):
                continue
            entry = {
                "kind": item.get("kind"),
                "error_code": item.get("error_code"),
                "message": _single_line(item.get("message"), limit=160),
            }
            raw_item = item.get("item")
            if isinstance(raw_item, Mapping):
                entry["item"] = {
                    "action": raw_item.get("action"),
                    "record_id": raw_item.get("record_id"),
                    "box": raw_item.get("box"),
                    "position": raw_item.get("position"),
                }
            compact_errors.append(entry)
        compact_data["errors"] = compact_errors

    incoming = compact_data.get("incoming_items")
    if isinstance(incoming, list):
        compact_incoming = []
        for item in incoming[:6]:
            if not isinstance(item, Mapping):
                continue
            compact_incoming.append(
                {
                    "action": item.get("action"),
                    "record_id": item.get("record_id"),
                    "box": item.get("box"),
                    "position": item.get("position"),
                }
            )
        compact_data["incoming_items"] = compact_incoming

    compact_data["validation_record_ids"] = _extract_record_ids(
        out.get("text"),
        out.get("details"),
        compact_data.get("errors"),
        compact_data.get("blocked_items"),
    )

    out["data"] = compact_data
    return out


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
    event_type = str(payload.get("type") or "")
    report = payload.get("report")
    if event_type in ("plan_executed", "plan_execute_blocked") and isinstance(report, Mapping):
        payload["report"] = compact_plan_report(report)

    # Unified notice path: keep one event shape, compact heavy nested report payloads.
    if event_type == "system_notice":
        data = payload.get("data")
        if isinstance(data, Mapping):
            compact_data = dict(data)
            report_in_data = compact_data.get("report")
            if isinstance(report_in_data, Mapping):
                compact_data["report"] = compact_plan_report(report_in_data)
            payload["data"] = compact_data

        if str(payload.get("code") or "") == "plan.stage.blocked":
            payload = _compact_stage_blocked_notice(payload)

    # Add human-readable hints so the LLM doesn't confuse plan lifecycle events
    # with actual inventory modifications.
    _EVENT_HINTS: Dict[str, str] = {
        "system_notice": "System notice from GUI. The `text` field is user-facing; `data` carries machine-readable context.",
        "plan_staged": "User added operations to the plan queue. Nothing has been executed yet — the inventory is unchanged.",
        "plan_cleared": "User manually cleared the plan queue. No operations were executed — the inventory is unchanged.",
        "plan_removed": "User removed selected items from the plan queue. No operations were executed — the inventory is unchanged.",
        "plan_restored": "User undid the last execution and restored the previous plan. The inventory was rolled back.",
        "plan_executed": "Plan operations were executed against the inventory. Check stats for success/failure details.",
        "plan_execute_blocked": "Plan execution was blocked due to validation errors. The inventory is unchanged.",
        "box_layout_adjusted": "User adjusted the active box set. This directly changed inventory box metadata.",
    }
    hint = _EVENT_HINTS.get(event_type)
    if hint:
        payload["_hint"] = hint

    return payload
