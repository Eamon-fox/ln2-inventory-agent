"""Plan staging helpers for AgentToolRunner."""

from app_gui.plan_gate import validate_stage_request
from lib.plan_item_factory import build_add_plan_item, build_edit_plan_item, build_record_plan_item, build_rollback_plan_item
from lib.tool_api import parse_batch_entries

def _stage_to_plan(self, tool_name, payload, trace_id=None):
    return self._stage_to_plan_impl(tool_name, payload, trace_id)

def _stage_to_plan_impl(self, tool_name, payload, trace_id=None):
    """Intercept write ops and stage as PlanItems for human approval."""
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

    gate = validate_stage_request(
        existing_items=self._plan_store.list_items() if self._plan_store else [],
        incoming_items=items,
        yaml_path=self._yaml_path,
        bridge=None,
        run_preflight=True,
    )
    if gate.get("blocked"):
        return self._build_stage_blocked_response(tool_name, gate)

    staged = list(gate.get("accepted_items") or [])
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
                "result": {"staged_count": 0, "blocked_count": 0},
            },
        )

    self._plan_store.add(staged)
    summary = [self._item_desc(item) for item in staged]
    return {
        "ok": True,
        "staged": True,
        "message": self._msg(
            "stage.stagedForHumanApproval",
            "Staged {count} operation(s) for human approval in Plan tab: {summary}",
            count=len(staged),
            summary="; ".join(summary),
        ),
        "result": {"staged_count": len(staged)},
    }

def _build_staged_plan_items(self, tool_name, payload, layout):
    handlers = {
        "add_entry": self._stage_items_add_entry,
        "record_takeout": self._stage_items_record_takeout,
        "batch_takeout": self._stage_items_batch_takeout,
        "edit_entry": self._stage_items_edit_entry,
        "rollback": self._stage_items_rollback,
    }
    handler = handlers.get(tool_name)
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
            frozen_at=payload.get("frozen_at"),
            fields=fields,
            source="ai",
        )
    ]

def _stage_items_record_takeout(self, payload, layout):
    rid_raw = payload.get("record_id")
    if rid_raw in (None, ""):
        raise ValueError(
            self._msg("errors.recordIdRequired", "record_id is required")
        )

    try:
        rid = int(rid_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            self._msg(
                "errors.recordIdMustBeInteger",
                "record_id must be an integer: {error}",
                error=exc,
            )
        ) from exc

    pos_raw = payload.get("position")
    pos = None
    if pos_raw not in (None, ""):
        pos = self._parse_position(pos_raw, layout=layout, field_name="position")

    to_pos_raw = payload.get("to_position")
    to_pos = None
    if to_pos_raw not in (None, ""):
        to_pos = self._parse_position(to_pos_raw, layout=layout, field_name="to_position")

    to_box_raw = payload.get("to_box")
    to_box = int(to_box_raw) if to_box_raw not in (None, "") else None

    box, position = self._lookup_record_info(rid)
    if pos is None:
        if position is not None:
            pos = int(position)
        else:
            raise ValueError(
                self._msg(
                    "errors.positionMissingCannotInfer",
                    "position is missing and cannot be inferred for record_id={record_id}. record has no position (may be consumed).",
                    record_id=rid,
                )
            )

    action_raw = payload.get("action", "takeout")
    return [
        build_record_plan_item(
            action=action_raw,
            record_id=rid,
            position=pos,
            box=box,
            date_str=payload.get("date"),
            to_position=to_pos,
            to_box=to_box,
            source="ai",
            payload_action=str(action_raw).strip(),
        )
    ]

def _stage_items_batch_takeout(self, payload, layout):
    entries = payload.get("entries")
    if isinstance(entries, str):
        entries = parse_batch_entries(entries, layout=layout)

    if not entries:
        raise ValueError(
            self._msg(
                "errors.entriesRequiredCannotBeEmpty",
                "entries is required and cannot be empty",
            )
        )

    action_raw = payload.get("action", "takeout")
    batch_to_box_raw = payload.get("to_box")
    batch_to_box = int(batch_to_box_raw) if batch_to_box_raw not in (None, "") else None

    items = []
    for entry in entries:
        rid = None
        pos = None
        to_pos = None
        to_box = batch_to_box

        if isinstance(entry, (list, tuple)):
            if len(entry) >= 4:
                rid = int(entry[0])
                pos = self._parse_position(entry[1], layout=layout, field_name="from_position")
                to_pos = self._parse_position(entry[2], layout=layout, field_name="to_position")
                to_box = int(entry[3])
            elif len(entry) == 3:
                rid = int(entry[0])
                pos = self._parse_position(entry[1], layout=layout, field_name="from_position")
                to_pos = self._parse_position(entry[2], layout=layout, field_name="to_position")
            elif len(entry) == 2:
                rid = int(entry[0])
                pos = self._parse_position(entry[1], layout=layout, field_name="position")
            elif len(entry) == 1:
                rid = int(entry[0])
            else:
                continue
        elif isinstance(entry, dict):
            rid = int(entry.get("record_id", entry.get("id", 0)) or 0)
            raw_pos = entry.get("position")
            if raw_pos is None:
                raw_pos = entry.get("from_position")
            if raw_pos not in (None, ""):
                pos = self._parse_position(raw_pos, layout=layout, field_name="position")
            raw_to_pos = entry.get("to_position")
            if raw_to_pos not in (None, ""):
                to_pos = self._parse_position(raw_to_pos, layout=layout, field_name="to_position")
            raw_to_box = entry.get("to_box")
            if raw_to_box not in (None, ""):
                to_box = int(raw_to_box)
        else:
            continue

        if not rid:
            raise ValueError(
                self._msg(
                    "errors.invalidBatchEntryMissingRecordId",
                    "Invalid batch entry (missing record_id): {entry}",
                    entry=entry,
                )
            )

        box, position = self._lookup_record_info(rid)
        if pos is None:
            # Keep staging atomic: let plan validation reject schema-invalid rows.
            pos = int(position) if position is not None else 0

        items.append(
            build_record_plan_item(
                action=action_raw,
                record_id=rid,
                position=pos,
                box=box,
                date_str=payload.get("date"),
                to_position=to_pos,
                to_box=to_box,
                source="ai",
                payload_action=str(action_raw).strip(),
            )
        )

    return items

def _stage_items_edit_entry(self, payload, _layout):
    rid_raw = payload.get("record_id")
    if rid_raw in (None, ""):
        raise ValueError(
            self._msg("errors.recordIdRequired", "record_id is required")
        )

    try:
        rid = int(rid_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            self._msg(
                "errors.recordIdMustBeInteger",
                "record_id must be an integer: {error}",
                error=exc,
            )
        ) from exc

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
