"""Batch takeout/move write-operation implementations for Tool API."""

from ..position_fmt import get_position_range
from ..takeout_parser import ACTION_LABEL, normalize_action
from ..yaml_ops import load_yaml
from . import write_takeout_batch_move as _move_ops
from . import write_takeout_batch_nonmove as _nonmove_ops
from .write_common import api


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
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message="Batch operation parameter validation failed",
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
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message="Batch operation parameter validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            errors=normalize_errors,
        )

    return normalized_entries, None


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
        operations = plan["operations"]
        errors = plan["errors"]

        if errors:
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message="Batch operation parameter validation failed",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=errors,
                extra={"operations": operations},
                details={"error_count": len(errors)},
            )

        preview = {
            "date": date_str,
            "action_en": action_en,
            "action_cn": ACTION_LABEL.get(action_en, action),
            "count": len(operations),
            "operations": [
                {
                    "record_id": op["record_id"],
                    "cell_line": op["record"].get("cell_line"),
                    "short_name": op["record"].get("short_name"),
                    "box": op["record"].get("box"),
                    "position": op["position"],
                    "to_position": op.get("to_position"),
                    "old_position": op["old_position"],
                    "new_position": op["new_position"],
                    "swap_with_record_id": op.get("swap_with_record_id"),
                }
                for op in operations
            ],
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "preview": preview,
            }

        _backup_path, affected_ids, failure = _move_ops._persist_batch_move_plan(
            data=data,
            records=records,
            normalized_entries=normalized_entries,
            plan=plan,
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            action=action,
            action_en=action_en,
            date_str=date_str,
            auto_backup=auto_backup,
        )
        if failure:
            return failure

        return {
            "ok": True,
            "dry_run": False,
            "preview": preview,
            "result": {
                "count": len(operations),
                "record_ids": [op["record_id"] for op in operations],
                "affected_record_ids": affected_ids,
            },
            "backup_path": _backup_path,
        }

    nonmove = _nonmove_ops._build_batch_nonmove_plan(
        records=records,
        normalized_entries=normalized_entries,
        pos_lo=_pos_lo,
        pos_hi=_pos_hi,
    )
    operations = nonmove["operations"]
    errors = nonmove["errors"]

    if errors:
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message="Batch operation parameter validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            errors=errors,
            extra={"operations": operations},
            details={"error_count": len(errors)},
        )

    preview = {
        "date": date_str,
        "action_en": action_en,
        "action_cn": ACTION_LABEL.get(action_en, action),
        "count": len(operations),
        "operations": [
            {
                "record_id": op["record_id"],
                "cell_line": op["record"].get("cell_line"),
                "short_name": op["record"].get("short_name"),
                "box": op["record"].get("box"),
                "position": op["position"],
                "old_position": op["old_position"],
                "new_position": op["new_position"],
            }
            for op in operations
        ],
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    _backup_path, failure = _nonmove_ops._persist_batch_nonmove_plan(
        data=data,
        normalized_entries=normalized_entries,
        operations=operations,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        action=action,
        action_en=action_en,
        date_str=date_str,
        auto_backup=auto_backup,
    )
    if failure:
        return failure

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {
            "count": len(operations),
            "record_ids": [op["record_id"] for op in operations],
        },
        "backup_path": _backup_path,
    }
