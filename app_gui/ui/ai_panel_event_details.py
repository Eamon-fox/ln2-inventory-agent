"""Event-details formatting helpers for AIPanel."""

import json

from app_gui.error_localizer import localize_error_payload
from app_gui.i18n import tr


def _format_event_details(self, details_json):
    """Format event JSON as human-readable text."""
    try:
        event = json.loads(str(details_json)) if isinstance(details_json, str) else details_json
    except Exception:
        return str(details_json or "")

    if not isinstance(event, dict):
        return str(event)

    event_type = str(event.get("type", "unknown"))
    if event_type == "system_notice":
        return self._format_system_notice_details(event)

    lines = []
    type_key = (
        f"eventDetails.eventType.{event_type}"
        if event_type.startswith("plan_") or event_type == "box_layout_adjusted"
        else None
    )
    if type_key:
        lines.append(f"{tr('eventDetails.type')}: {tr(type_key, default=event_type)}")
    else:
        lines.append(f"{tr('eventDetails.type')}: {event_type}")

    ts = event.get("timestamp")
    if ts:
        lines.append(f"{tr('eventDetails.time')}: {ts}")

    self._append_event_type_details(lines, event_type, event, tr)

    if "_hint" in event:
        lines.append(f"\n{tr('eventDetails.hint')}: {event['_hint']}")

    if len(lines) <= 2:
        lines = self._build_event_fallback_lines(event, tr)

    return "\n".join(lines) if lines else str(event)


def _append_event_type_details(self, lines, event_type, event, tr_fn):
    if event_type in ("plan_staged", "plan_cleared"):
        self._append_plan_count_lines(lines, event_type, event, tr_fn)
        return
    if event_type == "plan_removed":
        removed = event.get("removed_count", 0)
        lines.append(f"{tr_fn('eventDetails.removed')}: {removed} {tr_fn('eventDetails.items')}")
        lines.append(f"{tr_fn('eventDetails.remaining')}: {event.get('total_count', 0)}")
        return
    if event_type == "plan_restored":
        restored = event.get("restored_count", 0)
        lines.append(f"{tr_fn('eventDetails.restored')}: {restored} {tr_fn('eventDetails.items')}")
        lines.append(f"{tr_fn('eventDetails.backupPath')}: {event.get('backup_path', 'N/A')}")
        return
    if event_type == "box_layout_adjusted":
        self._append_box_layout_lines(lines, event, tr_fn)
        return
    if event_type in ("plan_executed", "plan_execute_blocked"):
        self._append_plan_execution_lines(lines, event, tr_fn)


def _append_plan_count_lines(self, lines, event_type, event, tr_fn):
    if event_type == "plan_staged":
        label = tr_fn("eventDetails.added")
        count = event.get("added_count", 0)
        lines.append(f"{label}: {count} {tr_fn('eventDetails.items')}")
        lines.append(f"{tr_fn('eventDetails.totalInPlan')}: {event.get('total_count', 0)}")
    else:
        label = tr_fn("eventDetails.cleared")
        count = event.get("cleared_count", 0)
        lines.append(f"{label}: {count} {tr_fn('eventDetails.items')}")
    action_counts = event.get("action_counts", {})
    if action_counts:
        lines.append(f"  {tr_fn('eventDetails.actionLabel')}:")
        for key, value in sorted(action_counts.items()):
            action_label = tr_fn(f"eventDetails.action.{key}", default=key)
            lines.append(f"    - {action_label}: {value}")


