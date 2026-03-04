"""Plan execution helpers for OperationsPanel."""

import os
from datetime import datetime

from app_gui.application import PlanRunUseCase
from app_gui.i18n import tr
from app_gui.error_localizer import localize_error_payload
from app_gui.system_notice import build_system_notice, coerce_system_notice


def _build_rollback_outcome(
    *,
    attempted,
    ok,
    message,
    backup_path=None,
    error_code=None,
):
    payload = {
        "attempted": bool(attempted),
        "ok": bool(ok),
        "message": str(message or ""),
    }
    if backup_path:
        payload["backup_path"] = backup_path
    if error_code:
        payload["error_code"] = error_code
    return payload


def _execution_failure_level(execution_stats):
    return "warning" if execution_stats.get("rollback_ok") else "error"


def _resolve_execution_rollback_state(execution_stats):
    if execution_stats.get("rollback_ok"):
        return "applied", ""
    rollback_reason = str(execution_stats.get("rollback_message", "") or "")
    if execution_stats.get("rollback_attempted"):
        return "failed", rollback_reason
    if rollback_reason:
        return "unavailable", rollback_reason
    return "none", ""


def _is_undo_eligible_item(item):
    action = str((item or {}).get("action") or "").lower()
    return action != "rollback"


def _resolve_plan_run_use_case(panel):
    use_case = getattr(panel, "_plan_run_use_case", None)
    if use_case is not None:
        return use_case
    return PlanRunUseCase()


def _summarize_execution(panel, report, rollback_info):
    use_case = _resolve_plan_run_use_case(panel)
    summarize_fn = getattr(use_case, "summarize", None)
    if callable(summarize_fn):
        return summarize_fn(report=report, rollback_info=rollback_info)
    return {}


def execute_plan(self):
    """Execute all staged plan items after user confirmation."""
    from app_gui.ui import operations_panel_actions as _ops_actions
    from app_gui.ui import operations_panel_forms as _ops_forms
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    if bool(getattr(self, "_guard_migration_write_action", lambda: False)()):
        return
    if not self._plan_store.count():
        msg = tr("operations.planNoItemsToExecute")
        _ops_forms._set_plan_feedback(self, msg, level="warning")
        _publish_system_notice(
            self,
            code="plan.execute.empty",
            text=msg,
            level="error",
            timeout=3000,
            data={"total_count": 0},
        )
        return

    plan_items = self._plan_store.list_items()
    yaml_path = os.path.abspath(str(self.yaml_path_getter()))
    summary_lines = _build_execute_confirmation_lines(self, plan_items, yaml_path)
    if not _confirm_execute_plan(self, plan_items, summary_lines):
        return

    original_plan = list(plan_items)
    try:
        run_use_case = _resolve_plan_run_use_case(self)
        run_result = run_use_case.execute(
            yaml_path=yaml_path,
            plan_items=plan_items,
            bridge=self.bridge,
            mode="execute",
        )
        report = run_result.report
        results = list(run_result.results or [])
        _, rollback_info, fail_count = _finalize_plan_store_after_execution(
            self,
            report=report,
            results=results,
            original_plan=original_plan,
            yaml_path=yaml_path,
        )

        from app_gui.ui import operations_panel_plan_store as _ops_plan_store

        _ops_plan_store._run_plan_preflight(self, trigger="post_execute")
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)
        execution_stats = _summarize_execution(self, report, rollback_info)
        _show_plan_result(
            self,
            results,
            report=report,
            rollback_info=rollback_info,
            execution_stats=execution_stats,
        )

        executed_items = [r[1] for r in results if r[0] == "OK"]
        if execution_stats.get("rollback_ok"):
            executed_items = []
        self._last_executed_plan = list(executed_items)
        self._last_executed_print_snapshot = _ops_actions._capture_last_executed_print_snapshot(
            self,
            executed_items,
        )

        if report.get("ok") and any(r[0] == "OK" for r in results):
            self.operation_completed.emit(True)
        elif fail_count:
            self.operation_completed.emit(False)

        last_backup = report.get("backup_path")
        undo_eligible_items = [it for it in executed_items if _is_undo_eligible_item(it)]
        if last_backup and undo_eligible_items:
            self._last_operation_backup = last_backup
            _ops_actions._enable_undo(self, timeout_sec=30)
        else:
            _ops_actions._disable_undo(self, clear_last_executed=not bool(executed_items))

        summary_text = _build_execution_summary_text(self, execution_stats)
        notice_level = "success"
        if execution_stats.get("fail_count", 0) > 0:
            notice_level = _execution_failure_level(execution_stats)
        base_stats = report.get("stats") if isinstance(report.get("stats"), dict) else {}
        stats_payload = dict(base_stats) if isinstance(base_stats, dict) else {}
        stats_payload["applied"] = execution_stats.get("applied_count", 0)
        stats_payload["failed"] = execution_stats.get("fail_count", 0)
        stats_payload["rolled_back"] = bool(execution_stats.get("rollback_ok"))
        result_sample = _build_execution_result_sample(self, results)
        _publish_system_notice(
            self,
            code="plan.execute.result",
            text=summary_text,
            level=notice_level,
            timeout=5000,
            details=summary_text,
            data={
                "ok": bool(report.get("ok")),
                "stats": stats_payload,
                "report": report,
                "rollback": rollback_info,
                "sample": result_sample,
            },
        )
    finally:
        from app_gui.plan_executor import clear_write_through_cache
        clear_write_through_cache()

