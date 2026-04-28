"""Plan execution helpers for OperationsPanel."""

import os
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from app_gui.application import PlanRunUseCase
from app_gui.bridge_write_runner import execute_bridge_rollback
from app_gui.i18n import tr
from app_gui.error_localizer import localize_error_payload
from app_gui.system_notice import build_system_notice, coerce_system_notice
from app_gui.ui.plan_item_desc import build_localized_plan_item_desc
from lib.position_fmt import format_box_position_display


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


class _PlanExecutionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, run_use_case, yaml_path, plan_items, bridge):
        super().__init__()
        self._run_use_case = run_use_case
        self._yaml_path = yaml_path
        self._plan_items = list(plan_items or [])
        self._bridge = bridge

    @Slot()
    def run(self):
        try:
            run_result = self._run_use_case.execute(
                yaml_path=self._yaml_path,
                plan_items=self._plan_items,
                bridge=self._bridge,
                mode="execute",
            )
            self.finished.emit(
                {
                    "report": run_result.report,
                    "results": list(run_result.results or []),
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            from app_gui.plan_executor import clear_write_through_cache

            clear_write_through_cache()


class _PlanExecutionResultReceiver(QObject):
    def __init__(self, *, panel, thread, worker, original_plan, yaml_path):
        super().__init__(panel)
        self._panel = panel
        self._thread = thread
        self._worker = worker
        self._original_plan = list(original_plan or [])
        self._yaml_path = yaml_path
        self._handled = False

    def _begin_result_handling(self):
        if self._handled:
            return False
        self._handled = True
        self._panel._plan_execution_running = False
        return True

    @Slot(object)
    def on_finished(self, payload):
        if not self._begin_result_handling():
            return
        report = payload.get("report") if isinstance(payload, dict) else {}
        results = payload.get("results") if isinstance(payload, dict) else []
        _finish_execute_plan(
            self._panel,
            report=report if isinstance(report, dict) else {},
            results=list(results or []),
            original_plan=self._original_plan,
            yaml_path=self._yaml_path,
        )

    @Slot(str)
    def on_failed(self, message):
        if not self._begin_result_handling():
            return
        from app_gui.ui import operations_panel_forms as _ops_forms
        from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

        text = str(message or "Plan execution failed")
        _ops_forms._set_plan_feedback(self._panel, text, level="error")
        _publish_system_notice(
            self._panel,
            code="plan.execute.worker_failed",
            text=text,
            level="error",
            timeout=5000,
        )
        _ops_plan_toolbar._refresh_after_plan_items_changed(self._panel)

    @Slot()
    def on_thread_finished(self):
        panel = self._panel
        if getattr(panel, "_plan_execution_thread", None) is self._thread:
            panel._plan_execution_thread = None
        if getattr(panel, "_plan_execution_worker", None) is self._worker:
            panel._plan_execution_worker = None
        if getattr(panel, "_plan_execution_receiver", None) is self:
            panel._plan_execution_receiver = None
        self._thread = None
        self._worker = None
        self.deleteLater()


def _summarize_execution(panel, report, rollback_info):
    use_case = _resolve_plan_run_use_case(panel)
    summarize_fn = getattr(use_case, "summarize", None)
    if callable(summarize_fn):
        return summarize_fn(report=report, rollback_info=rollback_info)
    return {}


def _format_box_position(panel, box, position):
    return format_box_position_display(
        box,
        position,
        layout=panel._current_layout,
        box_label=tr("operations.box", default="Box"),
        position_label=tr("operations.position", default="Position"),
    )


def execute_plan(self):
    """Execute all staged plan items after user confirmation."""
    from app_gui.ui import operations_panel_actions as _ops_actions
    from app_gui.ui import operations_panel_forms as _ops_forms
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
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
    if bool(getattr(self, "_execute_plan_in_worker", False)):
        _start_execute_plan_worker(
            self,
            yaml_path=yaml_path,
            plan_items=plan_items,
            original_plan=original_plan,
        )
        return

    try:
        run_use_case = _resolve_plan_run_use_case(self)
        run_result = run_use_case.execute(
            yaml_path=yaml_path,
            plan_items=plan_items,
            bridge=self.bridge,
            mode="execute",
        )
        _finish_execute_plan(
            self,
            report=run_result.report,
            results=list(run_result.results or []),
            original_plan=original_plan,
            yaml_path=yaml_path,
        )
    finally:
        from app_gui.plan_executor import clear_write_through_cache
        clear_write_through_cache()


def _start_execute_plan_worker(self, *, yaml_path, plan_items, original_plan):
    from app_gui.ui import operations_panel_forms as _ops_forms

    if bool(getattr(self, "_plan_execution_running", False)):
        return

    self._plan_execution_running = True
    self.plan_exec_btn.setEnabled(False)
    self.plan_exec_btn.setText(tr("operations.planExecuting", default="Executing..."))
    _ops_forms._set_plan_feedback(self, tr("operations.planExecuting", default="Executing..."), level="info")

    thread = QThread(self)
    worker = _PlanExecutionWorker(
        run_use_case=_resolve_plan_run_use_case(self),
        yaml_path=yaml_path,
        plan_items=plan_items,
        bridge=self.bridge,
    )
    worker.moveToThread(thread)
    receiver = _PlanExecutionResultReceiver(
        panel=self,
        thread=thread,
        worker=worker,
        original_plan=original_plan,
        yaml_path=yaml_path,
    )
    self._plan_execution_thread = thread
    self._plan_execution_worker = worker
    self._plan_execution_receiver = receiver

    thread.started.connect(worker.run)
    worker.finished.connect(receiver.on_finished, Qt.ConnectionType.QueuedConnection)
    worker.failed.connect(receiver.on_failed, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(receiver.on_thread_finished, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(thread.deleteLater)
    thread.start()


def _finish_execute_plan(self, *, report, results, original_plan, yaml_path):
    from app_gui.ui import operations_panel_actions as _ops_actions
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

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

def _build_execute_confirmation_lines(self, plan_items, yaml_path):
    from app_gui.ui import operations_panel_confirm as _ops_confirm

    lines = []
    for item in plan_items:
        action = item.get("action", "?")
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

        lines.append(f"  {build_localized_plan_item_desc(self, item)}")
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

    try:
        payload = execute_bridge_rollback(
            self.bridge,
            yaml_path=yaml_path,
            backup_path=first_backup,
            execution_mode="execute",
            request_backup_path=first_backup,
        )
    except Exception as exc:
        return _build_rollback_outcome(
            attempted=True,
            ok=False,
            message=tr("operations.rollbackException", error=exc),
            backup_path=first_backup,
        )

    if str(payload.get("error_code") or "") == "bridge_no_rollback":
        return _build_rollback_outcome(
            attempted=False,
            ok=False,
            message=tr("operations.bridgeNoRollback"),
            backup_path=first_backup,
        )

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
        fail_info = fail_item[2] if isinstance(fail_item[2], dict) else {}
        error_msg = fail_info.get("message", "Unknown error")
        errors_detail = fail_info.get("errors_detail")
        if isinstance(errors_detail, list) and errors_detail:
            self._last_validation_errors_detail = [
                d for d in errors_detail if isinstance(d, dict)
            ]
            self._last_validation_summary = str(error_msg or "")
        else:
            self._last_validation_errors_detail = None
            self._last_validation_summary = ""
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
        self._last_validation_errors_detail = None
        self._last_validation_summary = ""
        lines = [
            f"<b style='color: var(--status-success);'>{tr('operations.planExecutionSuccess')}</b>",
            tr("operations.planExecutionSuccessSummary", applied=applied_count, total=applied_count),
        ]
        self._show_result_card(lines, "success")
    self._sync_result_actions()
