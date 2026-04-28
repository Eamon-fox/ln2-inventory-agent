"""Plan staging helpers for AgentToolRunner."""

import threading
from typing import List

from lib.diagnostics import span
from lib.plan_gate import validate_stage_request
from lib.plan_item_factory import PlanItem, build_add_plan_item, build_edit_plan_item, build_record_plan_item, build_rollback_plan_item
from lib.plan_store import (
    PLAN_VALIDATION_STATUS_INVALID,
    PLAN_VALIDATION_STATUS_PENDING,
    PLAN_VALIDATION_STATUS_VALID,
    PLAN_VALIDATION_STATUS_VALIDATING,
    PlanStore,
)
from lib.tool_registry import WRITE_TOOLS


_STAGE_PREFLIGHT_DEBOUNCE_SECONDS = 2.0


def _stage_to_plan(self, tool_name, payload, trace_id=None):
    return self._stage_to_plan_impl(tool_name, payload, trace_id)

def _stage_to_plan_impl(self, tool_name, payload, trace_id=None):
    """Intercept write ops and stage as PlanItems for human approval."""
    if tool_name not in self.list_tools():
        return self._unknown_tool_response(tool_name)

    payload = self._sanitize_tool_input_payload(payload)

    input_error = self._validate_tool_input(tool_name, payload)
    if input_error:
        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": input_error,
            },
        )

    runtime_spec = self._runtime_spec(tool_name) if hasattr(self, "_runtime_spec") else None
    stage_guard = getattr(runtime_spec, "stage_guard", None)
    if callable(stage_guard):
        issue = stage_guard(self, payload)
        if issue:
            return self._with_hint(tool_name, issue)

    layout = self._load_layout()
    try:
        items = self._build_staged_plan_items(tool_name, payload, layout)
    except (ValueError, TypeError) as exc:
        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "invalid_tool_input",
                "message": str(exc),
            },
        )

    if trace_id and self._plan_store is not None and callable(self._preflight_fn):
        return _stage_to_plan_deferred_validation(self, tool_name, items, trace_id)

    gate = validate_stage_request(
        existing_items=self._plan_store.list_items() if self._plan_store else [],
        incoming_items=items,
        yaml_path=self._yaml_path,
        bridge=None,
        run_preflight=True,
        preflight_fn=self._preflight_fn,
    )
    if gate.get("blocked"):
        return self._build_stage_blocked_response(tool_name, gate)

    staged = list(gate.get("accepted_items") or [])
    noop_items = list(gate.get("noop_items") or [])
    already_staged_count = len(noop_items)
    if not self._plan_store:
        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "stage.planStoreNotAvailable",
                    "Plan store not available.",
                ),
                "staged": False,
                "result": {"staged_count": 0, "blocked_count": 0, "already_staged_count": 0},
            },
        )

    if staged:
        self._plan_store.add(staged)

    summary_items = staged if staged else noop_items
    summary = [self._item_desc(item) for item in summary_items]
    summary_text = "; ".join(summary)
    if staged and already_staged_count:
        message = self._msg(
            "stage.stagedForHumanApprovalWithAlready",
            "Staged {count} operation(s) for human approval in Plan tab: {summary}; {already} already staged.",
            count=len(staged),
            summary=summary_text,
            already=already_staged_count,
        )
    elif staged:
        message = self._msg(
            "stage.stagedForHumanApproval",
            "Staged {count} operation(s) for human approval in Plan tab: {summary}",
            count=len(staged),
            summary=summary_text,
        )
    else:
        message = self._msg(
            "stage.alreadyStagedInPlan",
            "These operations are already staged in Plan tab: {summary}",
            summary=summary_text,
        )

    return {
        "ok": True,
        "staged": bool(staged),
        "message": message,
        "result": {
            "staged_count": len(staged),
            "already_staged_count": already_staged_count,
        },
    }


