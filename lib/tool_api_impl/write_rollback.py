"""Rollback-related write-operation implementations for Tool API."""

import os

from ..yaml_ops import list_yaml_backups, load_yaml, rollback_yaml
from .write_common import api


def tool_list_backups(yaml_path):
    """List YAML backup files, newest first."""
    return list_yaml_backups(yaml_path)


def tool_rollback(
    yaml_path,
    backup_path=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    source_event=None,
):
    """Rollback inventory YAML using shared tool flow."""
    del auto_backup  # Keep signature parity with tool_api; rollback handles its own snapshots.

    audit_action = "rollback"
    tool_name = "tool_rollback"
    normalized_source_event = {}
    if isinstance(source_event, dict):
        normalized_source_event = {
            str(key): value
            for key, value in source_event.items()
            if value not in (None, "")
        }

    def _details_for_target(target_path=None):
        details = {}
        if target_path not in (None, ""):
            details["requested_backup"] = target_path
        if normalized_source_event:
            details["requested_from_event"] = dict(normalized_source_event)
        return details or None

    tool_input = {
        "backup_path": backup_path,
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
    }
    if normalized_source_event:
        tool_input["source_event"] = dict(normalized_source_event)

    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload={},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
    )
    if not validation.get("ok"):
        return validation

    current_data = None
    try:
        current_data = load_yaml(yaml_path)
    except Exception:
        current_data = None

    backups = list_yaml_backups(yaml_path)
    if not backups and not backup_path:
        payload = {
            "ok": False,
            "error_code": "no_backups",
            "message": "No backups available; rollback is not possible",
        }
        if not dry_run:
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=payload["error_code"],
                message=payload["message"],
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=current_data,
                details=_details_for_target(),
            )
        return payload

    target = backup_path or backups[0]
    if dry_run and not os.path.exists(target):
        return {
            "ok": False,
            "error_code": "backup_not_found",
            "message": f"Backup not found: {target}",
        }
    try:
        backup_data = load_yaml(target)
    except Exception as exc:
        payload = {
            "ok": False,
            "error_code": "backup_load_failed",
            "message": f"Failed to read backup file: {exc}",
        }
        if not dry_run:
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=payload["error_code"],
                message=payload["message"],
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=current_data,
                details=_details_for_target(target),
            )
        return payload

    validation_error = api._validate_data_or_error(
        backup_data,
        message_prefix="Rollback blocked: backup does not pass integrity validation",
    )
    if validation_error:
        validation_error = validation_error or {
            "error_code": "rollback_backup_invalid",
            "message": "Validation failed",
            "errors": [],
        }
        payload = {
            "ok": False,
            "error_code": "rollback_backup_invalid",
            "message": validation_error.get("message", "Validation failed"),
            "errors": validation_error.get("errors"),
            "backup_path": target,
        }
        if not dry_run:
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=payload["error_code"],
                message=payload["message"],
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=current_data,
                errors=payload.get("errors"),
                details=_details_for_target(target),
                extra={"backup_path": target},
            )
        return payload

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "result": {
                "requested_backup": target,
            },
        }

    try:
        result = rollback_yaml(
            path=yaml_path,
            backup_path=target,
            audit_meta=api._build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details=_details_for_target(target),
                tool_input=tool_input,
            ),
        )
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="rollback_failed",
            message=f"Rollback failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
            details=_details_for_target(target),
        )

    return {
        "ok": True,
        "dry_run": False,
        "result": result,
        # Expose pre-rollback snapshot so Plan executor can offer an Undo path.
        "backup_path": result.get("snapshot_before_rollback"),
    }
