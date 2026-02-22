"""Batch takeout/move write-operation implementations for Tool API."""

from ..position_fmt import get_position_range
from ..takeout_parser import ACTION_LABEL, normalize_action
from ..yaml_ops import load_yaml
from . import write_takeout_batch_move as _move_ops
from . import write_takeout_batch_nonmove as _nonmove_ops
from .write_common import api


def _validation_failed_result(
    *,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    errors,
    before_data=None,
    operations=None,
):
    extra = None
    details = None
    if operations is not None:
        extra = {"operations": operations}
        details = {"error_count": len(errors)}
    return api._failure_result(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        error_code="validation_failed",
        message="Batch operation parameter validation failed",
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
        errors=errors,
        extra=extra,
        details=details,
    )


def _normalize_batch_takeout_entries(
    *,
    entries,
    layout,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    if isinstance(entries, str):
        try:
            entries = api.parse_batch_entries(entries, layout=layout)
        except ValueError as exc:
            return None, _validation_failed_result(
                yaml_path=yaml_path,
                audit_action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                tool_input=tool_input,
                errors=[str(exc)],
            )

    normalized_entries = []
    normalize_errors = []
    for idx, entry in enumerate(entries, 1):
        try:
            normalized_entries.append(api._coerce_batch_entry(entry, layout=layout))
        except Exception as exc:
            normalize_errors.append(f"Row {idx}: {exc}")

    if normalize_errors:
        return None, _validation_failed_result(
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            errors=normalize_errors,
        )

    return normalized_entries, None


def _batch_validation_failed_result(
    *,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
    operations,
    errors,
):
    return _validation_failed_result(
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
        errors=errors,
        operations=operations,
    )


def _build_batch_operation_preview_item(op, *, include_move_fields):
    item = {
        "record_id": op["record_id"],
        "cell_line": op["record"].get("cell_line"),
        "short_name": op["record"].get("short_name"),
        "box": op["record"].get("box"),
        "position": op["position"],
        "old_position": op["old_position"],
        "new_position": op["new_position"],
    }
    if include_move_fields:
        item["to_position"] = op.get("to_position")
        if op.get("swap_with_record_id") is not None:
            item["swap_with_record_id"] = op.get("swap_with_record_id")
    return item


def _build_batch_preview(*, date_str, action_en, action, operations, include_move_fields):
    return {
        "date": date_str,
        "action_en": action_en,
        "action_cn": ACTION_LABEL.get(action_en, action),
        "count": len(operations),
        "operations": [
            _build_batch_operation_preview_item(op, include_move_fields=include_move_fields)
            for op in operations
        ],
    }


def _build_batch_success_response(
    *,
    preview,
    operations,
    backup_path,
    affected_record_ids=None,
):
    result_payload = {
        "count": len(operations),
        "record_ids": [op["record_id"] for op in operations],
    }
    if affected_record_ids is not None:
        result_payload["affected_record_ids"] = affected_record_ids
    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": result_payload,
        "backup_path": backup_path,
    }


def _process_batch_plan(
    *,
    plan,
    include_move_fields,
    date_str,
    action_en,
    action,
    dry_run,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
    persist_fn,
    persist_kwargs,
):
    operations = plan["operations"]
    errors = plan["errors"]
    if errors:
        return _batch_validation_failed_result(
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=before_data,
            operations=operations,
            errors=errors,
        )

    preview = _build_batch_preview(
        date_str=date_str,
        action_en=action_en,
        action=action,
        operations=operations,
        include_move_fields=include_move_fields,
    )
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    backup_path, affected_record_ids, failure = persist_fn(**persist_kwargs)
    if failure:
        return failure

    return _build_batch_success_response(
        preview=preview,
        operations=operations,
        backup_path=backup_path,
        affected_record_ids=affected_record_ids,
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
    """Record batch takeout/move operations via shared tool flow."""
    audit_action = "batch_takeout"
    tool_name = "tool_batch_takeout"
    tool_input = {
        "entries": list(entries) if isinstance(entries, (list, tuple)) else entries,
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
        payload={"date_str": date_str, "action": action, "entries": entries},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
    )
    if not validation.get("ok"):
        return validation

    action_en = (validation.get("normalized") or {}).get("action_en") or normalize_action(action) or ""

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

    records = data.get("inventory", [])
    layout = api._get_layout(data)
    _pos_lo, _pos_hi = get_position_range(layout)

    normalized_entries, failure = _normalize_batch_takeout_entries(
        entries=entries,
        layout=layout,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    if action_en == "move":
        plan = _move_ops._build_batch_move_plan(
            records=records,
            normalized_entries=normalized_entries,
            layout=layout,
            date_str=date_str,
            pos_lo=_pos_lo,
            pos_hi=_pos_hi,
        )
        return _process_batch_plan(
            plan=plan,
            include_move_fields=True,
            date_str=date_str,
            action_en=action_en,
            action=action,
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            dry_run=dry_run,
            persist_fn=_persist_batch_move,
            persist_kwargs={
                "data": data,
                "records": records,
                "normalized_entries": normalized_entries,
                "plan": plan,
                "yaml_path": yaml_path,
                "audit_action": audit_action,
                "source": source,
                "tool_name": tool_name,
                "actor_context": actor_context,
                "tool_input": tool_input,
                "action": action,
                "action_en": action_en,
                "date_str": date_str,
                "auto_backup": auto_backup,
            },
        )

    nonmove = _nonmove_ops._build_batch_nonmove_plan(
        records=records,
        normalized_entries=normalized_entries,
        pos_lo=_pos_lo,
        pos_hi=_pos_hi,
    )
    return _process_batch_plan(
        plan=nonmove,
        include_move_fields=False,
        date_str=date_str,
        action_en=action_en,
        action=action,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=data,
        dry_run=dry_run,
        persist_fn=_persist_batch_nonmove,
        persist_kwargs={
            "data": data,
            "normalized_entries": normalized_entries,
            "operations": nonmove["operations"],
            "yaml_path": yaml_path,
            "audit_action": audit_action,
            "source": source,
            "tool_name": tool_name,
            "actor_context": actor_context,
            "tool_input": tool_input,
            "action": action,
            "action_en": action_en,
            "date_str": date_str,
            "auto_backup": auto_backup,
        },
    )


def _persist_batch_move(**kwargs):
    return _move_ops._persist_batch_move_plan(**kwargs)


def _persist_batch_nonmove(**kwargs):
    backup_path, failure = _nonmove_ops._persist_batch_nonmove_plan(**kwargs)
    return backup_path, None, failure
