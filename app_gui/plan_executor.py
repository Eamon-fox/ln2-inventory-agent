"""Unified Plan execution engine with preflight validation."""

from __future__ import annotations

import copy
import os
import tempfile
from datetime import date
from typing import Dict, List, Optional, Tuple

from lib.yaml_ops import load_yaml, write_yaml


def _make_error_item(item: Dict[str, object], error_code: str, message: str) -> Dict[str, object]:
    """Create an error report for a plan item."""
    return {
        "item": item,
        "ok": False,
        "blocked": True,
        "error_code": error_code,
        "message": message,
    }


def _make_ok_item(item: Dict[str, object], response: Dict[str, object]) -> Dict[str, object]:
    """Create a success report for a plan item."""
    return {
        "item": item,
        "ok": True,
        "blocked": False,
        "response": response,
    }


def preflight_plan(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: Optional[str] = None,
) -> Dict[str, object]:
    """Run plan validation without modifying real data.

    Creates a temporary copy of the YAML and executes the plan against it.
    Returns a report with per-item validation status.
    """
    if not items:
        return {
            "ok": True,
            "blocked": False,
            "items": [],
            "stats": {"total": 0, "ok": 0, "blocked": 0},
            "summary": "No items to validate.",
        }

    if not os.path.isfile(yaml_path):
        return {
            "ok": False,
            "blocked": True,
            "items": [_make_error_item(it, "yaml_not_found", f"YAML file not found: {yaml_path}") for it in items],
            "stats": {"total": len(items), "ok": 0, "blocked": len(items)},
            "summary": f"YAML file not found: {yaml_path}",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "blocked": True,
            "items": [_make_error_item(it, "yaml_load_failed", str(exc)) for it in items],
            "stats": {"total": len(items), "ok": 0, "blocked": len(items)},
            "summary": f"Failed to load YAML: {exc}",
        }

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp_path = tmp.name

    try:
        write_yaml(data, tmp_path, auto_backup=False, audit_meta={"action": "preflight", "source": "plan_executor"})
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        reports = [_make_error_item(it, "preflight_snapshot_invalid", str(exc)) for it in items]
        return {
            "ok": False,
            "blocked": True,
            "items": reports,
            "stats": {"total": len(items), "ok": 0, "blocked": len(reports)},
            "summary": f"Preflight blocked before simulation: {exc}",
        }

    try:
        result = run_plan(
            yaml_path=tmp_path,
            items=items,
            bridge=bridge,
            date_str=date_str,
            mode="preflight",
        )
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def run_plan(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: Optional[str] = None,
    mode: str = "execute",
) -> Dict[str, object]:
    """Execute or validate a plan against a YAML file.

    Args:
        yaml_path: Path to the inventory YAML file.
        items: List of plan items (each with action, box, position, record_id, payload, etc.).
        bridge: GuiToolBridge instance for executing operations.
        date_str: Optional date string for operations.
        mode: "execute" for real execution, "preflight" for validation-only.

    Returns:
        Dict with keys:
        - ok: overall success
        - blocked: whether any item was blocked
        - items: per-item reports
        - stats: summary counts
        - summary: human-readable summary
        - backup_path: backup path if any writes occurred (execute mode only)
    """
    if not items:
        return {
            "ok": True,
            "blocked": False,
            "items": [],
            "stats": {"total": 0, "ok": 0, "blocked": 0},
            "summary": "No items to process.",
            "backup_path": None,
        }

    if mode not in ("execute", "preflight"):
        mode = "execute"

    rollback_items = [it for it in items if it.get("action") == "rollback"]
    if rollback_items and len(items) != 1:
        reports = [
            _make_error_item(
                it,
                "rollback_must_be_alone",
                "Rollback must be executed as the only plan item (no mixing).",
            )
            for it in items
        ]
        return {
            "ok": False,
            "blocked": True,
            "items": reports,
            "stats": {"total": len(reports), "ok": 0, "blocked": len(reports), "remaining": len(items)},
            "summary": "Blocked: rollback cannot be mixed with other operations.",
            "backup_path": None,
            "remaining_items": list(items),
        }

    effective_date = date_str or date.today().isoformat()
    reports: List[Dict[str, object]] = []
    last_backup: Optional[str] = None

    remaining = list(items)

    # Phase 0: rollback (must be executed alone, enforced above)
    rollbacks = [it for it in remaining if it.get("action") == "rollback"]
    for item in rollbacks:
        payload = dict(item.get("payload") or {})
        backup_path = payload.get("backup_path")
        source_event = payload.get("source_event")

        if mode == "preflight":
            response = _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_rollback",
                backup_path=backup_path,
                source_event=source_event,
            )
        else:
            rollback_kwargs = {
                "yaml_path": yaml_path,
                "backup_path": backup_path,
                "execution_mode": "execute",
            }
            if isinstance(source_event, dict) and source_event:
                rollback_kwargs["source_event"] = source_event
            response = bridge.rollback(**rollback_kwargs)

        if response.get("ok"):
            reports.append(_make_ok_item(item, response))
            remaining.remove(item)
            snapshot = response.get("backup_path") or (response.get("result") or {}).get("snapshot_before_rollback")
            if snapshot:
                last_backup = snapshot
        else:
            reports.append(
                _make_error_item(
                    item,
                    response.get("error_code", "rollback_failed"),
                    response.get("message", "Rollback failed"),
                )
            )

    # Phase 1: add operations (each add is independent)
    adds = [it for it in remaining if it.get("action") == "add"]

    # Cross-item conflict detection: flag adds that target positions already
    # claimed by an earlier add in the same batch.  Pure in-memory check —
    # no file I/O, no side-effects.
    _add_claimed: set[tuple[int, int]] = set()  # (box, position)
    _add_blocked_ids: set[int] = set()
    for item in adds:
        payload = item.get("payload") or {}
        box = int(payload.get("box") or item.get("box") or 0)
        positions = payload.get("positions") or []
        for pos in positions:
            key = (box, int(pos))
            if key in _add_claimed:
                _add_blocked_ids.add(id(item))
                break
            _add_claimed.add(key)

    for item in adds:
        if id(item) in _add_blocked_ids:
            reports.append(_make_error_item(item, "position_conflict", "位置冲突（同批次内重复）"))
            continue

        payload = dict(item.get("payload") or {})
        if mode == "preflight":
            response = _preflight_add_entry(bridge, yaml_path, payload)
        else:
            response = bridge.add_entry(yaml_path=yaml_path, execution_mode="execute", **payload)

        if response.get("ok"):
            reports.append(_make_ok_item(item, response))
            remaining.remove(item)
            if response.get("backup_path"):
                last_backup = response["backup_path"]
        else:
            reports.append(_make_error_item(item, response.get("error_code", "add_failed"), response.get("message", "Add failed")))

    # Phase 1.5: edit operations (each edit is independent)
    edits = [it for it in remaining if it.get("action") == "edit"]
    for item in edits:
        payload = dict(item.get("payload") or {})
        if mode == "preflight":
            response = _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_edit_entry",
                record_id=payload.get("record_id"),
                fields=payload.get("fields", {}),
            )
        else:
            response = bridge.edit_entry(
                yaml_path=yaml_path,
                record_id=payload.get("record_id"),
                fields=payload.get("fields", {}),
                execution_mode="execute",
            )

        if response.get("ok"):
            reports.append(_make_ok_item(item, response))
            remaining.remove(item)
            if response.get("backup_path"):
                last_backup = response["backup_path"]
        else:
            reports.append(_make_error_item(item, response.get("error_code", "edit_failed"), response.get("message", "Edit failed")))

    # Phase 2: move operations (execute as a single batch)
    moves = [it for it in remaining if it.get("action") == "move"]
    if moves:
        batch_ok, batch_reports = _execute_moves_batch(
            yaml_path=yaml_path,
            items=moves,
            bridge=bridge,
            date_str=effective_date,
            mode=mode,
        )
        reports.extend(batch_reports)
        for r in batch_reports:
            if r.get("ok") and r.get("item") in remaining:
                remaining.remove(r["item"])
                if r.get("response", {}).get("backup_path"):
                    last_backup = r["response"]["backup_path"]

    # Phase 3: out operations (takeout/thaw/discard collapsed to Takeout)
    out_items = [it for it in remaining if str(it.get("action") or "").lower() in {"takeout", "thaw", "discard"}]
    if out_items:
        batch_ok, batch_reports = _execute_thaw_batch(
            yaml_path=yaml_path,
            items=out_items,
            action_name="Takeout",
            bridge=bridge,
            date_str=effective_date,
            mode=mode,
        )
        reports.extend(batch_reports)
        for r in batch_reports:
            if r.get("ok") and r.get("item") in remaining:
                remaining.remove(r["item"])
                if r.get("response", {}).get("backup_path"):
                    last_backup = r["response"]["backup_path"]

    # Finalize
    ok_count = sum(1 for r in reports if r.get("ok"))
    blocked_count = sum(1 for r in reports if r.get("blocked"))
    has_blocked = blocked_count > 0

    if has_blocked:
        summary = f"Blocked: {blocked_count}/{len(reports)} items cannot execute."
    elif ok_count == len(reports):
        summary = f"All {ok_count} operation(s) succeeded."
    else:
        summary = f"Completed: {ok_count} ok, {blocked_count} blocked, {len(remaining)} remaining."

    return {
        "ok": not has_blocked,
        "blocked": has_blocked,
        "items": reports,
        "stats": {"total": len(reports), "ok": ok_count, "blocked": blocked_count, "remaining": len(remaining)},
        "summary": summary,
        "backup_path": last_backup,
        "remaining_items": remaining,
    }


