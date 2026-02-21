"""Unified Tool API shared by CLI, GUI, and AI agents."""

import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from .position_fmt import (
    display_to_box,
    display_to_pos,
    get_box_numbers,
)
from .migrate_takeout_actions import migrate_takeout_actions
from .takeout_parser import extract_events, normalize_action
from .validators import (
    format_validation_errors,
    parse_positions,
    validate_box,
    validate_date,
    validate_inventory,
    validate_position,
)
from .yaml_ops import (
    append_audit_event,
    load_yaml,
)


_DEFAULT_SESSION_ID = f"session-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _get_layout(data):
    """Extract box_layout dict from loaded YAML data."""
    return (data or {}).get("meta", {}).get("box_layout", {})


def _format_box_constraint(layout):
    """Format allowed box IDs for messages."""
    boxes = list(get_box_numbers(layout))
    if not boxes:
        return "N/A"
    if len(boxes) == 1:
        return str(boxes[0])
    is_contiguous = all(boxes[i] + 1 == boxes[i + 1] for i in range(len(boxes) - 1))
    if is_contiguous:
        return f"{boxes[0]}-{boxes[-1]}"
    return ",".join(str(box_num) for box_num in boxes)


def _is_middle_box(box_numbers, target_box):
    """Return True when removing target would leave higher-numbered boxes."""
    return any(box_num > target_box for box_num in box_numbers)


def build_actor_context(
    actor_type="human",
    channel="cli",
    session_id=None,
    trace_id=None,
):
    """Build normalized actor context for unified audit records."""
    at = actor_type or "human"
    return {
        "actor_type": at,
        "actor_id": at,
        "channel": channel or "cli",
        "session_id": session_id or _DEFAULT_SESSION_ID,
        "trace_id": trace_id,
    }


def _coerce_position_value(raw_value, layout=None, field_name="position"):
    """Convert a display/internal position value to internal integer position."""
    if raw_value in (None, ""):
        raise ValueError(f"{field_name} cannot be empty")
    try:
        return int(display_to_pos(raw_value, layout))
    except Exception as exc:
        raise ValueError(f"{field_name} is invalid: {raw_value}") from exc


def _normalize_positions_input(positions, layout=None):
    """Normalize add-entry positions input into a list of internal integers."""
    if isinstance(positions, str):
        return parse_positions(positions, layout=layout)

    if isinstance(positions, (list, tuple, set)):
        return [_coerce_position_value(value, layout=layout, field_name="position") for value in positions]

    if positions in (None, ""):
        return []

    return [_coerce_position_value(positions, layout=layout, field_name="position")]


def parse_batch_entries(entries_str, layout=None):
    """Parse batch input format.

    Supports:
    - ``id1,id2,...`` (use current active position for each tube id; takeout only)
    - ``id1:pos1,id2:pos2,...`` (takeout)
    - ``id1:from1->to1,id2:from2->to2,...`` (move within same box)
    - ``id1:from1->to1:box,id2:from2->to2:box,...`` (cross-box move)

    ``pos/from/to`` accepts display values under current layout (e.g. ``A1``).
    """
    result = []
    try:
        for entry in str(entries_str).split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" not in entry:
                result.append((int(entry),))
                continue

            parts = entry.split(":")
            record_id = int(parts[0])
            pos_text = parts[1].strip() if len(parts) >= 2 else ""
            if not pos_text:
                result.append((record_id,))
                continue

            to_box = int(parts[2]) if len(parts) >= 3 else None
            if "->" in pos_text:
                from_pos_text, to_pos_text = pos_text.split("->", 1)
                tup = (
                    record_id,
                    _coerce_position_value(from_pos_text, layout=layout, field_name="from_position"),
                    _coerce_position_value(to_pos_text, layout=layout, field_name="to_position"),
                )
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            elif ">" in pos_text:
                from_pos_text, to_pos_text = pos_text.split(">", 1)
                tup = (
                    record_id,
                    _coerce_position_value(from_pos_text, layout=layout, field_name="from_position"),
                    _coerce_position_value(to_pos_text, layout=layout, field_name="to_position"),
                )
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            else:
                result.append((record_id, _coerce_position_value(pos_text, layout=layout, field_name="position")))
    except Exception as exc:
        raise ValueError(
            "Invalid input format: "
            f"{exc}. Valid examples: '182,183' or '182:23,183:41' or '182:23->31,183:41->42' or '182:23->31:1' (cross-box)"
        )
    return result


