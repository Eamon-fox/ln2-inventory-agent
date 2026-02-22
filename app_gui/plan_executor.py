"""Unified Plan execution engine with preflight validation."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

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


def _resolve_error_from_response(
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Tuple[str, str]:
    if not isinstance(response, dict):
        return fallback_error_code, fallback_message
    return (
        response.get("error_code", fallback_error_code),
        response.get("message", fallback_message),
    )


def _make_error_item_from_response(
    item: Dict[str, object],
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Dict[str, object]:
    error_code, message = _resolve_error_from_response(
        response,
        fallback_error_code=fallback_error_code,
        fallback_message=fallback_message,
    )
    return _make_error_item(item, error_code, message)


def _fanout_batch_response(
    items: List[Dict[str, object]],
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Convert one batch response into per-item reports."""
    reports: List[Dict[str, object]] = []
    if response.get("ok"):
        for item in items:
            reports.append(_make_ok_item(item, response))
        return True, reports

    for item in items:
        reports.append(
            _make_error_item_from_response(
                item,
                response,
                fallback_error_code=fallback_error_code,
                fallback_message=fallback_message,
            )
        )
    return False, reports


def _append_item_report(
    reports: List[Dict[str, object]],
    *,
    item: Dict[str, object],
    response: Dict[str, object],
    fallback_error_code: str,
    fallback_message: str,
) -> bool:
    """Append one per-item report and return whether it succeeded."""
    if response.get("ok"):
        reports.append(_make_ok_item(item, response))
        return True
    reports.append(
        _make_error_item_from_response(
            item,
            response,
            fallback_error_code=fallback_error_code,
            fallback_message=fallback_message,
        )
    )
    return False


def _update_last_backup(
    last_backup: Optional[str],
    response: Dict[str, object],
    *,
    include_snapshot_before_rollback: bool = False,
) -> Optional[str]:
    """Extract backup path from one tool response and update running backup marker."""
    if not isinstance(response, dict):
        return last_backup

    backup_path = response.get("backup_path")
    if backup_path:
        return backup_path

    if include_snapshot_before_rollback:
        snapshot = (response.get("result") or {}).get("snapshot_before_rollback")
        if snapshot:
            return snapshot

    return last_backup


def _consume_batch_successes(
    remaining: List[Dict[str, object]],
    batch_reports: List[Dict[str, object]],
    last_backup: Optional[str],
) -> Optional[str]:
    """Remove successful batch items from remaining and advance backup marker."""
    for report in batch_reports:
        item = report.get("item")
        if not report.get("ok") or item not in remaining:
            continue
        remaining.remove(item)
        last_backup = _update_last_backup(last_backup, report.get("response") or {})
    return last_backup


def _append_and_consume_item_report(
    reports: List[Dict[str, object]],
    remaining: List[Dict[str, object]],
    *,
    item: Dict[str, object],
    response: Dict[str, object],
    fallback_error_code: str,
    fallback_message: str,
    last_backup: Optional[str],
    include_snapshot_before_rollback: bool = False,
) -> Optional[str]:
    if not _append_item_report(
        reports,
        item=item,
        response=response,
        fallback_error_code=fallback_error_code,
        fallback_message=fallback_message,
    ):
        return last_backup

    if item in remaining:
        remaining.remove(item)
    return _update_last_backup(
        last_backup,
        response,
        include_snapshot_before_rollback=include_snapshot_before_rollback,
    )


def _apply_batch_phase_reports(
    reports: List[Dict[str, object]],
    remaining: List[Dict[str, object]],
    *,
    phase_items: List[Dict[str, object]],
    run_batch: Callable[[], Tuple[bool, List[Dict[str, object]]]],
    last_backup: Optional[str],
) -> Optional[str]:
    if not phase_items:
        return last_backup
    _, batch_reports = run_batch()
    reports.extend(batch_reports)
    return _consume_batch_successes(remaining, batch_reports, last_backup)


def _run_mode_call(
    mode: str,
    *,
    run_preflight: Callable[[], Dict[str, object]],
    run_execute: Callable[[], Dict[str, object]],
) -> Dict[str, object]:
    if mode == "preflight":
        return run_preflight()
    return run_execute()