def _stage_to_plan_deferred_validation(self, tool_name, items, trace_id):
    """Stage immediately, then debounce future-plan preflight in background.

    This path is used for agent runs, where a single trace can emit many
    write tool calls in a short burst. Direct runner calls without trace_id
    retain the historical immediate-preflight behavior used by tests and GUI
    helper flows.
    """
    gate = validate_stage_request(
        existing_items=self._plan_store.list_items() if self._plan_store else [],
        incoming_items=items,
        yaml_path=self._yaml_path,
        bridge=None,
        run_preflight=False,
        preflight_fn=self._preflight_fn,
    )
    if gate.get("blocked"):
        return self._build_stage_blocked_response(tool_name, gate)

    staged = []
    for item in list(gate.get("accepted_items") or []):
        staged_item = dict(item)
        PlanStore.apply_validation_state(
            staged_item,
            status=PLAN_VALIDATION_STATUS_PENDING,
            trace_id=trace_id,
        )
        staged.append(staged_item)

    noop_items = list(gate.get("noop_items") or [])
    already_staged_count = len(noop_items)
    if not self._plan_store:
        return self._with_hint(
            tool_name,
            {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "stage.planStoreNotAvailable",
                    "Plan store not available.",
                ),
                "staged": False,
                "result": {"staged_count": 0, "blocked_count": 0, "already_staged_count": 0},
            },
        )

    if staged:
        self._plan_store.add(staged)
        _schedule_deferred_stage_preflight(self, trace_id)

    summary_items = staged if staged else noop_items
    summary = [self._item_desc(item) for item in summary_items]
    summary_text = "; ".join(summary)
    if staged and already_staged_count:
        message = self._msg(
            "stage.stagedForHumanApprovalWithAlready",
            "Staged {count} operation(s) for human approval in Plan tab: {summary}; {already} already staged.",
            count=len(staged),
            summary=summary_text,
            already=already_staged_count,
        )
    elif staged:
        message = self._msg(
            "stage.stagedForHumanApproval",
            "Staged {count} operation(s) for human approval in Plan tab: {summary}",
            count=len(staged),
            summary=summary_text,
        )
    else:
        message = self._msg(
            "stage.alreadyStagedInPlan",
            "These operations are already staged in Plan tab: {summary}",
            summary=summary_text,
        )

    return {
        "ok": True,
        "staged": bool(staged),
        "message": message,
        "validation_status": "pending" if staged else "unchanged",
        "result": {
            "staged_count": len(staged),
            "already_staged_count": already_staged_count,
            "pending_validation": bool(staged),
        },
    }


def _ensure_stage_validation_state(self):
    lock = getattr(self, "_stage_validation_lock", None)
    if lock is None:
        lock = threading.Lock()
        self._stage_validation_lock = lock
        self._stage_validation_timer = None
        self._stage_validation_generation = 0
        self._stage_validation_running = False
        self._stage_validation_reschedule_requested = False
        self._stage_validation_trace_id = ""
    return lock


def _schedule_deferred_stage_preflight(self, trace_id):
    lock = _ensure_stage_validation_state(self)
    with lock:
        self._stage_validation_generation += 1
        generation = self._stage_validation_generation
        self._stage_validation_trace_id = str(trace_id or "")
        if getattr(self, "_stage_validation_running", False):
            self._stage_validation_reschedule_requested = True
            return
        old_timer = getattr(self, "_stage_validation_timer", None)
        if old_timer is not None:
            try:
                old_timer.cancel()
            except Exception:
                pass
        _start_stage_validation_timer(self, str(trace_id or ""), generation)


def _start_stage_validation_timer(self, trace_id, generation):
    timer = threading.Timer(
        _STAGE_PREFLIGHT_DEBOUNCE_SECONDS,
        _run_deferred_stage_preflight,
        args=(self, str(trace_id or ""), generation),
    )
    timer.daemon = True
    self._stage_validation_timer = timer
    timer.start()


