"""Single takeout/move write-operation implementations for Tool API."""

from copy import deepcopy

from ..operations import find_record_by_id
from ..position_fmt import get_position_range
from ..takeout_parser import ACTION_LABEL, normalize_action
from ..validators import validate_box
from ..yaml_ops import load_yaml, write_yaml
from .write_common import (
    api,
    append_record_events_or_failure,
    build_integrity_failure,
    build_write_failed_result,
    get_candidate_inventory_or_failure,
)


def _single_failure(
    *,
    ctx,
    error_code,
    message,
    before_data=None,
    details=None,
    extra=None,
    errors=None,
):
    return api._failure_result(
        yaml_path=ctx["yaml_path"],
        action=ctx["audit_action"],
        source=ctx["source"],
        tool_name=ctx["tool_name"],
        error_code=error_code,
        message=message,
        actor_context=ctx["actor_context"],
        tool_input=ctx["tool_input"],
        before_data=before_data,
        details=details,
        extra=extra,
        errors=errors,
    )


def _build_record_takeout_preview(
    *,
    record_id,
    record,
    action_en,
    action_cn,
    position,
    move_to_position,
    to_box,
    date_str,
    current_position,
    new_position,
    swap_target,
    swap_target_new_position,
):
    preview = {
        "record_id": record_id,
        "cell_line": record.get("cell_line"),
        "short_name": record.get("short_name"),
        "box": record.get("box"),
        "action_en": action_en,
        "action_cn": action_cn,
        "position": position,
        "to_position": move_to_position,
        "to_box": to_box,
        "date": date_str,
        "position_before": current_position,
        "position_after": new_position,
    }
    if swap_target:
        preview["swap_with_record_id"] = swap_target["record"].get("id")
        preview["swap_with_short_name"] = swap_target["record"].get("short_name")
        preview["swap_position_before"] = swap_target["old_position"]
        preview["swap_position_after"] = swap_target_new_position
    return preview


def _build_record_takeout_result(*, record_id, new_position, move_to_position, swap_target):
    result_payload = {
        "record_id": record_id,
        "remaining_position": new_position,
    }
    if move_to_position is not None:
        result_payload["to_position"] = move_to_position
    if swap_target:
        result_payload["swap_with_record_id"] = swap_target["record"].get("id")
    return result_payload


def _coerce_move_target_or_failure(*, move_to_position, layout, pos_lo, pos_hi, ctx, data):
    if move_to_position is None:
        return None, None

    try:
        move_to_position = api._coerce_position_value(
            move_to_position,
            layout=layout,
            field_name="to_position",
        )
    except ValueError:
        return None, _single_failure(
            ctx=ctx,
            error_code="invalid_move_target",
            message=f"Invalid target position: {move_to_position}",
            before_data=data,
            details={"to_position": move_to_position},
        )

    if move_to_position < pos_lo or move_to_position > pos_hi:
        return None, _single_failure(
            ctx=ctx,
            error_code="invalid_position",
            message=f"Target position must be between {pos_lo}-{pos_hi}",
            before_data=data,
            details={"to_position": move_to_position},
        )

    return move_to_position, None


def _resolve_source_position_or_failure(
    *,
    position,
    current_position,
    record_id,
    layout,
    pos_lo,
    pos_hi,
    ctx,
    data,
):
    if position in ("", "auto"):
        position = None

    if position is None:
        if current_position is None:
            return None, _single_failure(
                ctx=ctx,
                error_code="position_not_found",
                message="Validation failed",
                before_data=data,
                details={"record_id": record_id},
                extra={"current_position": current_position},
            )
        position = current_position

    try:
        position = api._coerce_position_value(position, layout=layout, field_name="position")
    except ValueError:
        return None, _single_failure(
            ctx=ctx,
            error_code="invalid_position",
            message=f"Invalid position: {position}",
            before_data=data,
            details={"record_id": record_id, "position": position},
        )

    if position < pos_lo or position > pos_hi:
        return None, _single_failure(
            ctx=ctx,
            error_code="invalid_position",
            message=f"Position must be between {pos_lo}-{pos_hi}",
            details={"position": position},
        )

    if current_position is not None and position != current_position:
        return None, _single_failure(
            ctx=ctx,
            error_code="position_not_found",
            message="Validation failed",
            before_data=data,
            details={"record_id": record_id, "position": position},
            extra={"current_position": current_position},
        )

    return position, None