def _append_box_layout_lines(self, lines, event, tr_fn):
    lines.append(f"{tr_fn('eventDetails.operation')}: {event.get('operation', 'unknown')}")
    preview = event.get("preview", {})
    if not preview:
        return
    before = preview.get("box_count_before", "?")
    after = preview.get("box_count_after", "?")
    lines.append(f"{tr_fn('eventDetails.before')}: {before} {tr_fn('eventDetails.boxes')}")
    lines.append(f"{tr_fn('eventDetails.after')}: {after} {tr_fn('eventDetails.boxes')}")
    added = preview.get("added_boxes", [])
    if added:
        lines.append(f"{tr_fn('eventDetails.addedBoxes')}: {', '.join(str(box_id) for box_id in added)}")
    removed = preview.get("removed_box")
    if removed:
        lines.append(f"{tr_fn('eventDetails.removedBox')}: {removed}")
        lines.append(f"{tr_fn('eventDetails.renumberMode')}: {preview.get('renumber_mode', '?')}")


def _append_plan_execution_lines(self, lines, event, tr_fn):
    ok = event.get("ok", False)
    lines.append(f"{tr_fn('eventDetails.success')}: {ok}")
    stats = event.get("stats", {})
    if stats:
        lines.append(f"{tr_fn('eventDetails.total')}: {stats.get('total', 0)}")
        lines.append(f"{tr_fn('eventDetails.applied')}: {stats.get('applied', 0)}")
        lines.append(f"{tr_fn('eventDetails.blocked')}: {stats.get('blocked', 0)}")

    report = event.get("report")
    if isinstance(report, dict):
        self._append_plan_execution_report(lines, report, tr_fn)

    rollback = event.get("rollback")
    if rollback:
        self._append_plan_execution_rollback(lines, rollback, tr_fn)

    source_event = event.get("source_event")
    if source_event:
        lines.append(f"\n{tr_fn('eventDetails.sourceEvent')}:")
        lines.append(f"  Timestamp: {source_event.get('timestamp', '?')}")
        lines.append(f"  {tr_fn('eventDetails.actionLabel')}: {source_event.get('action', '?')}")


def _append_plan_execution_report(self, lines, report, tr_fn):
    items = report.get("items", [])
    if not items:
        return
    lines.append(f"\n{tr_fn('eventDetails.itemsList')} ({len(items)}):")
    for item in items[:5]:
        action_key = item.get("action", "?")
        action_label = tr_fn(f"eventDetails.action.{action_key}", default=action_key)
        rid = item.get("record_id", "?")
        box = item.get("box", "?")
        pos = item.get("position", "?")
        error = item.get("error") or localize_error_payload(item, fallback=item.get("message"))
        item_line = f"  - [{action_label}] {tr_fn('eventDetails.id')}: {rid}"
        if box != "?" and pos != "?":
            item_line += f" | {tr_fn('eventDetails.box')}: {box}, {tr_fn('eventDetails.position')}: {pos}"
        lines.append(item_line)
        if error:
            lines.append(f"    {tr_fn('eventDetails.error')}: {error}")
    if len(items) > 5:
        more = tr_fn("eventDetails.andMore", count=len(items) - 5)
        lines.append(f"  - ... {more}")


def _append_plan_execution_rollback(self, lines, rollback, tr_fn):
    lines.append(f"\n{tr_fn('eventDetails.rollback')}:")
    if rollback.get("ok"):
        lines.append(f"  {tr_fn('eventDetails.rollbackOk')}")
        return
    if rollback.get("failed"):
        lines.append(
            f"  {tr_fn('eventDetails.rollbackFailed')}: "
            f"{localize_error_payload(rollback, fallback=rollback.get('message', '?'))}"
        )
        return
    lines.append(
        f"  {tr_fn('eventDetails.rollBackUnavailable')}: "
        f"{localize_error_payload(rollback, fallback=rollback.get('message', '?'))}"
    )


def _build_event_fallback_lines(event, tr_fn):
    lines = []
    skip_keys = ("type", "timestamp", "_hint", "response_pool", "_compact_meta", "report", "preview")
    for key in sorted(event.keys()):
        if key in skip_keys:
            continue
        value = event[key]
        if isinstance(value, (list, dict)):
            value = f"<{type(value).__name__} with {len(value)} {tr_fn('eventDetails.items')}>"
        lines.append(f"{key}: {value}")
    return lines