def _run_preflight_tool(
    bridge: object,
    yaml_path: str,
    tool_name: str,
    **payload: object,
) -> Dict[str, object]:
    """Invoke lib.tool_api in preflight using full execute-mode validation.

    Preflight always runs against a temporary YAML copy, so execute-mode writes are
    safe and let us reuse the same validation path as real execution.
    """
    try:
        from lib import tool_api
    except ImportError:
        return {"ok": False, "error_code": "import_error", "message": "Failed to import tool_api"}

    tool_fn = getattr(tool_api, tool_name, None)
    build_actor_context = getattr(tool_api, "build_actor_context", None)
    if not callable(tool_fn) or not callable(build_actor_context):
        return {"ok": False, "error_code": "import_error", "message": f"Failed to resolve {tool_name}"}

    actor_context = getattr(bridge, "_ctx", lambda: None)() or build_actor_context(actor_type="human", channel="gui")

    return tool_fn(
        yaml_path=yaml_path,
        dry_run=False,
        execution_mode="execute",
        actor_context=actor_context,
        source="plan_executor.preflight",
        auto_backup=False,
        **payload,
    )


def _preflight_add_entry(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate add_entry with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_add_entry",
        box=payload.get("box"),
        positions=payload.get("positions"),
        frozen_at=payload.get("frozen_at"),
        fields=payload.get("fields"),
    )


