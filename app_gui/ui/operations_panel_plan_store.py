"""Plan-store and preflight helpers for OperationsPanel."""

import os

from app_gui.error_localizer import localize_error_payload
from app_gui.plan_executor import preflight_plan
from lib.plan_gate import validate_stage_request


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
    from app_gui.ui import operations_panel as _ops_panel

    action = str(item.get("action", "") or "")
    action_norm = action.lower()
    if action_norm == "add":
        box = item.get("box", "?")
        positions = item.get("positions")
        if positions is None:
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        pos_text = self._positions_to_display_text(positions or [])
        return _tr("operations.noticeDescAdd", box=box, positions=pos_text)

    if action_norm == "rollback":
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        source_event = payload.get("source_event") if isinstance(payload.get("source_event"), dict) else None
        if source_event and source_event.get("trace_id"):
            return _tr(
                "operations.noticeDescRollbackTrace",
                trace_id=str(source_event.get("trace_id")),
                action=str(source_event.get("action") or "-"),
            )
        backup_path = payload.get("backup_path")
        if backup_path:
            return _tr("operations.noticeDescRollbackPath", path=os.path.basename(str(backup_path)))
        return _tr("operations.noticeDescRollback")

    rid = item.get("record_id")
    rid_text = str(rid) if rid not in (None, "") else "?"
    box = item.get("box", "?")
    pos = self._position_to_display(item.get("position", "?"))
    to_pos = item.get("to_position")
    to_box = item.get("to_box")
    action_label = _ops_panel._localized_action(action or action_norm)
    if to_pos is not None:
        to_pos_text = self._position_to_display(to_pos)
        if to_box in (None, ""):
            return _tr(
                "operations.noticeDescRecordTargetNoBox",
                action=action_label,
                rid=rid_text,
                box=box,
                pos=pos,
                to_pos=to_pos_text,
            )
        return _tr(
            "operations.noticeDescRecordTarget",
            action=action_label,
            rid=rid_text,
            box=box,
            pos=pos,
            to_box=to_box,
            to_pos=to_pos_text,
        )
    return _tr(
        "operations.noticeDescRecord",
        action=action_label,
        rid=rid_text,
        box=box,
        pos=pos,
    )


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
        feedback = "\n".join(f"- {msg}" for msg in preview)
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

    if not self._plan_store.count():
        self.plan_exec_btn.setEnabled(False)
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