def _build_execute_confirmation_lines(self, plan_items, yaml_path):
    from app_gui.ui import operations_panel_confirm as _ops_confirm

    lines = []
    for item in plan_items:
        action = item.get("action", "?")
        label = item.get("label", "?")
        pos = item.get("position", "?")
        if str(action).lower() == "rollback":
            payload = item.get("payload") or {}
            lines.extend(
                _ops_confirm._build_rollback_confirmation_lines(
                    self,
                    backup_path=payload.get("backup_path"),
                    yaml_path=yaml_path,
                    source_event=payload.get("source_event"),
                    include_action_prefix=True,
                )
            )
            continue

        line = f"  {action}: {label} @ Box {item.get('box', '?')}:{self._position_to_display(pos)}"
        to_pos = item.get("to_position")
        to_box = item.get("to_box")
        if to_pos:
            if to_box:
                line += f" \u2192 Box {to_box}:{self._position_to_display(to_pos)}"
            else:
                line += f" \u2192 {self._position_to_display(to_pos)}"
        lines.append(line)
    return lines

def _confirm_execute_plan(self, plan_items, summary_lines):
    from app_gui.ui import operations_panel_confirm as _ops_confirm

    detailed_text = "\n".join(summary_lines) if len(summary_lines) > 20 else None
    return _ops_confirm._confirm_warning_dialog(
        self,
        title=tr("operations.executePlanTitle"),
        text=tr("operations.executePlanConfirm", count=len(plan_items)),
        informative_text="\n".join(summary_lines[:20]),
        detailed_text=detailed_text,
    )

def _finalize_plan_store_after_execution(self, report, results, original_plan, yaml_path):
    remaining = report.get("remaining_items") if isinstance(report.get("remaining_items"), list) else []
    fail_count = sum(1 for status, _, _ in results if status == "FAIL")
    rollback_info = None

    if fail_count:
        rollback_info = _attempt_atomic_rollback(self, yaml_path, results, report=report)
        self._plan_store.replace_all(original_plan)
    elif remaining:
        self._plan_store.replace_all(remaining)
    else:
        self._plan_store.clear()

    return remaining, rollback_info, fail_count

