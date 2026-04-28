"""Plan-store and preflight helpers for OperationsPanel."""

import os

from app_gui.error_localizer import localize_error_payload
from app_gui.plan_executor import preflight_plan
from app_gui.ui.plan_item_desc import build_localized_plan_item_desc
from lib.plan_gate import validate_stage_request
from lib.plan_store import (
    PLAN_VALIDATION_STATUS_INVALID,
    PLAN_VALIDATION_STATUS_PENDING,
    PLAN_VALIDATION_STATUS_VALIDATING,
    PlanStore,
)


def _tr(key, **kwargs):
    # Keep tests and monkeypatch points stable on operations_panel.tr.
    from app_gui.ui import operations_panel as _ops_panel

    return _ops_panel.tr(key, **kwargs)


def _plan_item_key(self, item):
    return (
        item.get("action"),
        item.get("record_id"),
        item.get("box"),
        item.get("position"),
    )


def _build_notice_plan_item_desc(self, item):
    return build_localized_plan_item_desc(self, item)


def _collect_notice_action_counts_and_sample(self, items, max_sample=8):
    action_counts = {}
    sample = []
    for item in items or []:
        action = str(item.get("action", "") or "").lower()
        action_counts[action] = action_counts.get(action, 0) + 1
        if len(sample) < max_sample:
            sample.append(_build_notice_plan_item_desc(self, item))
    return action_counts, sample


def _collect_plan_notice_summary(self, items, max_sample=8):
    action_counts, sample = _collect_notice_action_counts_and_sample(self, items, max_sample=max_sample)
    details = "\n".join(sample[:max_sample]) if sample else None
    return {
        "action_counts": action_counts,
        "sample": sample,
        "details": details,
    }


def _publish_plan_items_notice(
    self,
    *,
    code,
    text,
    level,
    timeout,
    items,
    count_key,
    count_value,
    include_total_count=False,
    extra_data=None,
):
    from app_gui.ui import operations_panel_execution as _ops_exec

    summary = _collect_plan_notice_summary(self, items)
    data = {
        count_key: count_value,
        "action_counts": summary["action_counts"],
        "sample": summary["sample"],
    }
    if include_total_count:
        data["total_count"] = self._plan_store.count()
    if isinstance(extra_data, dict) and extra_data:
        data.update(extra_data)
    _ops_exec._publish_system_notice(
        self,
        code=code,
        text=text,
        level=level,
        timeout=timeout,
        details=summary["details"],
        data=data,
    )


def _apply_preflight_report(self, report):
    """Normalize and cache preflight report + per-item validation map."""
    self._plan_preflight_report = report if isinstance(report, dict) else None
    self._plan_validation_by_key = {}
    if not isinstance(self._plan_preflight_report, dict):
        return
    for report_item in self._plan_preflight_report.get("items") or []:
        item = report_item.get("item") if isinstance(report_item, dict) else None
        if not isinstance(item, dict):
            continue
        self._plan_validation_by_key[_plan_item_key(self, item)] = {
            "ok": report_item.get("ok"),
            "blocked": report_item.get("blocked"),
            "error_code": report_item.get("error_code"),
            "message": report_item.get("message"),
        }


def _reset_plan_feedback_and_validation(self):
    """Clear transient plan feedback + validation cache."""
    from app_gui.ui import operations_panel_forms as _ops_forms

    _ops_forms._set_plan_feedback(self, "")
    _apply_preflight_report(self, None)


def _refresh_current_plan_validation(self, trigger="manual"):
    """Re-sync cached preflight/validation state to the current staged plan."""
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar

    _run_plan_preflight(self, trigger=trigger)
    _ops_plan_toolbar._refresh_after_plan_items_changed(self)


def _is_rollback_replace_request(items):
    incoming = list(items or [])
    if len(incoming) != 1:
        return False
    action = str((incoming[0] or {}).get("action") or "").strip().lower()
    return action == "rollback"