def _preflight_batch_thaw(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate batch_thaw with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_batch_thaw",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
        action=payload.get("action", "Takeout"),
    )


def _execute_moves_batch(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: str,
    mode: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute move operations using a single batch strategy."""
    reports: List[Dict[str, object]] = []

    entries = []
    for item in items:
        p = item.get("payload") or {}
        entry = (p.get("record_id"), p.get("position"), p.get("to_position"))
        if p.get("to_box") is not None:
            entry = entry + (p.get("to_box"),)
        entries.append(entry)

    first_item = items[0] if items else {}
    first_payload = first_item.get("payload") or {}
    batch_payload = {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
        "action": "Move",
    }

    if mode == "preflight":
        response = _preflight_batch_thaw(bridge, yaml_path, batch_payload)
    else:
        response = bridge.batch_thaw(yaml_path=yaml_path, execution_mode="execute", **batch_payload)

    if response.get("ok"):
        for item in items:
            reports.append(_make_ok_item(item, response))
        return True, reports

    # Batch failed - mark all as blocked (no fallback).
    for item in items:
        reports.append(
            _make_error_item(
                item,
                response.get("error_code", "move_batch_failed"),
                response.get("message", "Move batch failed"),
            )
        )
    return False, reports


def _execute_thaw_batch(
    yaml_path: str,
    items: List[Dict[str, object]],
    action_name: str,
    bridge: object,
    date_str: str,
    mode: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute takeout/thaw/discard operations.

    - Preflight: validate each item individually for precise error reporting.
    - Execute: run as a single batch (no fallback).
    """
    reports: List[Dict[str, object]] = []

    if mode == "preflight":
        all_ok = True
        for item in items:
            p = item.get("payload") or {}
            single_payload = {
                "record_id": p.get("record_id"),
                "position": p.get("position"),
                "date_str": p.get("date_str", date_str),
                "action": action_name,
            }
            response = _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_record_thaw",
                **single_payload,
            )
            if response.get("ok"):
                reports.append(_make_ok_item(item, response))
            else:
                reports.append(
                    _make_error_item(
                        item,
                        response.get("error_code", "thaw_failed"),
                        response.get("message", "Operation failed"),
                    )
                )
                all_ok = False
        return all_ok, reports

    entries = []
    for item in items:
        p = item.get("payload") or {}
        entries.append((p.get("record_id"), p.get("position")))

    first_item = items[0] if items else {}
    first_payload = first_item.get("payload") or {}
    batch_payload = {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
        "action": action_name,
    }

    response = bridge.batch_thaw(yaml_path=yaml_path, execution_mode="execute", **batch_payload)

    if response.get("ok"):
        for item in items:
            reports.append(_make_ok_item(item, response))
        return True, reports

    # Batch failed - mark all as blocked (no fallback).
    for item in items:
        reports.append(
            _make_error_item(
                item,
                response.get("error_code", "thaw_batch_failed"),
                response.get("message", "Batch operation failed"),
            )
        )
    return False, reports
