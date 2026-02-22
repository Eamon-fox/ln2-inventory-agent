"""V2 write-entry handlers for record/batch takeout and move."""

from .position_fmt import pos_to_display
from .validators import validate_box
from .yaml_ops import load_yaml


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
    request_backup_path=None,
):
    """V2 takeout API requiring explicit source slot."""
    from . import tool_api as api

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

    layout = api._get_layout(data)
    records = data.get("inventory", [])
    try:
        from_box, from_pos = api._parse_slot_payload(from_slot, layout=layout, field_name="from")
    except ValueError as exc:
        return api._failure_result(
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
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Source box {from_box} is out of range ({api._format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    record = api._find_record_by_id_local(records, record_id)
    issue = api._validate_source_slot_match(
        record,
        record_id=record_id,
        from_box=from_box,
        from_pos=from_pos,
    )
    if issue:
        return api._failure_result(
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

    response = _tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=pos_to_display(from_pos, layout),
        date_str=date_str,
        action="takeout",
        to_position=None,
        to_box=None,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return api._format_tool_response_positions(response, layout=layout)


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
    request_backup_path=None,
):
    """V2 move API requiring explicit source and target slots."""
    from . import tool_api as api

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

    layout = api._get_layout(data)
    records = data.get("inventory", [])
    try:
        from_box, from_pos = api._parse_slot_payload(from_slot, layout=layout, field_name="from")
        to_box, to_pos = api._parse_slot_payload(to_slot, layout=layout, field_name="to")
    except ValueError as exc:
        return api._failure_result(
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
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Source box {from_box} is out of range ({api._format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )
    if not validate_box(to_box, layout):
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Target box {to_box} is out of range ({api._format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    record = api._find_record_by_id_local(records, record_id)
    issue = api._validate_source_slot_match(
        record,
        record_id=record_id,
        from_box=from_box,
        from_pos=from_pos,
    )
    if issue:
        return api._failure_result(
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

    response = _tool_record_takeout_impl(
        yaml_path=yaml_path,
        record_id=record_id,
        position=pos_to_display(from_pos, layout),
        date_str=date_str,
        action="move",
        to_position=pos_to_display(to_pos, layout),
        to_box=to_box,
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        source=source,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    return api._format_tool_response_positions(response, layout=layout)


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
    request_backup_path=None,
):
    from . import tool_api as api
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_record_takeout_impl(
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
        request_backup_path=request_backup_path,
    )
    return api._format_tool_response_positions(response, yaml_path=yaml_path)


def tool_batch_takeout(
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
    """V2 batch takeout API using explicit source slots."""
    from . import tool_api as api

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

    layout = api._get_layout(data)
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
            return api._failure_result(
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
            return api._failure_result(
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
            from_box, from_pos = api._parse_slot_payload(
                entry.get("from"),
                layout=layout,
                field_name=f"entries[{idx}].from",
            )
        except ValueError as exc:
            return api._failure_result(
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
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].from.box {from_box} is out of range ({api._format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].from.box"},
            )

        issue = api._validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return api._failure_result(
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
        normalized_entries.append((rid, pos_to_display(from_pos, layout)))

    response = _tool_batch_takeout_impl(
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
    )
    return api._format_tool_response_positions(response, layout=layout)


def tool_batch_move(
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
    """V2 batch move API using explicit source and target slots."""
    from . import tool_api as api

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

    layout = api._get_layout(data)
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
            return api._failure_result(
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
            return api._failure_result(
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
            return api._failure_result(
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
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].from.box {from_box} is out of range ({api._format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].from.box"},
            )
        if not validate_box(to_box, layout):
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_box",
                message=f"entries[{idx}].to.box {to_box} is out of range ({api._format_box_constraint(layout)})",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"entry_index": idx, "field_path": f"entries[{idx}].to.box"},
            )

        issue = api._validate_source_slot_match(
            record_map.get(rid),
            record_id=rid,
            from_box=from_box,
            from_pos=from_pos,
        )
        if issue:
            return api._failure_result(
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
        normalized_entries.append(
            (
                rid,
                pos_to_display(from_pos, layout),
                pos_to_display(to_pos, layout),
                to_box,
            )
        )

    response = _tool_batch_takeout_impl(
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
    )
    return api._format_tool_response_positions(response, layout=layout)


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
    request_backup_path=None,
):
    from . import tool_api as api
    from .tool_api_impl import write_ops as _write_ops

    response = _write_ops._tool_batch_takeout_impl(
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
    )
    return api._format_tool_response_positions(response, yaml_path=yaml_path)
