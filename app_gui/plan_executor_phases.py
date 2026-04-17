from __future__ import annotations

from typing import Callable, Dict, List, Optional

from app_gui.plan_executor_reports import consume_batch_successes, make_error_item


def apply_batch_phase_reports(
    reports: List[Dict[str, object]],
    remaining: List[Dict[str, object]],
    *,
    phase_items: List[Dict[str, object]],
    run_batch: Callable[[], tuple[bool, List[Dict[str, object]]]],
    last_backup: Optional[str],
) -> Optional[str]:
    if not phase_items:
        return last_backup
    _, batch_reports = run_batch()
    reports.extend(batch_reports)
    return consume_batch_successes(remaining, batch_reports, last_backup)


def run_mode_call(
    mode: str,
    *,
    run_preflight: Callable[[], Dict[str, object]],
    run_execute: Callable[[], Dict[str, object]],
) -> Dict[str, object]:
    if mode == "preflight":
        return run_preflight()
    return run_execute()


def items_with_action(
    items: List[Dict[str, object]],
    action: str,
    *,
    case_insensitive: bool = False,
) -> List[Dict[str, object]]:
    if case_insensitive:
        target = str(action or "").lower()
        return [it for it in items if str(it.get("action") or "").lower() == target]
    return [it for it in items if it.get("action") == action]


def build_preflight_blocked_result(
    items: List[Dict[str, object]],
    *,
    error_code: str,
    message: str,
    summary: str,
) -> Dict[str, object]:
    reports = [make_error_item(it, error_code, message) for it in items]
    return {
        "ok": False,
        "blocked": True,
        "items": reports,
        "stats": {"total": len(items), "ok": 0, "blocked": len(reports)},
        "summary": summary,
    }


def build_execute_backup_blocked_result(
    items: List[Dict[str, object]],
    *,
    message: str,
) -> Dict[str, object]:
    reports = [make_error_item(it, "backup_create_failed", message) for it in items]
    return {
        "ok": False,
        "blocked": True,
        "items": reports,
        "stats": {"total": len(items), "ok": 0, "blocked": len(reports), "remaining": len(items)},
        "summary": message,
        "backup_path": None,
        "remaining_items": list(items),
    }


_apply_batch_phase_reports = apply_batch_phase_reports
_run_mode_call = run_mode_call
_items_with_action = items_with_action
_build_preflight_blocked_result = build_preflight_blocked_result
_build_execute_backup_blocked_result = build_execute_backup_blocked_result