def _build_execution_result_sample(self, results):
    from app_gui.ui import operations_panel_plan_store as _ops_plan_store

    sample = []
    for status, plan_item, info in results:
        if not isinstance(plan_item, dict):
            continue
        line = f"{status}: {_ops_plan_store._build_notice_plan_item_desc(self, plan_item)}"
        if status != "OK" and isinstance(info, dict):
            msg = localize_error_payload(info)
            if msg:
                line += f" | {str(msg)}"
        sample.append(line)
        if len(sample) >= 8:
            break
    return sample

def _attempt_atomic_rollback(self, yaml_path, results, report=None):
    """Best-effort rollback to the first backup of this execute run."""
    has_success = any(status == "OK" for status, _item, _info in results)
    if not has_success:
        return _build_rollback_outcome(
            attempted=False,
            ok=False,
            message=tr("operations.noRollbackBackup"),
        )

    first_backup = None
    if isinstance(report, dict):
        first_backup = str(report.get("backup_path") or "").strip() or None
    if not first_backup:
        for status, _item, info in results:
            if status != "OK" or not isinstance(info, dict):
                continue
            backup_path = info.get("backup_path")
            if backup_path:
                first_backup = backup_path
                break

    if not first_backup:
        return _build_rollback_outcome(
            attempted=False,
            ok=False,
            message=tr("operations.noRollbackBackup"),
        )

    rollback_fn = getattr(self.bridge, "rollback", None)
    if not callable(rollback_fn):
        return _build_rollback_outcome(
            attempted=False,
            ok=False,
            message=tr("operations.bridgeNoRollback"),
            backup_path=first_backup,
        )

    try:
        try:
            response = rollback_fn(
                yaml_path=yaml_path,
                backup_path=first_backup,
                execution_mode="execute",
                request_backup_path=first_backup,
            )
        except TypeError:
            # Backward-compatible path for test doubles that do not accept
            # request_backup_path yet.
            response = rollback_fn(
                yaml_path=yaml_path,
                backup_path=first_backup,
                execution_mode="execute",
            )
    except Exception as exc:
        return _build_rollback_outcome(
            attempted=True,
            ok=False,
            message=tr("operations.rollbackException", error=exc),
            backup_path=first_backup,
        )

    payload = response if isinstance(response, dict) else {}
    if payload.get("ok"):
        return _build_rollback_outcome(
            attempted=True,
            ok=True,
            message=tr("operations.executionRolledBack"),
            backup_path=first_backup,
        )

    return _build_rollback_outcome(
        attempted=True,
        ok=False,
        message=payload.get("message", tr("operations.rollbackUnknown")),
        backup_path=first_backup,
        error_code=payload.get("error_code"),
    )

def _emit_operation_event(self, event):
    """Emit a normalized operation event for AI panel/context consumers."""
    payload = coerce_system_notice(event) if isinstance(event, dict) else None
    if payload is None:
        payload = dict(event) if isinstance(event, dict) else {}
    payload["timestamp"] = payload.get("timestamp") or datetime.now().isoformat()
    self.operation_event.emit(payload)

def _publish_system_notice(
    self,
    *,
    code,
    text,
    level="info",
    timeout=2000,
    details=None,
    data=None,
    source="operations_panel",
):
    """Single-path publisher for user-facing status + AI-visible system notice."""
    message = str(text or "")
    self.status_message.emit(message, int(timeout), str(level))
    notice = build_system_notice(
        code=str(code or "notice"),
        text=message,
        level=str(level or "info"),
        source=str(source or "operations_panel"),
        timeout_ms=int(timeout),
        details=str(details) if details else None,
        data=data if isinstance(data, dict) else None,
    )
    _emit_operation_event(self, notice)
    return notice

def emit_external_operation_event(self, event):
    """Public helper for non-plan modules to emit operation events."""
    if not isinstance(event, dict):
        return
    _emit_operation_event(self, dict(event))