def _run_deferred_stage_preflight(self, trace_id, generation):
    lock = _ensure_stage_validation_state(self)
    with lock:
        if generation != getattr(self, "_stage_validation_generation", 0):
            return
        if getattr(self, "_stage_validation_running", False):
            self._stage_validation_reschedule_requested = True
            return
        self._stage_validation_running = True
        self._stage_validation_timer = None

    try:
        store = getattr(self, "_plan_store", None)
        preflight_fn = getattr(self, "_preflight_fn", None)
        if store is None or not callable(preflight_fn):
            return

        items = store.list_items()
        if not items:
            return

        keys = [store.item_key(item) for item in items]
        store.update_validation_statuses(
            {
                key: {
                    "status": PLAN_VALIDATION_STATUS_VALIDATING,
                    "trace_id": trace_id,
                }
                for key in keys
            }
        )

        try:
            with span(
                "plan.preflight",
                source="agent_stage_debounce",
                trace_id=trace_id,
                batch_size=len(items),
            ):
                report = preflight_fn(self._yaml_path, items, None)
        except Exception as exc:
            report = {
                "ok": False,
                "blocked": True,
                "items": [
                    {
                        "item": item,
                        "blocked": True,
                        "error_code": "plan_preflight_failed",
                        "message": f"Preflight exception: {exc}",
                    }
                    for item in items
                ],
            }

        with lock:
            if generation != getattr(self, "_stage_validation_generation", 0):
                return

        blocked_by_key = {}
        if isinstance(report, dict):
            for report_item in report.get("items") or []:
                if not isinstance(report_item, dict) or not report_item.get("blocked"):
                    continue
                item = report_item.get("item")
                if not isinstance(item, dict):
                    continue
                blocked_by_key[store.item_key(item)] = {
                    "status": PLAN_VALIDATION_STATUS_INVALID,
                    "error_code": report_item.get("error_code") or "plan_preflight_failed",
                    "message": report_item.get("message") or "Preflight validation failed",
                    "trace_id": trace_id,
                }

        updates = {}
        for item in store.list_items():
            key = store.item_key(item)
            if key in blocked_by_key:
                updates[key] = blocked_by_key[key]
            else:
                updates[key] = {
                    "status": PLAN_VALIDATION_STATUS_VALID,
                    "trace_id": trace_id,
                }
        store.update_validation_statuses(updates)
    finally:
        with lock:
            current_generation = getattr(self, "_stage_validation_generation", 0)
            current_trace_id = getattr(self, "_stage_validation_trace_id", trace_id)
            should_reschedule = (
                getattr(self, "_stage_validation_reschedule_requested", False)
                or generation != current_generation
            )
            self._stage_validation_running = False
            self._stage_validation_reschedule_requested = False
            if should_reschedule and current_generation:
                _start_stage_validation_timer(self, current_trace_id, current_generation)

def _build_staged_plan_items(self, tool_name, payload, layout) -> List[PlanItem]:
    runtime_specs = self._runtime_specs() if hasattr(self, "_runtime_specs") else {}
    staging_handlers = {
        name: spec.stage_builder
        for name, spec in runtime_specs.items()
        if callable(spec.stage_builder)
    }
    assert WRITE_TOOLS <= staging_handlers.keys(), (
        f"Staging handlers missing for write tools: {WRITE_TOOLS - staging_handlers.keys()}"
    )
    handler = staging_handlers.get(tool_name)
    if not callable(handler):
        return []
    return handler(payload, layout)

def _stage_items_add_entry(self, payload, layout):
    box_raw = payload.get("box")
    positions_raw = payload.get("positions")
    positions = self._normalize_positions(positions_raw, layout=layout) or []
    box = int(box_raw) if box_raw is not None else 0
    fields = dict(payload.get("fields") or {})
    return [
        build_add_plan_item(
            box=box,
            positions=positions,
            stored_at=payload.get("stored_at"),
            frozen_at=payload.get("frozen_at"),
            fields=fields,
            source="ai",
        )
    ]

def _extract_flat_slot(self, payload, *, layout, box_key, pos_key, field_name):
    box = self._required_int(payload, box_key)
    position = self._parse_position(
        payload.get(pos_key),
        layout=layout,
        field_name=field_name,
    )
    return box, position


def _parse_required_record_id(self, payload):
    rid_raw = payload.get("record_id")
    if rid_raw in (None, ""):
        raise ValueError(
            self._msg("errors.recordIdRequired", "record_id is required")
        )
    try:
        return int(rid_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            self._msg(
                "errors.recordIdMustBeInteger",
                "record_id must be an integer: {error}",
                error=exc,
            )
        ) from exc


def _require_non_empty_entries(self, entries):
    if entries:
        return entries
    raise ValueError(
        self._msg(
            "errors.entriesRequiredCannotBeEmpty",
            "entries is required and cannot be empty",
        )
    )


def _require_batch_entry_object(self, entry, idx):
    if isinstance(entry, dict):
        return entry
    raise ValueError(
        self._msg(
            "validation.mustBeObject",
            "{label} must be an object",
            label=f"entries[{idx}]",
        )
    )