def add_plan_items(self, items):
    """Validate and add items to the plan staging area atomically."""
    from app_gui.ui import operations_panel_forms as _ops_forms
    from app_gui.ui import operations_panel_plan_toolbar as _ops_plan_toolbar
    from app_gui.ui import operations_panel_execution as _ops_exec

    if bool(getattr(self, "_guard_write_action_by_migration_mode", lambda: False)()):
        return
    incoming = list(items or [])
    if not incoming:
        return

    _ops_forms._set_plan_feedback(self, "")
    existing_items = self._plan_store.list_items()
    replace_with_rollback = _is_rollback_replace_request(incoming)
    gate_existing_items = [] if replace_with_rollback else existing_items

    gate = validate_stage_request(
        existing_items=gate_existing_items,
        incoming_items=incoming,
        yaml_path=self.yaml_path_getter(),
        bridge=self.bridge,
        run_preflight=True,
        preflight_fn=preflight_plan,
    )

    blocked_messages = []
    for blocked in gate.get("blocked_items", []):
        err = localize_error_payload(blocked)
        if err not in blocked_messages:
            blocked_messages.append(str(err))

    if blocked_messages:
        _refresh_current_plan_validation(self, trigger="stage_blocked")
        first = blocked_messages[0]
        if replace_with_rollback and existing_items:
            user_text = _tr(
                "operations.planRejectedRollbackKept",
                error=first,
                count=len(existing_items),
            )
        else:
            user_text = _tr("operations.planRejected", error=first)
        preview = blocked_messages[:3]
        feedback = "\n".join(preview)
        if len(blocked_messages) > 3:
            feedback += f"\n... +{len(blocked_messages) - 3}"
        _ops_forms._set_plan_feedback(self, feedback, level="error")
        _ops_exec._publish_system_notice(
            self,
            code="plan.stage.blocked",
            text=user_text,
            level="error",
            timeout=5000,
            details=feedback,
            data={
                "blocked_items": gate.get("blocked_items") if isinstance(gate.get("blocked_items"), list) else [],
                "errors": gate.get("errors") if isinstance(gate.get("errors"), list) else [],
                "stats": gate.get("stats") if isinstance(gate.get("stats"), dict) else {},
                "incoming_items": incoming,
            },
        )
        return

    accepted = list(gate.get("accepted_items") or [])
    noop_items = list(gate.get("noop_items") or [])
    _apply_preflight_report(self, gate.get("preflight_report"))

    if not accepted and not noop_items:
        return

    if replace_with_rollback:
        replaced_count = len(existing_items)
        self._plan_store.replace_all(accepted)
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)
        _ops_forms._set_plan_feedback(self, "")

        _publish_plan_items_notice(
            self,
            code="plan.stage.replaced_by_rollback",
            text=_tr("operations.planRollbackReplaced", count=replaced_count),
            level="info",
            timeout=2000,
            items=accepted,
            count_key="replaced_count",
            count_value=replaced_count,
            include_total_count=True,
            extra_data={
                "items": accepted,
                "replaced_items": existing_items,
            },
        )
        return

    added = self._plan_store.add(accepted) if accepted else 0
    already_staged = len(noop_items)

    if added:
        _ops_plan_toolbar._refresh_after_plan_items_changed(self)
        _ops_forms._set_plan_feedback(self, "")

        if already_staged:
            notice_text = _tr(
                "operations.planAddedAndAlreadyStaged",
                added=added,
                already=already_staged,
            )
        else:
            notice_text = _tr("operations.planAddedCount", count=added)

        _publish_plan_items_notice(
            self,
            code="plan.stage.accepted",
            text=notice_text,
            level="info",
            timeout=2000,
            items=accepted,
            count_key="added_count",
            count_value=added,
            include_total_count=True,
            extra_data={
                "items": accepted,
                "noop_items": noop_items,
                "already_staged_count": already_staged,
            },
        )
        return

    _ops_plan_toolbar._refresh_after_plan_items_changed(self)
    _ops_forms._set_plan_feedback(self, "")
    _publish_plan_items_notice(
        self,
        code="plan.stage.already_staged",
        text=_tr("operations.planAlreadyStagedCount", count=already_staged),
        level="info",
        timeout=2000,
        items=noop_items,
        count_key="already_staged_count",
        count_value=already_staged,
        include_total_count=True,
        extra_data={
            "items": noop_items,
            "noop_items": noop_items,
        },
    )


