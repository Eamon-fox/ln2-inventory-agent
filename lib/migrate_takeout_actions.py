"""Migration helpers to normalize legacy takeout event actions."""

from __future__ import annotations

from copy import deepcopy
from contextlib import suppress
from typing import Any, Dict, List, Optional

from .takeout_parser import normalize_action
from .yaml_ops import load_yaml, write_yaml


_LEGACY_TAKEOUT_ALIASES = {
    "thaw",
    "discard",
    "复苏",
    "扔掉",
    "丢弃",
}


def _normalize_event_action(raw_action: Any) -> Optional[str]:
    """Return canonical action for stored events or ``None`` when unsupported."""
    if raw_action in (None, ""):
        return None

    raw_text = str(raw_action).strip()
    if not raw_text:
        return None

    lower = raw_text.lower()
    if lower in _LEGACY_TAKEOUT_ALIASES or raw_text in _LEGACY_TAKEOUT_ALIASES:
        return "takeout"

    normalized = normalize_action(raw_text)
    if normalized in {"takeout", "move"}:
        return normalized
    return None


def migrate_takeout_actions(
    yaml_path: str,
    *,
    dry_run: bool = False,
    auto_backup: bool = True,
    audit_source: str = "migration",
) -> Dict[str, Any]:
    """Convert legacy ``thaw/discard`` event actions to ``takeout``.

    The migration is idempotent:
    - already normalized ``takeout/move`` events stay unchanged
    - unknown actions are preserved and reported
    """
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML: {exc}",
        }

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return {
            "ok": False,
            "error_code": "invalid_inventory",
            "message": "YAML inventory must be a list.",
        }

    candidate = deepcopy(data)
    candidate_inventory = candidate.get("inventory", [])

    changed_events = 0
    scanned_events = 0
    changed_record_ids: List[int] = []
    unknown_actions: Dict[str, int] = {}

    for rec in candidate_inventory:
        if not isinstance(rec, dict):
            continue

        rec_id = rec.get("id")
        events = rec.get("thaw_events")
        if not isinstance(events, list):
            continue

        record_changed = False
        for ev in events:
            if not isinstance(ev, dict):
                continue
            scanned_events += 1

            raw_action = ev.get("action")
            normalized = _normalize_event_action(raw_action)
            if normalized is None:
                key = str(raw_action)
                unknown_actions[key] = unknown_actions.get(key, 0) + 1
                continue

            if str(raw_action).strip() != normalized:
                ev["action"] = normalized
                changed_events += 1
                record_changed = True

        if record_changed:
            with suppress(Exception):
                changed_record_ids.append(int(rec_id))

    summary = {
        "records_total": len(candidate_inventory),
        "records_changed": len(changed_record_ids),
        "changed_record_ids": sorted(set(changed_record_ids)),
        "events_scanned": scanned_events,
        "events_changed": changed_events,
        "unknown_actions": unknown_actions,
    }

    if dry_run or changed_events == 0:
        return {
            "ok": True,
            "dry_run": bool(dry_run),
            "changed": changed_events > 0,
            "summary": summary,
            "backup_path": None,
        }

    try:
        backup_path = write_yaml(
            candidate,
            yaml_path,
            auto_backup=auto_backup,
            audit_meta={
                "action": "migrate_takeout_actions",
                "source": audit_source,
                "tool_name": "migrate_takeout_actions",
                "details": summary,
                "tool_input": {
                    "yaml_path": yaml_path,
                    "dry_run": False,
                },
            },
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "write_failed",
            "message": f"Failed to write migrated YAML: {exc}",
            "summary": summary,
        }

    return {
        "ok": True,
        "dry_run": False,
        "changed": True,
        "summary": summary,
        "backup_path": backup_path,
    }