def _coerce_batch_entry(entry, layout=None):
    """Normalize one batch entry to a tuple of ints.

    Accepts tuple/list forms ``(record_id, position)`` or ``(record_id, from_pos, to_pos)``
    and dict forms with common aliases.
    """
    if isinstance(entry, dict):
        record_id = entry.get("record_id", entry.get("id"))
        from_pos = entry.get("position")
        if from_pos is None:
            from_pos = entry.get("from_position", entry.get("from_pos", entry.get("from")))
        to_pos = entry.get("to_position")
        if to_pos is None:
            to_pos = entry.get("to_pos", entry.get("target_position", entry.get("target_pos")))
        to_box = entry.get("to_box")

        if record_id is None:
            raise ValueError("Each item must include record_id/id")
        if from_pos is None:
            if to_pos is None:
                return (int(record_id),)
            raise ValueError("Each item must include position/from_position")
        if to_pos is None:
            return (int(record_id), _coerce_position_value(from_pos, layout=layout, field_name="position"))
        if to_box is not None:
            return (
                int(record_id),
                _coerce_position_value(from_pos, layout=layout, field_name="from_position"),
                _coerce_position_value(to_pos, layout=layout, field_name="to_position"),
                int(to_box),
            )
        return (
            int(record_id),
            _coerce_position_value(from_pos, layout=layout, field_name="from_position"),
            _coerce_position_value(to_pos, layout=layout, field_name="to_position"),
        )

    if isinstance(entry, (list, tuple)):
        if len(entry) == 1:
            return (int(entry[0]),)
        if len(entry) == 2:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="position"),
            )
        if len(entry) == 3:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="from_position"),
                _coerce_position_value(entry[2], layout=layout, field_name="to_position"),
            )
        if len(entry) == 4:
            return (
                int(entry[0]),
                _coerce_position_value(entry[1], layout=layout, field_name="from_position"),
                _coerce_position_value(entry[2], layout=layout, field_name="to_position"),
                int(entry[3]),
            )
        raise ValueError(
            "Each item must be (record_id) or (record_id, position) or (record_id, from_position, to_position[, to_box])"
        )

    raise ValueError("Each item must be tuple/list/dict")


def _parse_slot_payload(slot_payload, *, layout, field_name):
    """Normalize one V2 slot payload into internal ``(box, position)``."""
    if not isinstance(slot_payload, dict):
        raise ValueError(f"{field_name} must be an object with box/position")
    if "box" not in slot_payload:
        raise ValueError(f"{field_name}.box is required")
    if "position" not in slot_payload:
        raise ValueError(f"{field_name}.position is required")
    try:
        box = int(display_to_box(slot_payload.get("box"), layout))
    except Exception as exc:
        raise ValueError(f"{field_name}.box is invalid: {slot_payload.get('box')}") from exc
    pos = _coerce_position_value(
        slot_payload.get("position"),
        layout=layout,
        field_name=f"{field_name}.position",
    )
    return box, pos


def _find_record_by_id_local(records, record_id):
    """Return record dict by ``id`` from loaded inventory list."""
    target = int(record_id)
    for rec in records or []:
        try:
            rid = int(rec.get("id"))
        except Exception:
            continue
        if rid == target:
            return rec
    return None


def _validate_source_slot_match(record, *, record_id, from_box, from_pos):
    """Return issue payload if source slot does not match active record slot."""
    if record is None:
        return {
            "error_code": "record_not_found",
            "message": f"Record ID {record_id} not found",
            "details": {"record_id": record_id},
        }

    current_box = record.get("box")
    current_pos = record.get("position")
    if current_pos is None:
        return {
            "error_code": "position_not_found",
            "message": f"Record ID {record_id} has no active position",
            "details": {"record_id": record_id},
        }

    try:
        current_box_int = int(current_box)
        current_pos_int = int(current_pos)
    except Exception:
        return {
            "error_code": "validation_failed",
            "message": f"Record ID {record_id} has invalid box/position fields",
            "details": {"record_id": record_id},
        }

    if current_box_int != int(from_box) or current_pos_int != int(from_pos):
        return {
            "error_code": "from_mismatch",
            "message": (
                f"Record ID {record_id} source mismatch: requested "
                f"Box {from_box}:{from_pos}, current Box {current_box_int}:{current_pos_int}"
            ),
            "details": {
                "record_id": record_id,
                "from_box": from_box,
                "from_position": from_pos,
                "current_box": current_box_int,
                "current_position": current_pos_int,
            },
        }

    return None