def _items_with_action(
    items: List[Dict[str, object]],
    action: str,
    *,
    case_insensitive: bool = False,
) -> List[Dict[str, object]]:
    if case_insensitive:
        target = str(action or "").lower()
        return [it for it in items if str(it.get("action") or "").lower() == target]
    return [it for it in items if it.get("action") == action]


def _build_preflight_blocked_result(
    items: List[Dict[str, object]],
    *,
    error_code: str,
    message: str,
    summary: str,
) -> Dict[str, object]:
    reports = [_make_error_item(it, error_code, message) for it in items]
    return {
        "ok": False,
        "blocked": True,
        "items": reports,
        "stats": {"total": len(items), "ok": 0, "blocked": len(reports)},
        "summary": summary,
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
        message = f"YAML file not found: {yaml_path}"
        return _build_preflight_blocked_result(
            items,
            error_code="yaml_not_found",
            message=message,
            summary=message,
        )

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _build_preflight_blocked_result(
            items,
            error_code="yaml_load_failed",
            message=str(exc),
            summary=f"Failed to load YAML: {exc}",
        )

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp_path = tmp.name

    try:
        write_yaml(data, tmp_path, auto_backup=False, audit_meta={"action": "preflight", "source": "plan_executor"})
    except Exception as exc:
        with suppress(Exception):
            os.unlink(tmp_path)
        return _build_preflight_blocked_result(
            items,
            error_code="preflight_snapshot_invalid",
            message=str(exc),
            summary=f"Preflight blocked before simulation: {exc}",
        )

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
        with suppress(Exception):
            os.unlink(tmp_path)


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

    rollback_items = _items_with_action(items, "rollback")
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
    rollbacks = _items_with_action(remaining, "rollback")
    for item in rollbacks:
        payload = dict(item.get("payload") or {})
        backup_path = payload.get("backup_path")
        source_event = payload.get("source_event")

        rollback_kwargs = {
            "yaml_path": yaml_path,
            "backup_path": backup_path,
            "execution_mode": "execute",
        }
        if isinstance(source_event, dict) and source_event:
            rollback_kwargs["source_event"] = source_event
        response = _run_mode_call(
            mode,
            run_preflight=lambda: _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_rollback",
                backup_path=backup_path,
                source_event=source_event,
            ),
            run_execute=lambda: bridge.rollback(**rollback_kwargs),
        )

        last_backup = _append_and_consume_item_report(
            reports,
            remaining,
            item=item,
            response=response,
            fallback_error_code="rollback_failed",
            fallback_message="Rollback failed",
            last_backup=last_backup,
            include_snapshot_before_rollback=True,
        )

    # Phase 1: add operations (each add is independent)
    adds = _items_with_action(remaining, "add")

    # Cross-item conflict detection: flag adds that target positions already
    # claimed by an earlier add in the same batch. Pure in-memory check:
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
            reports.append(_make_error_item(item, "position_conflict", "Position conflict (duplicate target in the same batch)"))
            continue

        payload = dict(item.get("payload") or {})
        response = _run_mode_call(
            mode,
            run_preflight=lambda: _preflight_add_entry(bridge, yaml_path, payload),
            run_execute=lambda: bridge.add_entry(yaml_path=yaml_path, execution_mode="execute", **payload),
        )

        last_backup = _append_and_consume_item_report(
            reports,
            remaining,
            item=item,
            response=response,
            fallback_error_code="add_failed",
            fallback_message="Add failed",
            last_backup=last_backup,
        )

    # Phase 1.5: edit operations (each edit is independent)
    edits = _items_with_action(remaining, "edit")
    for item in edits:
        payload = dict(item.get("payload") or {})
        response = _run_mode_call(
            mode,
            run_preflight=lambda: _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_edit_entry",
                record_id=payload.get("record_id"),
                fields=payload.get("fields", {}),
            ),
            run_execute=lambda: bridge.edit_entry(
                yaml_path=yaml_path,
                record_id=payload.get("record_id"),
                fields=payload.get("fields", {}),
                execution_mode="execute",
            ),
        )

        last_backup = _append_and_consume_item_report(
            reports,
            remaining,
            item=item,
            response=response,
            fallback_error_code="edit_failed",
            fallback_message="Edit failed",
            last_backup=last_backup,
        )

    # Phase 2: move operations (execute as a single batch)
    moves = _items_with_action(remaining, "move")
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=moves,
        run_batch=lambda: _execute_moves_batch(
            yaml_path=yaml_path,
            items=moves,
            bridge=bridge,
            date_str=effective_date,
            mode=mode,
        ),
        last_backup=last_backup,
    )

    # Phase 3: takeout operations
    out_items = _items_with_action(remaining, "takeout", case_insensitive=True)
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=out_items,
        run_batch=lambda: _execute_takeout_batch(
            yaml_path=yaml_path,
            items=out_items,
            action_name="Takeout",
            bridge=bridge,
            date_str=effective_date,
            mode=mode,
        ),
        last_backup=last_backup,
    )

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