def _prepare_record_takeout_request(
    *,
    data,
    record_id,
    position,
    move_to_position,
    action_en,
    ctx,
):
    records = data.get("inventory", [])
    layout = api._get_layout(data)
    _pos_lo, _pos_hi = get_position_range(layout)

    move_to_position, failure = _coerce_move_target_or_failure(
        move_to_position=move_to_position,
        layout=layout,
        pos_lo=_pos_lo,
        pos_hi=_pos_hi,
        ctx=ctx,
        data=data,
    )
    if failure:
        return None, failure

    idx, record = find_record_by_id(records, record_id)
    if record is None:
        return None, _single_failure(
            ctx=ctx,
            error_code="record_not_found",
            message="Validation failed",
            before_data=data,
            details={"record_id": record_id},
        )

    current_position = record.get("position")
    position, failure = _resolve_source_position_or_failure(
        position=position,
        current_position=current_position,
        record_id=record_id,
        layout=layout,
        pos_lo=_pos_lo,
        pos_hi=_pos_hi,
        ctx=ctx,
        data=data,
    )
    if failure:
        return None, failure

    if action_en == "move" and move_to_position == position:
        return None, _single_failure(
            ctx=ctx,
            error_code="invalid_move_target",
            message="Move source and target positions cannot be the same",
            details={"position": position, "to_position": move_to_position},
        )

    return {
        "records": records,
        "layout": layout,
        "idx": idx,
        "record": record,
        "current_position": current_position,
        "position": position,
        "move_to_position": move_to_position,
    }, None


def _validate_cross_box_move_target_or_failure(
    *,
    to_box,
    layout,
    records,
    move_to_position,
    record_id,
    data,
    ctx,
):
    if not validate_box(to_box, layout):
        return _single_failure(
            ctx=ctx,
            error_code="invalid_box",
            message=f"Target box {to_box} is out of range ({api._format_box_constraint(layout)})",
            before_data=data,
            details={"to_box": to_box},
        )

    target_box = to_box
    for other in records:
        if other.get("box") != target_box:
            continue
        if other.get("position") == move_to_position:
            return _single_failure(
                ctx=ctx,
                error_code="position_conflict",
                message=(
                    f"Target box {target_box} position {move_to_position} "
                    f"is occupied by record #{other.get('id')}"
                ),
                before_data=data,
                details={
                    "record_id": record_id,
                    "to_box": target_box,
                    "to_position": move_to_position,
                    "blocking_record_id": other.get("id"),
                },
            )

    return None


def _resolve_same_box_swap_or_failure(
    *,
    records,
    idx,
    box,
    move_to_position,
    record_id,
    position,
    data,
    ctx,
):
    for other_idx, other in enumerate(records):
        if other.get("box") != box:
            continue
        other_position = other.get("position")
        if other_position != move_to_position:
            continue

        if other_idx == idx:
            return None, None, _single_failure(
                ctx=ctx,
                error_code="invalid_move_target",
                message=(
                    f"Target position {move_to_position} already belongs to "
                    f"record #{record_id}; no move needed"
                ),
                before_data=data,
                details={"record_id": record_id, "to_position": move_to_position},
            )

        return {
            "idx": other_idx,
            "record": other,
            "old_position": other_position,
        }, position, None

    return None, None, None


def _build_move_events(
    *,
    date_str,
    position,
    move_to_position,
    record_id,
    box,
    to_box,
    cross_box,
    swap_target,
):
    new_event = api._build_move_event(
        date_str=date_str,
        from_position=position,
        to_position=move_to_position,
        paired_record_id=swap_target["record"].get("id") if swap_target else None,
        from_box=box if cross_box else None,
        to_box=to_box if cross_box else None,
    )
    swap_target_event = None
    if swap_target:
        swap_target_event = api._build_move_event(
            date_str=date_str,
            from_position=move_to_position,
            to_position=position,
            paired_record_id=record_id,
        )
    return new_event, swap_target_event


def _single_takeout_details(*, record_id, position, move_to_position, action_en, date_str=None):
    details = {
        "record_id": record_id,
        "position": position,
        "to_position": move_to_position,
        "action": action_en,
    }
    if date_str is not None:
        details["date"] = date_str
    return details


def _append_events_or_failure(*, candidate_data, candidate_records, record_index, new_events, data, ctx):
    return append_record_events_or_failure(
        candidate_data=candidate_data,
        candidate_records=candidate_records,
        record_index=record_index,
        new_events=new_events,
        yaml_path=ctx["yaml_path"],
        audit_action=ctx["audit_action"],
        source=ctx["source"],
        tool_name=ctx["tool_name"],
        actor_context=ctx["actor_context"],
        tool_input=ctx["tool_input"],
        before_data=data,
    )


