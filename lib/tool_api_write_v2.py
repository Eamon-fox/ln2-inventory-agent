"""V2 write-entry handlers for unified takeout/move tools."""

from .position_fmt import pos_to_display
from .validators import validate_box
from .yaml_ops import load_yaml


def _load_layout_context(
    *,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    from . import tool_api as api

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return None, None, None, api._failure_result(
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

    layout = api._get_layout(data)
    record_map = {}
    for rec in data.get("inventory", []):
        try:
            record_map[int(rec.get("id"))] = rec
        except Exception:
            continue
    return data, layout, record_map, None


def _entry_failure(
    *,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
    error_code,
    message,
    entry_index=None,
    field_path=None,
    details=None,
):
    from . import tool_api as api

    merged_details = {}
    if entry_index is not None:
        merged_details["entry_index"] = entry_index
    if field_path:
        merged_details["field_path"] = field_path
    if details:
        merged_details.update(details)
    return api._failure_result(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        error_code=error_code,
        message=message,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
        details=merged_details or None,
    )


def _parse_record_id(entry, *, idx):
    record_id = entry.get("record_id")
    if record_id in (None, ""):
        return None, {
            "error_code": "validation_failed",
            "message": f"entries[{idx}].record_id is required",
            "field_path": f"entries[{idx}].record_id",
        }
    if isinstance(record_id, bool):
        return None, {
            "error_code": "invalid_record_id",
            "message": f"entries[{idx}].record_id must be an integer",
            "field_path": f"entries[{idx}].record_id",
        }
    try:
        return int(record_id), None
    except Exception:
        return None, {
            "error_code": "invalid_record_id",
            "message": f"entries[{idx}].record_id must be an integer",
            "field_path": f"entries[{idx}].record_id",
        }


def _normalize_takeout_entries(
    *,
    entries,
    layout,
    record_map,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
):
    from . import tool_api as api

    normalized_entries = []
    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="validation_failed",
                message=f"entries[{idx}] must be an object",
                entry_index=idx,
                field_path=f"entries[{idx}]",
            )

        rid, rid_error = _parse_record_id(entry, idx=idx)
        if rid_error:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code=rid_error["error_code"],
                message=rid_error["message"],
                entry_index=idx,
                field_path=rid_error.get("field_path"),
            )

        try:
            from_box, from_pos = api._parse_slot_payload(
                entry.get("from"),
                layout=layout,
                field_name=f"entries[{idx}].from",
            )
        except ValueError as exc:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="validation_failed",
                message=str(exc),
                entry_index=idx,
                field_path=f"entries[{idx}].from",
            )

        if not validate_box(from_box, layout):
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="invalid_box",
                message=(
                    f"entries[{idx}].from.box {from_box} is out of range "
                    f"({api._format_box_constraint(layout)})"
                ),
                entry_index=idx,
                field_path=f"entries[{idx}].from.box",
            )

        issue = api._validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Source slot validation failed"),
                entry_index=idx,
                details=issue.get("details"),
            )

        normalized_entries.append((rid, pos_to_display(from_pos, layout)))

    return normalized_entries, None


def _normalize_move_entries(
    *,
    entries,
    layout,
    record_map,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
):
    from . import tool_api as api

    normalized_entries = []
    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="validation_failed",
                message=f"entries[{idx}] must be an object",
                entry_index=idx,
                field_path=f"entries[{idx}]",
            )

        rid, rid_error = _parse_record_id(entry, idx=idx)
        if rid_error:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code=rid_error["error_code"],
                message=rid_error["message"],
                entry_index=idx,
                field_path=rid_error.get("field_path"),
            )

        try:
            from_box, from_pos = api._parse_slot_payload(
                entry.get("from"),
                layout=layout,
                field_name=f"entries[{idx}].from",
            )
            to_box, to_pos = api._parse_slot_payload(
                entry.get("to"),
                layout=layout,
                field_name=f"entries[{idx}].to",
            )
        except ValueError as exc:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="validation_failed",
                message=str(exc),
                entry_index=idx,
            )

        if not validate_box(from_box, layout):
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="invalid_box",
                message=(
                    f"entries[{idx}].from.box {from_box} is out of range "
                    f"({api._format_box_constraint(layout)})"
                ),
                entry_index=idx,
                field_path=f"entries[{idx}].from.box",
            )
        if not validate_box(to_box, layout):
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code="invalid_box",
                message=(
                    f"entries[{idx}].to.box {to_box} is out of range "
                    f"({api._format_box_constraint(layout)})"
                ),
                entry_index=idx,
                field_path=f"entries[{idx}].to.box",
            )

        issue = api._validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return None, _entry_failure(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Source slot validation failed"),
                entry_index=idx,
                details=issue.get("details"),
            )

        normalized_entries.append(
            (
                rid,
                pos_to_display(from_pos, layout),
                pos_to_display(to_pos, layout),
                to_box,
            )
        )

    return normalized_entries, None


def tool_takeout(
    yaml_path,
    entries,
    date_str,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """V2 takeout API using explicit source slots."""
    from . import tool_api as api

    audit_action = "takeout"
    tool_name = "tool_takeout_v2"
    tool_input = {
        "entries": entries,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    data, layout, record_map, failure = _load_layout_context(
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    normalized_entries, failure = _normalize_takeout_entries(
        entries=entries,
        layout=layout,
        record_map=record_map,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=data,
    )
    if failure:
        return failure

    response = _tool_takeout_impl(
        yaml_path=yaml_path,
        entries=normalized_entries,
        date_str=date_str,
        action="takeout",
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
        tool_name="tool_takeout",
    )
    return api._format_tool_response_positions(response, layout=layout)


def tool_move(
    yaml_path,
    entries,
    date_str,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """V2 move API using explicit source and target slots."""
    from . import tool_api as api

    audit_action = "move"
    tool_name = "tool_move_v2"
    tool_input = {
        "entries": entries,
        "date": date_str,
        "dry_run": bool(dry_run),
    }
    data, layout, record_map, failure = _load_layout_context(
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    normalized_entries, failure = _normalize_move_entries(
        entries=entries,
        layout=layout,
        record_map=record_map,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=data,
    )
    if failure:
        return failure

    response = _tool_takeout_impl(
        yaml_path=yaml_path,
        entries=normalized_entries,
        date_str=date_str,
        action="move",
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
        tool_name="tool_move",
    )
    return api._format_tool_response_positions(response, layout=layout)


def _tool_takeout_impl(
    yaml_path,
    entries,
    date_str,
    action="takeout",
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
    tool_name="tool_takeout",
):
    from . import tool_api as api
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_takeout_impl(
        yaml_path=yaml_path,
        entries=entries,
        date_str=date_str,
        action=action,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
        tool_name=tool_name,
    )
    return api._format_tool_response_positions(response, yaml_path=yaml_path)