def _preflight_batch_takeout(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate batch_takeout with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_batch_takeout",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
    )


def _preflight_batch_move(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate batch_move with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="tool_batch_move",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
    )


def _build_batch_takeout_payload(
    items: List[Dict[str, object]],
    *,
    date_str: str,
    include_target: bool = False,
) -> Dict[str, object]:
    """Build shared V2 batch payload for takeout/move operations."""
    entries = []
    for item in items:
        payload = item.get("payload") or {}
        source_box = item.get("box")
        source_position = payload.get("position")
        if include_target:
            target_box = payload.get("to_box")
            if target_box in (None, ""):
                target_box = source_box
            entry = {
                "record_id": payload.get("record_id"),
                "from": {"box": source_box, "position": source_position},
                "to": {"box": target_box, "position": payload.get("to_position")},
            }
        else:
            entry = {
                "record_id": payload.get("record_id"),
                "from": {"box": source_box, "position": source_position},
            }
        entries.append(entry)

    first_payload = (items[0].get("payload") or {}) if items else {}
    return {
        "entries": entries,
        "date_str": first_payload.get("date_str", date_str),
    }


def _run_batch_takeout(
    bridge: object,
    yaml_path: str,
    batch_payload: Dict[str, object],
    mode: str,
) -> Dict[str, object]:
    if mode == "preflight":
        return _preflight_batch_takeout(bridge, yaml_path, batch_payload)
    return bridge.batch_takeout(yaml_path=yaml_path, execution_mode="execute", **batch_payload)


def _run_batch_move(
    bridge: object,
    yaml_path: str,
    batch_payload: Dict[str, object],
    mode: str,
) -> Dict[str, object]:
    if mode == "preflight":
        return _preflight_batch_move(bridge, yaml_path, batch_payload)
    return bridge.batch_move(yaml_path=yaml_path, execution_mode="execute", **batch_payload)


def _execute_moves_batch(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: str,
    mode: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute move operations using a single batch strategy."""
    batch_payload = _build_batch_takeout_payload(
        items,
        date_str=date_str,
        include_target=True,
    )

    response = _run_batch_move(bridge, yaml_path, batch_payload, mode)

    return _fanout_batch_response(
        items,
        response,
        fallback_error_code="move_batch_failed",
        fallback_message="Move batch failed",
    )


def _execute_takeout_batch(
    yaml_path: str,
    items: List[Dict[str, object]],
    action_name: str,
    bridge: object,
    date_str: str,
    mode: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute takeout operations.

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
                "from_slot": {
                    "box": item.get("box"),
                    "position": p.get("position"),
                },
                "date_str": p.get("date_str", date_str),
            }
            response = _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="tool_record_takeout",
                **single_payload,
            )
            if not _append_item_report(
                reports,
                item=item,
                response=response,
                fallback_error_code="takeout_failed",
                fallback_message="Operation failed",
            ):
                all_ok = False
        return all_ok, reports

    batch_payload = _build_batch_takeout_payload(
        items,
        date_str=date_str,
        include_target=False,
    )

    response = _run_batch_takeout(bridge, yaml_path, batch_payload, mode="execute")

    return _fanout_batch_response(
        items,
        response,
        fallback_error_code="takeout_batch_failed",
        fallback_message="Batch operation failed",
    )