def _apply_primary_record_update_or_failure(
    *,
    candidate_data,
    candidate_records,
    idx,
    record,
    new_position,
    to_box,
    new_event,
    data,
    ctx,
):
    candidate_records[idx]["position"] = new_position
    if to_box is not None and to_box != record.get("box"):
        candidate_records[idx]["box"] = to_box
    return _append_events_or_failure(
        candidate_data=candidate_data,
        candidate_records=candidate_records,
        record_index=idx,
        new_events=[new_event],
        data=data,
        ctx=ctx,
    )


def _apply_swap_record_update_or_failure(
    *,
    candidate_data,
    candidate_records,
    swap_target,
    swap_target_new_position,
    swap_target_event,
    record_id,
    data,
    ctx,
):
    affected_record_ids = [record_id]
    if not swap_target:
        return affected_record_ids, None

    swap_idx = swap_target["idx"]
    candidate_records[swap_idx]["position"] = swap_target_new_position
    failure = _append_events_or_failure(
        candidate_data=candidate_data,
        candidate_records=candidate_records,
        record_index=swap_idx,
        new_events=[swap_target_event],
        data=data,
        ctx=ctx,
    )
    if failure:
        return None, failure

    affected_record_ids.append(swap_target["record"].get("id"))
    return affected_record_ids, None


def _plan_record_takeout_transition(
    *,
    records,
    idx,
    record,
    record_id,
    position,
    move_to_position,
    to_box,
    action_en,
    date_str,
    layout,
    data,
    ctx,
):
    swap_target = None
    swap_target_new_position = None
    swap_target_event = None

    if action_en == "move":
        new_position = move_to_position
        box = record.get("box")
        cross_box = to_box is not None and to_box != box

        if cross_box:
            failure = _validate_cross_box_move_target_or_failure(
                to_box=to_box,
                layout=layout,
                records=records,
                move_to_position=move_to_position,
                record_id=record_id,
                data=data,
                ctx=ctx,
            )
            if failure:
                return None, failure
        else:
            swap_target, swap_target_new_position, failure = _resolve_same_box_swap_or_failure(
                records=records,
                idx=idx,
                box=box,
                move_to_position=move_to_position,
                record_id=record_id,
                position=position,
                data=data,
                ctx=ctx,
            )
            if failure:
                return None, failure

        new_event, swap_target_event = _build_move_events(
            date_str=date_str,
            position=position,
            move_to_position=move_to_position,
            record_id=record_id,
            box=box,
            to_box=to_box,
            cross_box=cross_box,
            swap_target=swap_target,
        )
    else:
        new_position = None
        new_event = {"date": date_str, "action": action_en, "positions": [position]}

    return {
        "new_position": new_position,
        "new_event": new_event,
        "swap_target": swap_target,
        "swap_target_new_position": swap_target_new_position,
        "swap_target_event": swap_target_event,
    }, None


