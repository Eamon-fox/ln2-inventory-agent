"""Batch move helpers for Tool API write operations."""

from collections import defaultdict
from copy import deepcopy

from ..operations import find_record_by_id
from ..validators import validate_box
from ..yaml_ops import write_yaml
from .write_common import (
    api,
    append_record_events_or_failure,
    build_batch_write_details,
    build_integrity_failure,
    build_write_failed_result,
    get_candidate_inventory_or_failure,
)


def _seed_move_simulation_state(records):
    simulated_position = {}
    simulated_box = {}
    position_owner = {}
    errors = []

    for idx, rec in enumerate(records):
        rec_position = rec.get("position")
        simulated_position[idx] = rec_position
        box = rec.get("box")
        simulated_box[idx] = box
        if rec_position is None:
            continue
        key = (box, rec_position)
        if key in position_owner and position_owner[key] != idx:
            errors.append(f"Box {box} position {rec_position} is already conflicting; cannot execute move")
        else:
            position_owner[key] = idx

    return simulated_position, simulated_box, position_owner, errors


def _parse_move_entry_or_error(*, entry, row_idx, pos_lo, pos_hi, layout):
    if len(entry) < 3:
        return None, f"Row {row_idx}: move requires id:from->to format"

    record_id, from_pos, to_pos = entry[0], entry[1], entry[2]
    entry_to_box = entry[3] if len(entry) >= 4 else None

    if from_pos < pos_lo or from_pos > pos_hi:
        return None, (
            f"Row {row_idx} ID {record_id}: source position {from_pos} must be within {pos_lo}-{pos_hi}"
        )
    if to_pos < pos_lo or to_pos > pos_hi:
        return None, (
            f"Row {row_idx} ID {record_id}: target position {to_pos} must be within {pos_lo}-{pos_hi}"
        )
    if entry_to_box is not None and not validate_box(entry_to_box, layout):
        return None, (
            f"Row {row_idx} ID {record_id}: target box {entry_to_box} out of range ({api._format_box_constraint(layout)})"
        )

    return {
        "record_id": record_id,
        "from_pos": from_pos,
        "to_pos": to_pos,
        "entry_to_box": entry_to_box,
    }, None


def _resolve_destination_or_error(
    *,
    records,
    row_idx,
    record_id,
    idx,
    cross_box,
    target_box,
    to_pos,
    touched_indices,
    position_owner,
    simulated_position,
    from_pos,
):
    dest_idx = position_owner.get((target_box, to_pos))
    if dest_idx == idx:
        return None, f"Row {row_idx} ID {record_id}: target position {to_pos} already belongs to this record"

    if dest_idx is None:
        return {
            "dest_idx": None,
            "dest_record": None,
            "dest_before": None,
            "dest_after": None,
        }, None

    if cross_box:
        dest_record = records[dest_idx]
        return None, (
            f"Row {row_idx} ID {record_id}: target box {target_box} position {to_pos} "
            f"is occupied by record #{dest_record.get('id')}"
        )

    if dest_idx in touched_indices:
        return None, (
            f"Row {row_idx} ID {record_id}: target position {to_pos} has already been moved in this batch"
        )

    dest_record = records[dest_idx]
    return {
        "dest_idx": dest_idx,
        "dest_record": dest_record,
        "dest_before": simulated_position.get(dest_idx),
        "dest_after": from_pos,
    }, None


def _apply_move_to_simulation(
    *,
    idx,
    dest_idx,
    current_box,
    from_pos,
    target_box,
    to_pos,
    source_after,
    dest_after,
    entry_to_box,
    simulated_position,
    simulated_box,
    touched_indices,
    position_owner,
):
    simulated_position[idx] = source_after
    touched_indices.add(idx)

    old_key = (current_box, from_pos)
    if dest_idx is None:
        position_owner.pop(old_key, None)
    else:
        simulated_position[dest_idx] = dest_after
        touched_indices.add(dest_idx)
        position_owner[old_key] = dest_idx
    position_owner[(target_box, to_pos)] = idx

    if entry_to_box is not None and entry_to_box != current_box:
        simulated_box[idx] = entry_to_box


def _append_move_events(
    *,
    events_by_idx,
    idx,
    dest_idx,
    dest_record,
    record_id,
    date_str,
    from_pos,
    to_pos,
    current_box,
    entry_to_box,
):
    cross_box = entry_to_box is not None and entry_to_box != current_box
    events_by_idx[idx].append(
        api._build_move_event(
            date_str=date_str,
            from_position=from_pos,
            to_position=to_pos,
            paired_record_id=dest_record.get("id") if dest_record else None,
            from_box=current_box if cross_box else None,
            to_box=entry_to_box if cross_box else None,
        )
    )

    if dest_record is not None and dest_idx is not None:
        events_by_idx[dest_idx].append(
            api._build_move_event(
                date_str=date_str,
                from_position=to_pos,
                to_position=from_pos,
                paired_record_id=record_id,
            )
        )