def _build_move_event(
    date_str,
    from_position,
    to_position,
    paired_record_id=None,
    from_box=None,
    to_box=None,
):
    """Build normalized move event payload."""
    event = {
        "date": date_str,
        "action": "move",
        "positions": [from_position],
        "from_position": from_position,
        "to_position": to_position,
    }
    if from_box is not None:
        event["from_box"] = from_box
    if to_box is not None:
        event["to_box"] = to_box
    if paired_record_id is not None:
        event["paired_record_id"] = paired_record_id
    return event


def _build_audit_meta(action, source, tool_name, actor_context=None, details=None, tool_input=None):
    actor = dict(build_actor_context())
    actor.update(actor_context or {})
    if not actor.get("trace_id"):
        actor["trace_id"] = f"trace-{uuid.uuid4().hex}"
    if not actor.get("session_id"):
        actor["session_id"] = _DEFAULT_SESSION_ID

    return {
        "action": action,
        "source": source,
        "tool_name": tool_name,
        "actor_type": actor.get("actor_type", "human"),
        "actor_id": actor.get("actor_type", "human"),
        "channel": actor.get("channel", "cli"),
        "session_id": actor.get("session_id"),
        "trace_id": actor.get("trace_id"),
        "status": "success",
        "details": details,
        "tool_input": tool_input,
    }


def _validate_data_or_error(data, message_prefix="Write blocked: integrity validation failed"):
    """Return structured validation error payload when data is invalid."""
    errors, _warnings = validate_inventory(data)
    if not errors:
        return None
    return {
        "ok": False,
        "error_code": "integrity_validation_failed",
        "message": format_validation_errors(errors, prefix=message_prefix),
        "errors": errors,
    }


def _append_failed_audit(
    yaml_path,
    action,
    source,
    tool_name,
    actor_context=None,
    details=None,
    tool_input=None,
    error_code=None,
    message=None,
    errors=None,
    before_data=None,
):
    """Best-effort audit append for blocked/failed write operations."""
    meta = _build_audit_meta(
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        details=details,
        tool_input=tool_input,
    )
    meta["status"] = "failed"
    error_payload = {
        "error_code": error_code,
        "message": message,
    }
    if errors:
        error_payload["errors"] = errors
    meta["error"] = error_payload

    snapshot = before_data if isinstance(before_data, dict) else None
    try:
        append_audit_event(
            yaml_path=yaml_path,
            before_data=snapshot,
            after_data=snapshot,
            backup_path=None,
            warnings=[],
            audit_meta=meta,
        )
    except Exception:
        # Failure auditing must never change tool behavior.
        return


def _failure_result(
    yaml_path,
    action,
    source,
    tool_name,
    error_code,
    message,
    actor_context=None,
    details=None,
    tool_input=None,
    before_data=None,
    errors=None,
    extra=None,
):
    payload = {
        "ok": False,
        "error_code": error_code,
        "message": message,
    }
    if errors is not None:
        payload["errors"] = errors
    if extra:
        payload.update(extra)

    _append_failed_audit(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        details=details,
        tool_input=tool_input,
        error_code=error_code,
        message=message,
        errors=errors,
        before_data=before_data,
    )
    return payload


_ALLOWED_EXECUTION_MODES = {"direct", "preflight", "execute"}


def _normalize_execution_mode(execution_mode):
    mode = str(execution_mode or "").strip().lower()
    return mode or "direct"


def _enforce_execute_mode_for_source(source):
    """Return True when this caller must execute writes via execute mode.

    Keep plain ``tool_api`` source backward compatible for direct library users,
    while enforcing plan execution for GUI/agent channels.
    """
    src = str(source or "").strip().lower()
    if src in {"", "tool_api"}:
        return False
    return src.startswith("agent") or src.startswith("app_gui") or src.startswith("plan_executor")


def _validate_execution_gate(*, dry_run=False, execution_mode=None, source="tool_api"):
    mode = _normalize_execution_mode(execution_mode)
    if mode not in _ALLOWED_EXECUTION_MODES:
        return {
            "error_code": "invalid_execution_mode",
            "message": "execution_mode must be direct/preflight/execute",
            "details": {"execution_mode": execution_mode},
        }, mode

    if bool(dry_run):
        return None, mode

    if _enforce_execute_mode_for_source(source) and mode != "execute":
        return {
            "error_code": "write_requires_execute_mode",
            "message": "Writes are only allowed during plan execution (save to Plan first, then click Execute).",
            "details": {"execution_mode": mode, "source": source},
        }, mode

    return None, mode


