"""Unified Tool API shared by CLI, GUI, and AI agents."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from .position_fmt import (
    get_box_numbers,
)
from .migrate_takeout_actions import migrate_takeout_actions
from .takeout_parser import extract_events
from .validators import (
    format_validation_errors,
    validate_inventory,
)
from .yaml_ops import (
    append_audit_event,
    load_yaml,
)
from . import tool_api_parsers as _parsers
from . import tool_api_write_validation as _write_validation
from . import tool_api_write_v2 as _write_v2


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
    session_id=None,
    trace_id=None,
):
    """Build trace/session context for unified audit records."""
    return {
        "session_id": session_id or _DEFAULT_SESSION_ID,
        "trace_id": trace_id,
    }


_coerce_position_value = _parsers._coerce_position_value
_normalize_positions_input = _parsers._normalize_positions_input
parse_batch_entries = _parsers.parse_batch_entries
_coerce_batch_entry = _parsers._coerce_batch_entry
_parse_slot_payload = _parsers._parse_slot_payload
_format_positions_in_payload = _parsers._format_positions_in_payload
_find_record_by_id_local = _parsers._find_record_by_id_local
_validate_source_slot_match = _parsers._validate_source_slot_match


def _format_tool_response_positions(response, *, yaml_path=None, layout=None):
    """Render position fields in one tool response as display strings."""
    if not isinstance(response, dict):
        return response

    resolved_layout = layout or {}
    if not resolved_layout and yaml_path:
        try:
            resolved_layout = _get_layout(load_yaml(yaml_path))
        except Exception:
            resolved_layout = {}
    return _format_positions_in_payload(response, layout=resolved_layout)


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
    ctx = dict(build_actor_context())
    ctx.update(actor_context or {})
    if not ctx.get("trace_id"):
        ctx["trace_id"] = f"trace-{uuid.uuid4().hex}"
    if not ctx.get("session_id"):
        ctx["session_id"] = _DEFAULT_SESSION_ID

    return {
        "action": action,
        "source": source,
        "tool_name": tool_name,
        "session_id": ctx.get("session_id"),
        "trace_id": ctx.get("trace_id"),
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
    layout = _get_layout(before_data) if isinstance(before_data, dict) else {}
    return _format_positions_in_payload(payload, layout=layout)


_ALLOWED_EXECUTION_MODES = _write_validation._ALLOWED_EXECUTION_MODES
_normalize_execution_mode = _write_validation._normalize_execution_mode
_enforce_execute_mode_for_source = _write_validation._enforce_execute_mode_for_source
_validate_execution_gate = _write_validation._validate_execution_gate
_validate_add_entry_request = _write_validation._validate_add_entry_request
_validate_edit_entry_request = _write_validation._validate_edit_entry_request
_validate_record_takeout_request = _write_validation._validate_record_takeout_request
_validate_batch_takeout_request = _write_validation._validate_batch_takeout_request
_validate_adjust_box_count_request = _write_validation._validate_adjust_box_count_request
_WRITE_REQUEST_VALIDATORS = _write_validation._WRITE_REQUEST_VALIDATORS


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
    auto_backup=True,
    request_backup_path=None,
):
    return _write_validation.validate_write_tool_call(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload=payload,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        before_data=before_data,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
        failure_result_fn=_failure_result,
    )


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
    request_backup_path=None,
):
    response = _tool_add_entry_impl(
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
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_add_entry_impl(
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
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_edit_entry(
        yaml_path=yaml_path,
        record_id=record_id,
        fields=fields,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


tool_record_takeout = _write_v2.tool_record_takeout
tool_record_move = _write_v2.tool_record_move
_tool_record_takeout_impl = _write_v2._tool_record_takeout_impl
tool_batch_takeout = _write_v2.tool_batch_takeout
tool_batch_move = _write_v2.tool_batch_move
_tool_batch_takeout_impl = _write_v2._tool_batch_takeout_impl

def tool_list_backups(yaml_path):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_list_backups(yaml_path=yaml_path)
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_rollback(
    yaml_path,
    backup_path=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    source_event=None,
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops.tool_rollback(
        yaml_path=yaml_path,
        backup_path=backup_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        source_event=source_event,
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    request_backup_path=None,
):
    response = _tool_adjust_box_count_impl(
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
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    request_backup_path=None,
):
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_adjust_box_count_impl(
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
        request_backup_path=request_backup_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)

def tool_export_inventory_csv(yaml_path, output_path):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_export_inventory_csv(
        yaml_path=yaml_path,
        output_path=output_path,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_list_empty_positions(yaml_path, box=None):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_list_empty_positions(
        yaml_path=yaml_path,
        box=box,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


_record_search_blob = _parsers._record_search_blob


_parse_search_location_shortcut = _parsers._parse_search_location_shortcut

def tool_search_records(
    yaml_path,
    query=None,
    mode="fuzzy",
    max_results=None,
    case_sensitive=False,
    box=None,
    position=None,
    record_id=None,
    active_only=True,
):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_search_records(
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
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_recent_frozen(yaml_path, days=None, count=None):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_recent_frozen(
        yaml_path=yaml_path,
        days=days,
        count=count,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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

    response = _read_ops.tool_query_takeout_events(
        yaml_path=yaml_path,
        date=date,
        days=days,
        start_date=start_date,
        end_date=end_date,
        action=action,
        max_records=max_records,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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
    response = migrate_takeout_actions(
        yaml_path=yaml_path,
        dry_run=bool(dry_run),
        auto_backup=bool(auto_backup),
        audit_source="tool_api",
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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

    response = _read_ops.tool_collect_timeline(
        yaml_path=yaml_path,
        days=days,
        all_history=all_history,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


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

    response = _read_ops.tool_recommend_positions(
        yaml_path=yaml_path,
        count=count,
        box_preference=box_preference,
        strategy=strategy,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_generate_stats(yaml_path, box=None, include_inactive=False):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_generate_stats(
        yaml_path=yaml_path,
        box=box,
        include_inactive=include_inactive,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)


def tool_get_raw_entries(yaml_path, ids):
    from .tool_api_impl import read_ops as _read_ops

    response = _read_ops.tool_get_raw_entries(
        yaml_path=yaml_path,
        ids=ids,
    )
    return _format_tool_response_positions(response, yaml_path=yaml_path)