def _build_move_operation(
    *,
    idx,
    record_id,
    record,
    from_pos,
    to_pos,
    source_before,
    source_after,
    entry_to_box,
    dest_record,
    dest_before,
    dest_after,
):
    op = {
        "idx": idx,
        "record_id": record_id,
        "record": record,
        "position": from_pos,
        "to_position": to_pos,
        "old_position": source_before,
        "new_position": source_after,
    }
    if entry_to_box is not None:
        op["to_box"] = entry_to_box
    if dest_record is not None:
        op["swap_with_record_id"] = dest_record.get("id")
        op["swap_with_short_name"] = dest_record.get("short_name")
        op["swap_old_position"] = dest_before
        op["swap_new_position"] = dest_after
    return op


def _build_batch_move_plan(
    *,
    records,
    normalized_entries,
    layout,
    date_str,
    pos_lo,
    pos_hi,
):
    operations = []
    simulated_position, simulated_box, position_owner, errors = _seed_move_simulation_state(records)
    events_by_idx = defaultdict(list)
    touched_indices = set()

    for row_idx, entry in enumerate(normalized_entries, 1):
        parsed, error = _parse_move_entry_or_error(
            entry=entry,
            row_idx=row_idx,
            pos_lo=pos_lo,
            pos_hi=pos_hi,
            layout=layout,
        )
        if error:
            errors.append(error)
            continue

        record_id = parsed["record_id"]
        from_pos = parsed["from_pos"]
        to_pos = parsed["to_pos"]
        entry_to_box = parsed["entry_to_box"]

        idx, record = find_record_by_id(records, record_id)
        if record is None:
            errors.append(f"Row {row_idx} ID {record_id}: record not found")
            continue

        current_box = simulated_box.get(idx, record.get("box"))
        cross_box = entry_to_box is not None and entry_to_box != current_box

        if not cross_box and from_pos == to_pos:
            errors.append(
                f"Row {row_idx} ID {record_id}: source and target positions must differ for move"
            )
            continue

        source_before = simulated_position.get(idx)
        if source_before is None:
            errors.append(f"Row {row_idx} ID {record_id}: record has no active position")
            continue
        if from_pos != source_before:
            errors.append(
                f"Row {row_idx} ID {record_id}: source position {from_pos} "
                f"does not match current {source_before}"
            )
            continue

        source_after = to_pos

        target_box = entry_to_box if cross_box else current_box
        destination, error = _resolve_destination_or_error(
            records=records,
            row_idx=row_idx,
            record_id=record_id,
            idx=idx,
            cross_box=cross_box,
            target_box=target_box,
            to_pos=to_pos,
            touched_indices=touched_indices,
            position_owner=position_owner,
            simulated_position=simulated_position,
            from_pos=from_pos,
        )
        if error:
            errors.append(error)
            continue

        dest_idx = destination["dest_idx"]
        dest_record = destination["dest_record"]
        dest_before = destination["dest_before"]
        dest_after = destination["dest_after"]

        _apply_move_to_simulation(
            idx=idx,
            dest_idx=dest_idx,
            current_box=current_box,
            from_pos=from_pos,
            target_box=target_box,
            to_pos=to_pos,
            source_after=source_after,
            dest_after=dest_after,
            entry_to_box=entry_to_box,
            simulated_position=simulated_position,
            simulated_box=simulated_box,
            touched_indices=touched_indices,
            position_owner=position_owner,
        )
        _append_move_events(
            events_by_idx=events_by_idx,
            idx=idx,
            dest_idx=dest_idx,
            dest_record=dest_record,
            record_id=record_id,
            date_str=date_str,
            from_pos=from_pos,
            to_pos=to_pos,
            current_box=current_box,
            entry_to_box=entry_to_box,
        )
        operations.append(
            _build_move_operation(
                idx=idx,
                record_id=record_id,
                record=record,
                from_pos=from_pos,
                to_pos=to_pos,
                source_before=source_before,
                source_after=source_after,
                entry_to_box=entry_to_box,
                dest_record=dest_record,
                dest_before=dest_before,
                dest_after=dest_after,
            )
        )

    return {
        "operations": operations,
        "errors": errors,
        "simulated_position": simulated_position,
        "simulated_box": simulated_box,
        "events_by_idx": events_by_idx,
        "touched_indices": touched_indices,
    }


def _persist_batch_move_plan(
    *,
    data,
    records,
    normalized_entries,
    plan,
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
    operations = plan["operations"]
    touched_indices = plan["touched_indices"]
    simulated_position = plan["simulated_position"]
    simulated_box = plan["simulated_box"]
    events_by_idx = plan["events_by_idx"]
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
            return None, None, failure

        for idx in touched_indices:
            candidate_records[idx]["position"] = simulated_position[idx]
            if simulated_box.get(idx) != records[idx].get("box"):
                candidate_records[idx]["box"] = simulated_box[idx]

        for idx in touched_indices:
            events = events_by_idx.get(idx) or []
            if not events:
                continue
            failure = append_record_events_or_failure(
                candidate_data=candidate_data,
                candidate_records=candidate_records,
                record_index=idx,
                new_events=events,
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
            )
            if failure:
                return None, None, failure

        if api._validate_data_or_error(candidate_data):
            return None, None, build_integrity_failure(
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

        affected_ids = sorted({records[idx].get("id") for idx in touched_indices})
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
                    "affected_record_ids": affected_ids,
                },
                tool_input={
                    "entries": list(normalized_entries),
                    "date": date_str,
                    "action": action,
                },
            ),
        )
    except Exception as exc:
        return None, None, build_write_failed_result(
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

    return _backup_path, affected_ids, None