def _validate_add_entry_request(payload):
    frozen_at = payload.get("frozen_at")
    positions = payload.get("positions")
    if not validate_date(frozen_at):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {frozen_at}",
            "details": {"frozen_at": frozen_at},
        }, {}
    if not positions:
        return {
            "error_code": "empty_positions",
            "message": "At least one position is required",
        }, {}
    return None, {}


def _validate_edit_entry_request(payload):
    fields = payload.get("fields")
    if not fields:
        return {
            "error_code": "no_fields",
            "message": "At least one field must be provided",
        }, {}
    if "frozen_at" in fields and not validate_date(fields["frozen_at"]):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {fields['frozen_at']}",
            "details": {"frozen_at": fields["frozen_at"]},
        }, {}
    return None, {}


def _validate_record_takeout_request(payload):
    date_str = payload.get("date_str")
    action = payload.get("action")
    to_position = payload.get("to_position")

    if not validate_date(date_str):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {date_str}",
            "details": {"date": date_str},
        }, {}

    action_en = normalize_action(action)
    if not action_en:
        return {
            "error_code": "invalid_action",
            "message": "Action must be takeout/move",
            "details": {"action": action},
        }, {}

    normalized = {"action_en": action_en, "move_to_position": None}
    if action_en == "move":
        if to_position in (None, ""):
            return {
                "error_code": "invalid_move_target",
                "message": "Move operation requires to_position (target position)",
            }, normalized
        normalized["move_to_position"] = to_position

    return None, normalized


def _validate_batch_takeout_request(payload):
    date_str = payload.get("date_str")
    action = payload.get("action")
    entries = payload.get("entries")

    if not validate_date(date_str):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {date_str}",
            "details": {"date": date_str},
        }, {}

    if not entries:
        return {
            "error_code": "empty_entries",
            "message": "No entries provided",
        }, {}

    action_en = normalize_action(action)
    if not action_en:
        return {
            "error_code": "invalid_action",
            "message": "Action must be takeout/move",
            "details": {"action": action},
        }, {}

    return None, {"action_en": action_en}


def _validate_adjust_box_count_request(payload):
    operation = payload.get("operation")
    op_text = str(operation or "").strip().lower()
    op_alias = {
        "add": "add",
        "add_boxes": "add",
        "increase": "add",
        "remove": "remove",
        "remove_box": "remove",
        "delete": "remove",
    }
    op = op_alias.get(op_text)
    if not op:
        return {
            "error_code": "invalid_operation",
            "message": "operation must be add/remove",
            "details": {"operation": operation},
        }, {}
    return None, {"op": op}


_WRITE_REQUEST_VALIDATORS = {
    "tool_add_entry": _validate_add_entry_request,
    "tool_edit_entry": _validate_edit_entry_request,
    "tool_record_takeout": _validate_record_takeout_request,
    "tool_batch_takeout": _validate_batch_takeout_request,
    "tool_rollback": lambda _payload: (None, {}),
    "tool_adjust_box_count": _validate_adjust_box_count_request,
}


def validate_write_tool_call(
    *,
    yaml_path,
    action,
    source,
    tool_name,
    tool_input,
    payload,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    before_data=None,
):
    """Unified write-tool validation gate.

    1) Enforce execute-mode write policy for GUI/agent channels.
    2) Dispatch to each tool's request-level validator.
    3) Return either a normalized success payload or unified failure payload.
    """
    gate_issue, normalized_mode = _validate_execution_gate(
        dry_run=dry_run,
        execution_mode=execution_mode,
        source=source,
    )
    if gate_issue:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=gate_issue.get("error_code", "validation_failed"),
            message=gate_issue.get("message", "Write validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=before_data,
            errors=gate_issue.get("errors"),
            details=gate_issue.get("details"),
            extra=gate_issue.get("extra"),
        )

    validator = _WRITE_REQUEST_VALIDATORS.get(tool_name)
    if callable(validator):
        payload_dict = payload if isinstance(payload, dict) else {}
        validator_result = validator(payload_dict)
        if isinstance(validator_result, tuple) and len(validator_result) == 2:
            issue, normalized = validator_result
        else:
            issue, normalized = None, {}
        if issue:
            return _failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Write validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                errors=issue.get("errors"),
                details=issue.get("details"),
                extra=issue.get("extra"),
            )
    else:
        normalized = {}

    return {
        "ok": True,
        "execution_mode": normalized_mode,
        "normalized": normalized,
    }


