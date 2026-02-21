"""Single takeout/move write-operation implementations for Tool API."""

from copy import deepcopy

from ..operations import find_record_by_id
from ..position_fmt import get_position_range
from ..takeout_parser import ACTION_LABEL, normalize_action
from ..validators import validate_box
from ..yaml_ops import load_yaml, write_yaml
from .write_common import api

def _prepare_record_takeout_request(
    *,
    data,
    record_id,
    position,
    move_to_position,
    action_en,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    records = data.get("inventory", [])
    layout = api._get_layout(data)
    _pos_lo, _pos_hi = get_position_range(layout)

    if move_to_position is not None:
        try:
            move_to_position = api._coerce_position_value(
                move_to_position,
                layout=layout,
                field_name="to_position",
            )
        except ValueError:
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_move_target",
                message=f"Invalid target position: {move_to_position}",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"to_position": move_to_position},
            )

    if move_to_position is not None and (move_to_position < _pos_lo or move_to_position > _pos_hi):
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_position",
            message=f"Target position must be between {_pos_lo}-{_pos_hi}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"to_position": move_to_position},
        )

    idx, record = find_record_by_id(records, record_id)
    if record is None:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="record_not_found",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"record_id": record_id},
        )

    current_position = record.get("position")
    if position in ("", "auto"):
        position = None

    if position is None:
        if current_position is None:
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="position_not_found",
                message="Validation failed",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"record_id": record_id},
                extra={"current_position": current_position},
            )
        position = current_position

    try:
        position = api._coerce_position_value(position, layout=layout, field_name="position")
    except ValueError:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_position",
            message=f"Invalid position: {position}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"record_id": record_id, "position": position},
        )

    if position < _pos_lo or position > _pos_hi:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_position",
            message=f"Position must be between {_pos_lo}-{_pos_hi}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"position": position},
        )

    if current_position is not None and position != current_position:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="position_not_found",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"record_id": record_id, "position": position},
            extra={"current_position": current_position},
        )

    if action_en == "move" and move_to_position == position:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_move_target",
            message="Move source and target positions cannot be the same",
            actor_context=actor_context,
            tool_input=tool_input,
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
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    data,
):
    swap_target = None
    swap_target_new_position = None
    swap_target_event = None

    if action_en == "move":
        new_position = move_to_position
        box = record.get("box")
        cross_box = to_box is not None and to_box != box

        if cross_box:
            if not validate_box(to_box, layout):
                return None, api._failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code="invalid_box",
                    message=f"Target box {to_box} is out of range ({api._format_box_constraint(layout)})",
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    details={"to_box": to_box},
                )
            target_box = to_box
            for other_idx, other in enumerate(records):
                if other.get("box") != target_box:
                    continue
                other_position = other.get("position")
                if other_position == move_to_position:
                    return None, api._failure_result(
                        yaml_path=yaml_path,
                        action=audit_action,
                        source=source,
                        tool_name=tool_name,
                        error_code="position_conflict",
                        message=f"Target box {target_box} position {move_to_position} is occupied by record #{other.get('id')}",
                        actor_context=actor_context,
                        tool_input=tool_input,
                        before_data=data,
                        details={
                            "record_id": record_id,
                            "to_box": target_box,
                            "to_position": move_to_position,
                            "blocking_record_id": other.get("id"),
                        },
                    )
        else:
            for other_idx, other in enumerate(records):
                if other.get("box") != box:
                    continue
                other_position = other.get("position")
                if other_position == move_to_position:
                    if other_idx == idx:
                        return None, api._failure_result(
                            yaml_path=yaml_path,
                            action=audit_action,
                            source=source,
                            tool_name=tool_name,
                            error_code="invalid_move_target",
                            message=f"Target position {move_to_position} already belongs to record #{record_id}; no move needed",
                            actor_context=actor_context,
                            tool_input=tool_input,
                            before_data=data,
                            details={"record_id": record_id, "to_position": move_to_position},
                        )

                    swap_target_new_position = position
                    swap_target = {
                        "idx": other_idx,
                        "record": other,
                        "old_position": other_position,
                    }
                    break

        new_event = api._build_move_event(
            date_str=date_str,
            from_position=position,
            to_position=move_to_position,
            paired_record_id=swap_target["record"].get("id") if swap_target else None,
            from_box=box if cross_box else None,
            to_box=to_box if cross_box else None,
        )
        if swap_target:
            swap_target_event = api._build_move_event(
                date_str=date_str,
                from_position=move_to_position,
                to_position=position,
                paired_record_id=record_id,
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
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    auto_backup,
):
    try:
        candidate_data = deepcopy(data)
        candidate_records = candidate_data.get("inventory", [])
        if not isinstance(candidate_records, list):
            validation_error = api._validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "Validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )

        candidate_records[idx]["position"] = new_position
        if to_box is not None and to_box != record.get("box"):
            candidate_records[idx]["box"] = to_box
        thaw_events = candidate_records[idx].get("thaw_events")
        if thaw_events is None:
            candidate_records[idx]["thaw_events"] = []
            thaw_events = candidate_records[idx]["thaw_events"]
        if not isinstance(thaw_events, list):
            validation_error = api._validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "Validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )
        thaw_events.append(new_event)

        affected_record_ids = [record_id]
        if swap_target:
            swap_idx = swap_target["idx"]
            candidate_records[swap_idx]["position"] = swap_target_new_position
            swap_events = candidate_records[swap_idx].get("thaw_events")
            if swap_events is None:
                candidate_records[swap_idx]["thaw_events"] = []
                swap_events = candidate_records[swap_idx]["thaw_events"]
            if not isinstance(swap_events, list):
                validation_error = api._validate_data_or_error(candidate_data) or {
                    "error_code": "integrity_validation_failed",
                    "message": "Validation failed",
                    "errors": [],
                }
                return None, None, api._failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code=validation_error.get("error_code", "integrity_validation_failed"),
                    message=validation_error.get("message", "Validation failed"),
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    errors=validation_error.get("errors"),
                )
            swap_events.append(swap_target_event)
            affected_record_ids.append(swap_target["record"].get("id"))

        validation_error = api._validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "Validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
                details={
                    "record_id": record_id,
                    "position": position,
                    "to_position": move_to_position,
                    "action": action_en,
                    "date": date_str,
                },
            )

        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            audit_meta=api._build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details={
                    "record_id": record_id,
                    "box": record.get("box"),
                    "position": position,
                    "to_position": move_to_position,
                    "action": action_en,
                    "date": date_str,
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
        return None, None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Update failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={
                "record_id": record_id,
                "position": position,
                "to_position": move_to_position,
                "action": action_en,
            },
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
        return api._failure_result(
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

    prepared, failure = _prepare_record_takeout_request(
        data=data,
        record_id=record_id,
        position=position,
        move_to_position=move_to_position,
        action_en=action_en,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
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
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        data=data,
    )
    if failure:
        return failure

    new_position = transition["new_position"]
    new_event = transition["new_event"]
    swap_target = transition["swap_target"]
    swap_target_new_position = transition["swap_target_new_position"]
    swap_target_event = transition["swap_target_event"]

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
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        auto_backup=auto_backup,
    )
    if failure:
        return failure

    result_payload = {
        "record_id": record_id,
        "remaining_position": new_position,
    }
    if move_to_position is not None:
        result_payload["to_position"] = move_to_position
    if swap_target:
        result_payload["swap_with_record_id"] = swap_target["record"].get("id")

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": result_payload,
        "backup_path": _backup_path,
    }

