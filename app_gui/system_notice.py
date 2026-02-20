"""Unified system notice payloads for status bar and AI chat feeds."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def build_system_notice(
    *,
    code: str,
    text: str,
    level: str = "info",
    source: str = "app",
    timeout_ms: int = 2000,
    details: Optional[str] = None,
    data: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a normalized ``system_notice`` event payload."""
    payload: Dict[str, Any] = {
        "type": "system_notice",
        "code": str(code or "notice"),
        "level": str(level or "info"),
        "text": str(text or ""),
        "source": str(source or "app"),
        "timeout_ms": int(timeout_ms or 0),
    }
    if details:
        payload["details"] = str(details)
    if isinstance(data, Mapping):
        payload["data"] = dict(data)
    return payload


def _with_legacy_data(event: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Attach legacy event payload for debugging/context tracing."""
    data = dict(kwargs)
    data["legacy_event"] = dict(event)
    return data


def coerce_system_notice(event: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert legacy operation events into ``system_notice`` payloads.

    Returns ``None`` when conversion is not possible.
    """
    if not isinstance(event, Mapping):
        return None

    if str(event.get("type") or "") == "system_notice":
        payload = dict(event)
        payload.setdefault("code", "notice")
        payload.setdefault("level", "info")
        payload.setdefault("text", "")
        payload.setdefault("source", "app")
        payload.setdefault("timeout_ms", 2000)
        return payload

    event_type = str(event.get("type") or "").strip().lower()
    source = str(event.get("source") or "app")
    timestamp = event.get("timestamp")

    notice: Optional[Dict[str, Any]] = None

    if event_type == "plan_staged":
        count = int(event.get("added_count") or 0)
        text = str(event.get("text") or f"Added {count} item(s) to plan.")
        sample = event.get("sample") if isinstance(event.get("sample"), list) else []
        details = "\n".join(str(v) for v in sample[:8]) if sample else None
        notice = build_system_notice(
            code="plan.stage.accepted",
            text=text,
            level="info",
            source=source,
            details=details,
            data=_with_legacy_data(
                event,
                added_count=count,
                total_count=int(event.get("total_count") or 0),
                action_counts=event.get("action_counts") or {},
                items=event.get("items") if isinstance(event.get("items"), list) else [],
            ),
        )

    elif event_type == "plan_stage_blocked":
        blocked_items = event.get("blocked_items") if isinstance(event.get("blocked_items"), list) else []
        text = str(event.get("text") or event.get("message") or "Plan rejected.")
        details = event.get("details")
        if not details and blocked_items:
            details = "\n".join(str((it or {}).get("message") or (it or {}).get("error_code") or "Validation failed") for it in blocked_items[:3])
        notice = build_system_notice(
            code="plan.stage.blocked",
            text=text,
            level="error",
            source=source,
            details=str(details) if details else None,
            data=_with_legacy_data(
                event,
                blocked_items=blocked_items,
                errors=event.get("errors") if isinstance(event.get("errors"), list) else [],
                stats=event.get("stats") if isinstance(event.get("stats"), Mapping) else {},
            ),
        )

    elif event_type in ("plan_executed", "plan_execute_blocked"):
        if event_type == "plan_execute_blocked":
            blocked_count = int(event.get("blocked_count") or 0)
            fallback = f"Plan blocked: {blocked_count} item(s) failed validation." if blocked_count else "Plan blocked by validation."
            text = str(event.get("text") or event.get("summary") or fallback)
        else:
            text = str(event.get("text") or event.get("summary") or "Plan execution finished.")
        rollback_raw = event.get("rollback")
        stats_raw = event.get("stats")
        report_raw = event.get("report")
        rollback_map = rollback_raw if isinstance(rollback_raw, dict) else {}
        stats_map = stats_raw if isinstance(stats_raw, dict) else {}
        report_map = report_raw if isinstance(report_raw, dict) else {}
        level = "success"
        if event_type == "plan_execute_blocked":
            level = "error"
        elif not bool(event.get("ok", False)):
            level = "warning" if bool(rollback_map.get("ok")) else "error"
        notice = build_system_notice(
            code="plan.execute.result",
            text=text,
            level=level,
            source=source,
            details=str(event.get("details") or "") or None,
            data=_with_legacy_data(
                event,
                blocked_count=int(event.get("blocked_count") or 0),
                stats=stats_map,
                rollback=rollback_map,
                report=report_map,
            ),
        )

    elif event_type == "plan_removed":
        count = int(event.get("removed_count") or 0)
        text = str(event.get("text") or f"Removed {count} plan item(s).")
        notice = build_system_notice(
            code="plan.removed",
            text=text,
            level="info",
            source=source,
            data=_with_legacy_data(
                event,
                removed_count=count,
                total_count=int(event.get("total_count") or 0),
                action_counts=event.get("action_counts") or {},
            ),
        )

    elif event_type == "plan_cleared":
        text = str(event.get("text") or "Plan cleared.")
        notice = build_system_notice(
            code="plan.cleared",
            text=text,
            level="info",
            source=source,
            data=_with_legacy_data(
                event,
                cleared_count=int(event.get("cleared_count") or 0),
                action_counts=event.get("action_counts") or {},
            ),
        )

    elif event_type == "plan_restored":
        count = int(event.get("restored_count") or 0)
        text = str(event.get("text") or f"Plan restored: {count} item(s).")
        notice = build_system_notice(
            code="plan.restored",
            text=text,
            level="success",
            source=source,
            data=_with_legacy_data(
                event,
                restored_count=count,
                action_counts=event.get("action_counts") or {},
            ),
        )

    elif event_type == "box_layout_adjusted":
        ok = bool(event.get("ok", False))
        text = str(event.get("text") or event.get("message") or "Boxes updated.")
        notice = build_system_notice(
            code="box.layout.adjusted",
            text=text,
            level="success" if ok else "error",
            source=source,
            data=_with_legacy_data(
                event,
                ok=ok,
                operation=str(event.get("operation") or "unknown"),
                preview=event.get("preview") if isinstance(event.get("preview"), Mapping) else {},
                error_code=event.get("error_code"),
            ),
        )

    elif str(event.get("action") or "") == "edit_entry":
        rid = event.get("record_id")
        field = event.get("field")
        before = event.get("before")
        after = event.get("after")
        text = str(event.get("text") or f"Record {rid}: updated {field} ({before} -> {after}).")
        notice = build_system_notice(
            code="record.edit.saved",
            text=text,
            level="success",
            source=source,
            data=_with_legacy_data(
                event,
                record_id=rid,
                field=field,
                before=before,
                after=after,
            ),
        )

    if notice is None:
        return None

    if timestamp:
        notice["timestamp"] = timestamp
    return notice