def _parse_batch_entry_record_id(self, entry):
    rid_raw = entry.get("record_id")
    if rid_raw in (None, ""):
        raise ValueError(
            self._msg(
                "errors.invalidBatchEntryMissingRecordId",
                "Invalid batch entry (missing record_id): {entry}",
                entry=entry,
            )
        )
    return int(rid_raw)


def _stage_items_takeout(self, payload, layout):
    entries = _require_non_empty_entries(self, payload.get("entries"))
    items = []
    for idx, entry in enumerate(entries):
        entry = _require_batch_entry_object(self, entry, idx)
        rid = _parse_batch_entry_record_id(self, entry)
        from_box, pos = _extract_flat_slot(
            self,
            entry,
            layout=layout,
            box_key="from_box",
            pos_key="from_position",
            field_name=f"entries[{idx}].from_position",
        )

        items.append(
            build_record_plan_item(
                action="takeout",
                record_id=rid,
                position=pos,
                box=from_box,
                date_str=payload.get("date"),
                source="ai",
                payload_action="Takeout",
            )
        )

    return items

def _stage_items_move(self, payload, layout):
    entries = _require_non_empty_entries(self, payload.get("entries"))

    items = []
    for idx, entry in enumerate(entries):
        entry = _require_batch_entry_object(self, entry, idx)
        rid = _parse_batch_entry_record_id(self, entry)
        from_box, from_pos = _extract_flat_slot(
            self,
            entry,
            layout=layout,
            box_key="from_box",
            pos_key="from_position",
            field_name=f"entries[{idx}].from_position",
        )
        to_box, to_pos = _extract_flat_slot(
            self,
            entry,
            layout=layout,
            box_key="to_box",
            pos_key="to_position",
            field_name=f"entries[{idx}].to_position",
        )

        items.append(
            build_record_plan_item(
                action="move",
                record_id=rid,
                position=from_pos,
                box=from_box,
                date_str=payload.get("date"),
                to_position=to_pos,
                to_box=to_box,
                source="ai",
                payload_action="Move",
            )
        )

    return items

def _stage_items_edit_entry(self, payload, _layout):
    rid = _parse_required_record_id(self, payload)

    fields = payload.get("fields")
    if not fields or not isinstance(fields, dict):
        raise ValueError(
            self._msg(
                "errors.fieldsMustBeNonEmptyObject",
                "fields must be a non-empty object",
            )
        )

    box, position = self._lookup_record_info(rid)
    pos = int(position) if position is not None else 1
    return [
        build_edit_plan_item(
            record_id=rid,
            fields=fields,
            box=box,
            position=pos,
            source="ai",
        )
    ]

def _stage_items_rollback(self, payload, _layout):
    backup_path = payload.get("backup_path")
    return [
        build_rollback_plan_item(
            backup_path=str(backup_path),
            source="ai",
        )
    ]

def _build_stage_blocked_response(self, tool_name, gate):
    gate_errors = list(gate.get("errors") or [])
    gate_blocked = list(gate.get("blocked_items") or [])
    has_preflight = any(err.get("kind") == "preflight" for err in gate_errors)
    error_code = "plan_preflight_failed" if has_preflight else "plan_validation_failed"
    repair_ids = self._extract_record_ids_from_payload(gate_errors, gate_blocked)

    detail_lines = []
    for blocked in gate_blocked[:3]:
        desc = self._item_desc(blocked)
        error = blocked.get("message") or blocked.get("error_code") or self._msg(
            "errors.unknownError",
            "Unknown error",
        )
        if isinstance(error, str):
            error = error.splitlines()[0].strip()
        detail_lines.append(f"{desc}: {error}")
    detail = "; ".join(detail_lines)
    if len(gate_blocked) > 3:
        detail += self._msg(
            "stage.moreBlockedItems",
            "; ... and {count} more",
            count=len(gate_blocked) - 3,
        )

    result_payload = {
        "staged_count": 0,
        "blocked_count": len(gate_blocked),
        "repair_candidates": {"record_ids": repair_ids} if repair_ids else {},
    }

    return self._with_hint(
        tool_name,
        {
            "ok": False,
            "error_code": error_code,
            "message": self._msg(
                "stage.allRejectedByValidation",
                "All operations rejected by validation: {detail}",
                detail=detail,
            ),
            "staged": False,
            "result": result_payload,
            "blocked_items": gate_blocked,
            "repair_candidates": {"record_ids": repair_ids} if repair_ids else {},
        },
    )