def tool_add_entry(
    yaml_path,
    box,
    positions,
    frozen_at,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    return _tool_add_entry_impl(
        yaml_path=yaml_path,
        box=box,
        positions=positions,
        frozen_at=frozen_at,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def _tool_add_entry_impl(
    yaml_path,
    box,
    positions,
    frozen_at,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._tool_add_entry_impl(
        yaml_path=yaml_path,
        box=box,
        positions=positions,
        frozen_at=frozen_at,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


_EDITABLE_FIELDS = {"frozen_at", "cell_line", "note"}


def _get_editable_fields(yaml_path):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._get_editable_fields(yaml_path)


def tool_edit_entry(
    yaml_path,
    record_id,
    fields,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops.tool_edit_entry(
        yaml_path=yaml_path,
        record_id=record_id,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def tool_record_takeout(
    yaml_path,
    record_id,
    from_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    """V2 takeout API requiring explicit source slot."""
    audit_action = "record_takeout"
    tool_name = "tool_record_takeout_v2"
    tool_input = {
        "record_id": record_id,
        "from": from_slot,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    layout = _get_layout(data)
    records = data.get("inventory", [])
    try:
        from_box, from_pos = _parse_slot_payload(from_slot, layout=layout, field_name="from")
    except ValueError as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message=str(exc),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    if not validate_box(from_box, layout):
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Source box {from_box} is out of range ({_format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    record = _find_record_by_id_local(records, record_id)
    issue = _validate_source_slot_match(
        record,
        record_id=record_id,
        from_box=from_box,
        from_pos=from_pos,
    )
    if issue:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code=issue.get("error_code", "validation_failed"),
            message=issue.get("message", "Source slot validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=issue.get("details"),
        )

    return _tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=from_pos,
        date_str=date_str,
        action="takeout",
        to_position=None,
        to_box=None,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def tool_record_move(
    yaml_path,
    record_id,
    from_slot,
    to_slot,
    date_str=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    """V2 move API requiring explicit source and target slots."""
    audit_action = "record_takeout"
    tool_name = "tool_record_move"
    tool_input = {
        "record_id": record_id,
        "from": from_slot,
        "to": to_slot,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    layout = _get_layout(data)
    records = data.get("inventory", [])
    try:
        from_box, from_pos = _parse_slot_payload(from_slot, layout=layout, field_name="from")
        to_box, to_pos = _parse_slot_payload(to_slot, layout=layout, field_name="to")
    except ValueError as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message=str(exc),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    if not validate_box(from_box, layout):
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Source box {from_box} is out of range ({_format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )
    if not validate_box(to_box, layout):
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Target box {to_box} is out of range ({_format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    record = _find_record_by_id_local(records, record_id)
    issue = _validate_source_slot_match(
        record,
        record_id=record_id,
        from_box=from_box,
        from_pos=from_pos,
    )
    if issue:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code=issue.get("error_code", "validation_failed"),
            message=issue.get("message", "Source slot validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=issue.get("details"),
        )

    return _tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=from_pos,
        date_str=date_str,
        action="move",
        to_position=to_pos,
        to_box=to_box,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def _tool_record_takeout_impl(
    yaml_path,
    record_id,
    position=None,
    date_str=None,
    action="takeout",
    to_position=None,
    to_box=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=position,
        date_str=date_str,
        action=action,
        to_position=to_position,
        to_box=to_box,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )

def tool_batch_takeout(
    yaml_path,
    entries,
    date_str,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    """V2 batch takeout API using explicit source slots."""
    audit_action = "batch_takeout"
    tool_name = "tool_batch_takeout_v2"
    tool_input = {
        "entries": entries,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    layout = _get_layout(data)
    records = data.get("inventory", [])
    record_map = {}
    for rec in records:
        try:
            record_map[int(rec.get("id"))] = rec
        except Exception:
            continue

    normalized_entries = []
    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=f"entries[{idx}] must be an object",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}]"},
            )
        record_id = entry.get("record_id")
        if record_id in (None, ""):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=f"entries[{idx}].record_id is required",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].record_id"},
            )
        rid = int(record_id)
        try:
            from_box, from_pos = _parse_slot_payload(entry.get("from"), layout=layout, field_name=f"entries[{idx}].from")
        except ValueError as exc:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=str(exc),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].from"},
            )
        if not validate_box(from_box, layout):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].from.box {from_box} is out of range ({_format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].from.box"},
            )

        issue = _validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Source slot validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, **(issue.get("details") or {})},
            )
        normalized_entries.append((rid, from_pos))

    return _tool_batch_takeout_impl(
        yaml_path=yaml_path,
        entries=normalized_entries,
        date_str=date_str,
        action="takeout",
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def tool_batch_move(
    yaml_path,
    entries,
    date_str,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    """V2 batch move API using explicit source and target slots."""
    audit_action = "batch_takeout"
    tool_name = "tool_batch_move"
    tool_input = {
        "entries": entries,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    layout = _get_layout(data)
    records = data.get("inventory", [])
    record_map = {}
    for rec in records:
        try:
            record_map[int(rec.get("id"))] = rec
        except Exception:
            continue

    normalized_entries = []
    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=f"entries[{idx}] must be an object",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}]"},
            )
        record_id = entry.get("record_id")
        if record_id in (None, ""):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=f"entries[{idx}].record_id is required",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].record_id"},
            )
        rid = int(record_id)
        try:
            from_box, from_pos = _parse_slot_payload(entry.get("from"), layout=layout, field_name=f"entries[{idx}].from")
            to_box, to_pos = _parse_slot_payload(entry.get("to"), layout=layout, field_name=f"entries[{idx}].to")
        except ValueError as exc:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message=str(exc),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx},
            )
        if not validate_box(from_box, layout):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].from.box {from_box} is out of range ({_format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].from.box"},
            )
        if not validate_box(to_box, layout):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].to.box {to_box} is out of range ({_format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].to.box"},
            )

        issue = _validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Source slot validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, **(issue.get("details") or {})},
            )
        normalized_entries.append((rid, from_pos, to_pos, to_box))

    return _tool_batch_takeout_impl(
        yaml_path=yaml_path,
        entries=normalized_entries,
        date_str=date_str,
        action="move",
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def _tool_batch_takeout_impl(
    yaml_path,
    entries,
    date_str,
    action="takeout",
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._tool_batch_takeout_impl(
        yaml_path=yaml_path,
        entries=entries,
        date_str=date_str,
        action=action,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )

def tool_list_backups(yaml_path):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops.tool_list_backups(yaml_path=yaml_path)


def tool_rollback(
    yaml_path,
    backup_path=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    source_event=None,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops.tool_rollback(
        yaml_path=yaml_path,
        backup_path=backup_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        source_event=source_event,
    )


def tool_adjust_box_count(
    yaml_path,
    operation,
    count=1,
    box=None,
    renumber_mode=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    return _tool_adjust_box_count_impl(
        yaml_path=yaml_path,
        operation=operation,
        count=count,
        box=box,
        renumber_mode=renumber_mode,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )


def _tool_adjust_box_count_impl(
    yaml_path,
    operation,
    count=1,
    box=None,
    renumber_mode=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
):
    from .tool_api_impl import write_ops as _write_ops

    return _write_ops._tool_adjust_box_count_impl(
        yaml_path=yaml_path,
        operation=operation,
        count=count,
        box=box,
        renumber_mode=renumber_mode,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
    )

def tool_export_inventory_csv(yaml_path, output_path):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_export_inventory_csv(
        yaml_path=yaml_path,
        output_path=output_path,
    )


def tool_list_empty_positions(yaml_path, box=None):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_list_empty_positions(
        yaml_path=yaml_path,
        box=box,
    )


def _record_search_blob(record, case_sensitive=False):
    """Build a normalized text blob from one inventory record for matching."""
    parts = []
    for value in (record or {}).values():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            parts.append(str(value))
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (str, int, float, bool)):
                    parts.append(str(item))
    blob = " ".join(parts)
    return blob if case_sensitive else blob.lower()


def _parse_search_location_shortcut(query_text, layout):
    """Parse compact location query like ``2:15`` into (box, position)."""
    text = str(query_text or "").strip()
    if not text:
        return None

    match = re.match(r"^(?:box\s*)?([^:\s]+)\s*[:：]\s*([^:\s]+)$", text, flags=re.IGNORECASE)
    if not match:
        return None

    raw_box, raw_position = match.group(1), match.group(2)
    try:
        box_num = int(display_to_box(raw_box, layout))
        pos_num = int(display_to_pos(raw_position, layout))
    except Exception:
        return None

    if not validate_box(box_num, layout):
        return None
    if not validate_position(pos_num, layout):
        return None
    return box_num, pos_num


def tool_search_records(
    yaml_path,
    query=None,
    mode="fuzzy",
    max_results=None,
    case_sensitive=False,
    box=None,
    position=None,
    record_id=None,
    active_only=None,
):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_search_records(
        yaml_path=yaml_path,
        query=query,
        mode=mode,
        max_results=max_results,
        case_sensitive=case_sensitive,
        box=box,
        position=position,
        record_id=record_id,
        active_only=active_only,
    )


def tool_recent_frozen(yaml_path, days=None, count=None):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_recent_frozen(
        yaml_path=yaml_path,
        days=days,
        count=count,
    )


def tool_query_takeout_events(
    yaml_path,
    date=None,
    days=None,
    start_date=None,
    end_date=None,
    action=None,
    max_records=0,
):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_query_takeout_events(
        yaml_path=yaml_path,
        date=date,
        days=days,
        start_date=start_date,
        end_date=end_date,
        action=action,
        max_records=max_records,
    )


def tool_migrate_takeout_actions(
    yaml_path,
    dry_run=False,
    auto_backup=True,
):
    """One-click migration for legacy thaw/discard events.

    Converts stored event actions to canonical values:
    - thaw/discard -> takeout
    - takeout/move stay unchanged
    """
    return migrate_takeout_actions(
        yaml_path=yaml_path,
        dry_run=bool(dry_run),
        auto_backup=bool(auto_backup),
        audit_source="tool_api",
    )


def _collect_timeline_events(records, days=None):
    timeline = defaultdict(lambda: {"frozen": [], "takeout": [], "move": []})
    cutoff_str = None
    if days:
        cutoff_str = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    for rec in records:
        frozen_at = rec.get("frozen_at")
        if frozen_at and (not cutoff_str or frozen_at >= cutoff_str):
            timeline[frozen_at]["frozen"].append(rec)

    for rec in records:
        for ev in extract_events(rec):
            date = ev.get("date")
            if not date:
                continue
            if cutoff_str and date < cutoff_str:
                continue
            action = ev.get("action")
            if action not in {"takeout", "move"}:
                continue
            timeline[date][action].append({**ev, "record": rec})
    return timeline


def tool_collect_timeline(yaml_path, days=30, all_history=False):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_collect_timeline(
        yaml_path=yaml_path,
        days=days,
        all_history=all_history,
    )


def _find_consecutive_slots(empty_positions, count):
    if not empty_positions or count <= 0:
        return []
    groups = []
    current = [empty_positions[0]]
    for i in range(1, len(empty_positions)):
        if empty_positions[i] == current[-1] + 1:
            current.append(empty_positions[i])
        else:
            if len(current) >= count:
                groups.append(current[:count])
            current = [empty_positions[i]]
    if len(current) >= count:
        groups.append(current[:count])
    return groups


def _find_same_row_slots(empty_positions, count, layout):
    cols = int(layout.get("cols", 9))
    row_groups = {}
    for pos in empty_positions:
        row = (pos - 1) // cols
        row_groups.setdefault(row, []).append(pos)

    groups = []
    for _, positions in sorted(row_groups.items()):
        if len(positions) < count:
            continue
        consecutive = _find_consecutive_slots(positions, count)
        if consecutive:
            groups.extend(consecutive)
        else:
            groups.append(sorted(positions)[:count])
    return groups


def tool_recommend_positions(yaml_path, count, box_preference=None, strategy="consecutive"):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_recommend_positions(
        yaml_path=yaml_path,
        count=count,
        box_preference=box_preference,
        strategy=strategy,
    )


def tool_generate_stats(yaml_path):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_generate_stats(
        yaml_path=yaml_path,
    )


def tool_get_raw_entries(yaml_path, ids):
    from .tool_api_impl import read_ops as _read_ops

    return _read_ops.tool_get_raw_entries(
        yaml_path=yaml_path,
        ids=ids,
    )