def _build_execution_summary_text(self, execution_stats):
    """Build a user-facing summary for execution event payloads."""
    if execution_stats.get("fail_count", 0) <= 0:
        applied = execution_stats.get("applied_count", 0)
        total = execution_stats.get("total_count", 0)
        return tr("operations.planExecutionSuccessSummary", applied=applied, total=total)

    total = execution_stats.get("total_count", 0)
    fail = execution_stats.get("fail_count", 0)
    applied = execution_stats.get("applied_count", 0)
    rollback_state, rollback_reason = _resolve_execution_rollback_state(execution_stats)
    if rollback_state == "applied":
        return tr("operations.planExecutionAtomicRollback", fail=fail, total=total)

    if rollback_state == "failed":
        suffix = tr("operations.rollbackFailedSuffix", reason=rollback_reason) if rollback_reason else ""
    elif rollback_state == "unavailable":
        suffix = tr("operations.rollbackUnavailableSuffix", reason=rollback_reason)
    else:
        suffix = ""
    return tr(
        "operations.planExecutionFailedSummary",
        fail=fail,
        total=total,
        applied=applied,
        suffix=suffix,
    )

def _build_execution_rollback_notice(self, execution_stats, rollback_info):
    if not (isinstance(rollback_info, dict) and rollback_info):
        return ""
    rollback_state, rollback_reason = _resolve_execution_rollback_state(execution_stats)
    if rollback_state == "applied":
        return (
            f"<span style='color: var(--status-success);'>"
            f"{tr('operations.planExecutionRollbackApplied')}</span>"
        )
    if rollback_state == "failed":
        reason = rollback_reason or str(rollback_info.get("message") or "unknown error")
        return (
            f"<span style='color: var(--status-error);'>"
            f"{tr('operations.planExecutionRollbackFailed', reason=reason)}</span>"
        )
    if rollback_state == "unavailable":
        return (
            f"<span style='color: var(--status-warning);'>"
            f"{tr('operations.planExecutionRollbackUnavailable', reason=rollback_reason)}</span>"
        )
    return ""

def _build_execution_failure_lines(
    self,
    *,
    execution_stats,
    ok_count,
    fail_count,
    applied_count,
    error_msg,
    rollback_info,
):
    title_color = _execution_failure_level(execution_stats)
    title_key = "operations.planExecutionRolledBack" if title_color == "warning" else "operations.planExecutionStopped"
    lines = [
        f"<b style='color: var(--status-{title_color});'>{tr(title_key)}</b>",
        tr(
            "operations.planExecutionStats",
            attempted_ok=ok_count,
            failed=fail_count,
            applied=applied_count,
        ),
        tr("operations.planExecutionError", error=error_msg),
        f"<span style='color: var(--status-muted);'>{tr('operations.planExecutionRetry')}</span>",
    ]
    rollback_notice = _build_execution_rollback_notice(self, execution_stats, rollback_info)
    if rollback_notice:
        lines.append(rollback_notice)
    return lines

def _show_plan_result(self, results, report=None, rollback_info=None, execution_stats=None):
    if not isinstance(execution_stats, dict):
        execution_stats = _summarize_execution(self, report, rollback_info)
    ok_count = execution_stats.get("ok_count", sum(1 for r in results if r[0] == "OK"))
    fail_count = execution_stats.get("fail_count", sum(1 for r in results if r[0] == "FAIL"))
    applied_count = execution_stats.get("applied_count", ok_count)

    if fail_count:
        fail_item = [r for r in results if r[0] == "FAIL"][-1]
        error_msg = fail_item[2].get("message", "Unknown error")
        lines = _build_execution_failure_lines(
            self,
            execution_stats=execution_stats,
            ok_count=ok_count,
            fail_count=fail_count,
            applied_count=applied_count,
            error_msg=error_msg,
            rollback_info=rollback_info,
        )
        self._show_result_card(lines, _execution_failure_level(execution_stats))
    else:
        lines = [
            f"<b style='color: var(--status-success);'>{tr('operations.planExecutionSuccess')}</b>",
            tr("operations.planExecutionSuccessSummary", applied=applied_count, total=applied_count),
        ]
        self._show_result_card(lines, "success")
    self._sync_result_actions()
