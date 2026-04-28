"""Unified Plan execution engine with preflight validation."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from datetime import date
from typing import Dict, List, Optional

from app_gui.bridge_write_runner import (
    execute_bridge_rollback as _execute_bridge_rollback,
    execute_bridge_write as _execute_bridge_write,
)
from app_gui import plan_executor_actions as _plan_actions
from app_gui import plan_executor_cache as _plan_cache
from app_gui import plan_executor_layout as _plan_layout
from app_gui import plan_executor_phases as _plan_phases
from app_gui import plan_executor_reports as _plan_reports
from lib import tool_api_write_adapter as _write_adapter
from lib.bulk_operations import get_write_capability
from lib.diagnostics import span
from lib.yaml_ops import load_yaml

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
        data = _load_source_yaml_cached(yaml_path)
    except Exception as exc:
        return _build_preflight_blocked_result(
            items,
            error_code="yaml_load_failed",
            message=str(exc),
            summary=f"Failed to load YAML: {exc}",
        )

    tmp_dataset_dir, tmp_path = _allocate_preflight_yaml_path(yaml_path)

    try:
        from pathlib import Path
        from copy import deepcopy

        Path(tmp_path).touch()  # marker for os.path.isfile/exists checks

        # Seed the source-level cache in yaml_ops
        from lib.yaml_ops import _preflight_cache
        cache_key = os.path.normcase(os.path.normpath(os.path.abspath(tmp_path)))
        _preflight_cache[cache_key] = deepcopy(data)

        try:
            with span("plan.preflight", yaml_path=yaml_path, batch_size=len(items)):
                result = run_plan(
                    yaml_path=tmp_path,
                    items=items,
                    bridge=bridge,
                    date_str=date_str,
                    mode="preflight",
                )
            return result
        finally:
            _preflight_cache.pop(cache_key, None)
    finally:
        with suppress(Exception):
            shutil.rmtree(tmp_dataset_dir)


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
    request_backup_path: Optional[str] = None

    if mode == "execute":
        try:
            _, request_backup_path = _write_adapter.prepare_write_tool_kwargs(
                yaml_path=yaml_path,
                execution_mode="execute",
                dry_run=False,
                request_backup_path=None,
                backup_event_source="plan_executor.execute",
            )
        except Exception as exc:
            if os.path.isfile(yaml_path):
                return _build_execute_backup_blocked_result(
                    items,
                    message=f"Blocked before execute: failed to create backup ({exc})",
                )
            # In-memory/test execution may run with a virtual path. Let tool-level
            # validation report the concrete failure instead of hard-blocking here.
            request_backup_path = None

    # Seed write-through cache for execute mode to avoid redundant disk reads
    _wt_cache_key = None
    if mode == "execute":
        from lib.yaml_ops import _write_through_cache
        from copy import deepcopy
        _wt_cache_key = os.path.normcase(os.path.normpath(os.path.abspath(yaml_path)))
        try:
            _write_through_cache[_wt_cache_key] = deepcopy(load_yaml(yaml_path))
        except Exception:
            _wt_cache_key = None

    remaining = list(items)

    # Phase 0: rollback (must be executed alone, enforced above)
    rollbacks = _items_with_action(remaining, "rollback")
    for item in rollbacks:
        payload = dict(item.get("payload") or {})
        target_backup_path = payload.get("backup_path")
        source_event = payload.get("source_event")

        rollback_kwargs = {
            "yaml_path": yaml_path,
            "backup_path": target_backup_path,
            "execution_mode": "execute",
            "request_backup_path": request_backup_path,
        }
        if isinstance(source_event, dict) and source_event:
            rollback_kwargs["source_event"] = source_event
        response = _run_mode_call(
            mode,
            run_preflight=lambda: _run_preflight_tool(
                bridge=bridge,
                yaml_path=yaml_path,
                tool_name="rollback",
                backup_path=target_backup_path,
                source_event=source_event,
            ),
            run_execute=lambda: _execute_bridge_rollback(bridge, **rollback_kwargs),
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

    # Phase 1: add operations
    adds = _items_with_action(remaining, "add")
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=adds,
        run_batch=lambda: _run_bulk_plan_phase(
            "add",
            adds,
            mode,
            lambda: _execute_batch_add(
                yaml_path=yaml_path,
                items=adds,
                bridge=bridge,
                mode=mode,
                request_backup_path=request_backup_path,
            ),
        ),
        last_backup=last_backup,
    )

    # Phase 1.5: edit operations
    edits = _items_with_action(remaining, "edit")
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=edits,
        run_batch=lambda: _run_bulk_plan_phase(
            "edit",
            edits,
            mode,
            lambda: _execute_batch_edit(
                yaml_path=yaml_path,
                items=edits,
                bridge=bridge,
                mode=mode,
                request_backup_path=request_backup_path,
            ),
        ),
        last_backup=last_backup,
    )

    # Phase 2: move operations (execute as a single batch)
    moves = _items_with_action(remaining, "move")
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=moves,
        run_batch=lambda: _run_bulk_plan_phase(
            "move",
            moves,
            mode,
            lambda: _execute_move(
                yaml_path=yaml_path,
                items=moves,
                bridge=bridge,
                date_str=effective_date,
                mode=mode,
                request_backup_path=request_backup_path,
            ),
        ),
        last_backup=last_backup,
    )

    # Phase 3: takeout operations
    out_items = _items_with_action(remaining, "takeout", case_insensitive=True)
    last_backup = _apply_batch_phase_reports(
        reports,
        remaining,
        phase_items=out_items,
        run_batch=lambda: _run_bulk_plan_phase(
            "takeout",
            out_items,
            mode,
            lambda: _execute_takeout(
                yaml_path=yaml_path,
                items=out_items,
                action_name="Takeout",
                bridge=bridge,
                date_str=effective_date,
                mode=mode,
                request_backup_path=request_backup_path,
            ),
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

    if mode == "execute":
        undo_backup = request_backup_path or _first_success_backup_path(reports) or last_backup
    else:
        undo_backup = _first_success_backup_path(reports) or last_backup

    return {
        "ok": not has_blocked,
        "blocked": has_blocked,
        "items": reports,
        "stats": {"total": len(reports), "ok": ok_count, "blocked": blocked_count, "remaining": len(remaining)},
        "summary": summary,
        "backup_path": undo_backup,
        "remaining_items": remaining,
    }


def _run_bulk_plan_phase(action: str, phase_items: List[Dict[str, object]], mode: str, fn):
    capability = get_write_capability(action)
    tool_name = capability.tool_name if capability is not None else action
    with span(
        "plan.execute",
        action=action,
        tool_name=tool_name,
        mode=mode,
        batch_size=len(phase_items or []),
    ):
        return fn()

_source_yaml_cache = _plan_cache._source_yaml_cache
clear_write_through_cache = _plan_cache.clear_write_through_cache
_load_source_yaml_cached = _plan_cache._load_source_yaml_cached
_allocate_preflight_yaml_path = _plan_cache._allocate_preflight_yaml_path

_make_error_item = _plan_reports._make_error_item
_make_ok_item = _plan_reports._make_ok_item
_resolve_error_from_response = _plan_reports._resolve_error_from_response
_as_int = _plan_reports._as_int
_normalize_batch_item_key = _plan_reports._normalize_batch_item_key
_batch_item_key_from_plan_item = _plan_reports._batch_item_key_from_plan_item
_batch_item_key_from_error_item = _plan_reports._batch_item_key_from_error_item
_extract_record_id_from_text = _plan_reports._extract_record_id_from_text
_extract_batch_error_maps = _plan_reports._extract_batch_error_maps
_make_error_item_from_response = _plan_reports._make_error_item_from_response
_fanout_batch_response = _plan_reports._fanout_batch_response
_append_item_report = _plan_reports._append_item_report
_update_last_backup = _plan_reports._update_last_backup
_consume_batch_successes = _plan_reports._consume_batch_successes
_first_success_backup_path = _plan_reports._first_success_backup_path
_append_and_consume_item_report = _plan_reports._append_and_consume_item_report
_batch_ok_reports = _plan_reports._batch_ok_reports

_load_box_layout = _plan_layout._load_box_layout
_to_tool_position = _plan_layout._to_tool_position
_to_tool_positions = _plan_layout._to_tool_positions
_build_add_tool_payload = _plan_layout._build_add_tool_payload
_build_takeout_payload = _plan_layout._build_takeout_payload

_run_mode_call = _plan_phases._run_mode_call
_items_with_action = _plan_phases._items_with_action
_build_preflight_blocked_result = _plan_phases._build_preflight_blocked_result
_build_execute_backup_blocked_result = _plan_phases._build_execute_backup_blocked_result
_apply_batch_phase_reports = _plan_phases._apply_batch_phase_reports

_run_preflight_tool = _plan_actions._run_preflight_tool
_preflight_add_entry = _plan_actions._preflight_add_entry
_preflight_takeout = _plan_actions._preflight_takeout
_preflight_move = _plan_actions._preflight_move
_run_takeout = _plan_actions._run_takeout
_run_move = _plan_actions._run_move
_execute_move = _plan_actions._execute_move
_execute_takeout = _plan_actions._execute_takeout
_execute_batch_add = _plan_actions._execute_batch_add
_execute_batch_edit = _plan_actions._execute_batch_edit

