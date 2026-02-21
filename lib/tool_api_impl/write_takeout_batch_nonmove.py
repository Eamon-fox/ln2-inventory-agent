"""Batch non-move helpers for Tool API write operations."""

from copy import deepcopy

from ..operations import find_record_by_id
from ..yaml_ops import write_yaml
from .write_common import (
    api,
    append_record_events_or_failure,
    build_batch_write_details,
    build_integrity_failure,
    build_write_failed_result,
    get_candidate_inventory_or_failure,
)


def _resolve_nonmove_position_or_error(
    *,
    entry,
    record_id,
    current_position,
    pos_lo,
    pos_hi,
):
    if len(entry) == 2:
        position = entry[1]
        if position < pos_lo or position > pos_hi:
            return None, f"ID {record_id}: position {position} must be within {pos_lo}-{pos_hi}"
        if current_position is not None and position != current_position:
            return None, (
                f"ID {record_id}: position {position} does not match current position {current_position}"
            )
        return position, None

    if current_position is None:
        return None, f"ID {record_id}: record has no active position; please use id:position"

    position = current_position
    if position < pos_lo or position > pos_hi:
        return None, f"ID {record_id}: position {position} must be within {pos_lo}-{pos_hi}"
    return position, None


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
        position, error = _resolve_nonmove_position_or_error(
            entry=entry,
            record_id=record_id,
            current_position=current_position,
            pos_lo=pos_lo,
            pos_hi=pos_hi,
        )
        if error:
            errors.append(error)
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
    details = build_batch_write_details(operations=operations, action_en=action_en, date_str=date_str)
    try:
        candidate_data = deepcopy(data)
        candidate_records, failure = get_candidate_inventory_or_failure(
            candidate_data=candidate_data,
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )
        if failure:
            return None, failure

        for op in operations:
            idx = op["idx"]
            position = op["position"]
            candidate_records[idx]["position"] = op["new_position"]

            new_event = {
                "date": date_str,
                "action": action_en,
                "positions": [position],
            }
            failure = append_record_events_or_failure(
                candidate_data=candidate_data,
                candidate_records=candidate_records,
                record_index=idx,
                new_events=[new_event],
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
            )
            if failure:
                return None, failure

        if api._validate_data_or_error(candidate_data):
            return None, build_integrity_failure(
                candidate_data=candidate_data,
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details=details,
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
                    **details,
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
        return None, build_write_failed_result(
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            exc=exc,
            message_prefix="Batch update failed",
            details=details,
        )

    return _backup_path, None