def _persist_record_takeout(
    *,
    data,
    idx,
    record,
    record_id,
    position,
    new_position,
    to_box,
    new_event,
    swap_target,
    swap_target_new_position,
    swap_target_event,
    move_to_position,
    action_en,
    action,
    date_str,
    ctx,
    auto_backup,
):
    details = _single_takeout_details(
        record_id=record_id,
        position=position,
        move_to_position=move_to_position,
        action_en=action_en,
        date_str=date_str,
    )
    try:
        candidate_data = deepcopy(data)
        candidate_records, failure = get_candidate_inventory_or_failure(
            candidate_data=candidate_data,
            yaml_path=ctx["yaml_path"],
            audit_action=ctx["audit_action"],
            source=ctx["source"],
            tool_name=ctx["tool_name"],
            actor_context=ctx["actor_context"],
            tool_input=ctx["tool_input"],
            before_data=data,
        )
        if failure:
            return None, None, failure

        failure = _apply_primary_record_update_or_failure(
            candidate_data=candidate_data,
            candidate_records=candidate_records,
            idx=idx,
            record=record,
            new_position=new_position,
            to_box=to_box,
            new_event=new_event,
            data=data,
            ctx=ctx,
        )
        if failure:
            return None, None, failure

        affected_record_ids, failure = _apply_swap_record_update_or_failure(
            candidate_data=candidate_data,
            candidate_records=candidate_records,
            swap_target=swap_target,
            swap_target_new_position=swap_target_new_position,
            swap_target_event=swap_target_event,
            record_id=record_id,
            data=data,
            ctx=ctx,
        )
        if failure:
            return None, None, failure

        if api._validate_data_or_error(candidate_data):
            return None, None, build_integrity_failure(
                candidate_data=candidate_data,
                yaml_path=ctx["yaml_path"],
                audit_action=ctx["audit_action"],
                source=ctx["source"],
                tool_name=ctx["tool_name"],
                actor_context=ctx["actor_context"],
                tool_input=ctx["tool_input"],
                before_data=data,
                details=details,
            )

        _backup_path = write_yaml(
            candidate_data,
            ctx["yaml_path"],
            auto_backup=auto_backup,
            audit_meta=api._build_audit_meta(
                action=ctx["audit_action"],
                source=ctx["source"],
                tool_name=ctx["tool_name"],
                actor_context=ctx["actor_context"],
                details={
                    "box": record.get("box"),
                    **details,
                    "affected_record_ids": affected_record_ids,
                },
                tool_input={
                    "record_id": record_id,
                    "position": position,
                    "to_position": move_to_position,
                    "date": date_str,
                    "action": action,
                },
            ),
        )
    except Exception as exc:
        return None, None, build_write_failed_result(
            yaml_path=ctx["yaml_path"],
            audit_action=ctx["audit_action"],
            source=ctx["source"],
            tool_name=ctx["tool_name"],
            actor_context=ctx["actor_context"],
            tool_input=ctx["tool_input"],
            before_data=data,
            exc=exc,
            message_prefix="Update failed",
            details=_single_takeout_details(
                record_id=record_id,
                position=position,
                move_to_position=move_to_position,
                action_en=action_en,
            ),
        )

    return _backup_path, affected_record_ids, None


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
    """Record one takeout/move operation via shared tool flow."""
    audit_action = "record_takeout"
    tool_name = "tool_record_takeout"
    tool_input = {
        "record_id": record_id,
        "position": position,
        "to_position": to_position,
        "to_box": to_box,
        "date": date_str,
        "action": action,
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
    }
    ctx = {
        "yaml_path": yaml_path,
        "audit_action": audit_action,
        "source": source,
        "tool_name": tool_name,
        "actor_context": actor_context,
        "tool_input": tool_input,
    }

    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload={"date_str": date_str, "action": action, "to_position": to_position},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
    )
    if not validation.get("ok"):
        return validation

    normalized = validation.get("normalized") or {}
    action_en = normalized.get("action_en") or normalize_action(action) or ""
    action_cn = ACTION_LABEL.get(action_en, action)
    move_to_position = normalized.get("move_to_position")

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _single_failure(
            ctx=ctx,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            details={"load_error": str(exc)},
        )

    prepared, failure = _prepare_record_takeout_request(
        data=data,
        record_id=record_id,
        position=position,
        move_to_position=move_to_position,
        action_en=action_en,
        ctx=ctx,
    )
    if failure:
        return failure

    records = prepared["records"]
    layout = prepared["layout"]
    idx = prepared["idx"]
    record = prepared["record"]
    current_position = prepared["current_position"]
    position = prepared["position"]
    move_to_position = prepared["move_to_position"]

    transition, failure = _plan_record_takeout_transition(
        records=records,
        idx=idx,
        record=record,
        record_id=record_id,
        position=position,
        move_to_position=move_to_position,
        to_box=to_box,
        action_en=action_en,
        date_str=date_str,
        layout=layout,
        data=data,
        ctx=ctx,
    )
    if failure:
        return failure

    new_position = transition["new_position"]
    new_event = transition["new_event"]
    swap_target = transition["swap_target"]
    swap_target_new_position = transition["swap_target_new_position"]
    swap_target_event = transition["swap_target_event"]

    preview = _build_record_takeout_preview(
        record_id=record_id,
        record=record,
        action_en=action_en,
        action_cn=action_cn,
        position=position,
        move_to_position=move_to_position,
        to_box=to_box,
        date_str=date_str,
        current_position=current_position,
        new_position=new_position,
        swap_target=swap_target,
        swap_target_new_position=swap_target_new_position,
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    _backup_path, _affected_record_ids, failure = _persist_record_takeout(
        data=data,
        idx=idx,
        record=record,
        record_id=record_id,
        position=position,
        new_position=new_position,
        to_box=to_box,
        new_event=new_event,
        swap_target=swap_target,
        swap_target_new_position=swap_target_new_position,
        swap_target_event=swap_target_event,
        move_to_position=move_to_position,
        action_en=action_en,
        action=action,
        date_str=date_str,
        ctx=ctx,
        auto_backup=auto_backup,
    )
    if failure:
        return failure

    result_payload = _build_record_takeout_result(
        record_id=record_id,
        new_position=new_position,
        move_to_position=move_to_position,
        swap_target=swap_target,
    )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": result_payload,
        "backup_path": _backup_path,
    }