def _run_plan_preflight(self, trigger="manual"):
    """Run preflight validation on current plan items."""
    _ = trigger  # Reserved for future trace tagging.

    plan_items = self._plan_store.list_items()
    if not plan_items:
        _apply_preflight_report(self, None)
        return

    yaml_path = self.yaml_path_getter()
    if not os.path.isfile(yaml_path):
        _apply_preflight_report(
            self,
            {
                "ok": True,
                "blocked": False,
                "items": [],
                "stats": {
                    "total": len(plan_items),
                    "ok": len(plan_items),
                    "blocked": 0,
                },
            }
        )
        return

    _apply_preflight_report(self, preflight_plan(yaml_path, plan_items, self.bridge))


def _update_execute_button_state(self):
    """Enable/disable Execute button based on preflight results."""
    if bool(getattr(self, "_is_write_locked_by_migration_mode", lambda: False)()):
        self.plan_exec_btn.setEnabled(False)
        self.plan_exec_btn.setText(_tr("operations.executeAll"))
        return
    if bool(getattr(self, "_plan_execution_running", False)):
        self.plan_exec_btn.setEnabled(False)
        self.plan_exec_btn.setText(
            _tr("operations.planExecuting", default="Executing...")
        )
        return

    if not self._plan_store.count():
        self.plan_exec_btn.setEnabled(False)
        return

    plan_items = self._plan_store.list_items()
    transient_statuses = [
        PlanStore.validation_status(item)
        for item in plan_items
    ]
    if any(
        status in {PLAN_VALIDATION_STATUS_PENDING, PLAN_VALIDATION_STATUS_VALIDATING}
        for status in transient_statuses
    ):
        self.plan_exec_btn.setEnabled(False)
        self.plan_exec_btn.setText(
            _tr("operations.executePlanValidating", default="Validating...")
        )
        return
    invalid_count = sum(1 for status in transient_statuses if status == PLAN_VALIDATION_STATUS_INVALID)
    if invalid_count:
        self.plan_exec_btn.setEnabled(False)
        self.plan_exec_btn.setText(
            _tr("operations.executePlanBlocked", count=invalid_count)
        )
        return

    has_blocked = any(v.get("blocked") for v in self._plan_validation_by_key.values())
    self.plan_exec_btn.setEnabled(not has_blocked)
    if has_blocked:
        blocked_count = sum(1 for v in self._plan_validation_by_key.values() if v.get("blocked"))
        self.plan_exec_btn.setText(
            _tr("operations.executePlanBlocked", count=blocked_count)
        )
    else:
        self.plan_exec_btn.setText(_tr("operations.executeAll"))


def remove_plan_items_by_payload(self, payloads):
    """Remove plan items matching payload descriptors.

    Each payload should be a dict with ``action``, ``box``, ``position``.
    Delegates to :meth:`PlanStore.remove_by_key`.
    """
    store = getattr(self, "_plan_store", None)
    if store is None:
        return 0
    total_removed = 0
    for descriptor in list(payloads or []):
        if not isinstance(descriptor, dict):
            continue
        action = str(descriptor.get("action") or "").strip().lower()
        box = descriptor.get("box")
        position = descriptor.get("position")
        if not action or position is None:
            continue
        try:
            box = int(box) if box is not None else None
            position = int(position)
        except (TypeError, ValueError):
            continue
        total_removed += store.remove_by_key(
            action=action,
            record_id=None,
            position=position,
            box=box,
        )
    return total_removed
