"""Batch non-move helpers for Tool API write operations."""

from copy import deepcopy

from ..operations import find_record_by_id
from ..yaml_ops import write_yaml
from .write_common import api


def _build_batch_nonmove_plan(
    *,
    records,
    normalized_entries,
    pos_lo,
    pos_hi,
):
    operations = []
    errors = []
    seen_nonmove_entries = set()

    for row_idx, entry in enumerate(normalized_entries, 1):
        if len(entry) not in (1, 2):
            errors.append(f"Row {row_idx}: non-move entries must use id or id:position")
            continue

        record_id = entry[0]

        idx, record = find_record_by_id(records, record_id)
        if record is None:
            errors.append(f"ID {record_id}: record not found")
            continue

        current_position = record.get("position")

        if len(entry) == 2:
            position = entry[1]
            if position < pos_lo or position > pos_hi:
                errors.append(f"ID {record_id}: position {position} must be within {pos_lo}-{pos_hi}")
                continue
            if current_position is not None and position != current_position:
                errors.append(
                    f"ID {record_id}: position {position} does not match current position {current_position}"
                )
                continue
        else:
            if current_position is None:
                errors.append(
                    f"ID {record_id}: record has no active position; please use id:position"
                )
                continue
            position = current_position
            if position < pos_lo or position > pos_hi:
                errors.append(f"ID {record_id}: position {position} must be within {pos_lo}-{pos_hi}")
                continue

        entry_key = (record_id, position)
        if entry_key in seen_nonmove_entries:
            errors.append(f"ID {record_id}: duplicate position {position} in this batch")
            continue
        seen_nonmove_entries.add(entry_key)

        operations.append(
            {
                "idx": idx,
                "record_id": record_id,
                "record": record,
                "position": position,
                "old_position": current_position,
                "new_position": None,
            }
        )

    return {
        "operations": operations,
        "errors": errors,
    }


def _persist_batch_nonmove_plan(
    *,
    data,
    normalized_entries,
    operations,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    action,
    action_en,
    date_str,
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
            return None, api._failure_result(
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

        for op in operations:
            idx = op["idx"]
            position = op["position"]
            candidate_records[idx]["position"] = op["new_position"]

            new_event = {
                "date": date_str,
                "action": action_en,
                "positions": [position],
            }
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
                return None, api._failure_result(
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

        validation_error = api._validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, api._failure_result(
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
                details={"count": len(operations), "action": action_en, "date": date_str},
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
                    "count": len(operations),
                    "action": action_en,
                    "date": date_str,
                    "record_ids": [op["record_id"] for op in operations],
                },
                tool_input={
                    "entries": list(normalized_entries),
                    "date": date_str,
                    "action": action,
                },
            ),
        )
    except Exception as exc:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Batch update failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"count": len(operations), "action": action_en, "date": date_str},
        )

    return _backup_path, None
