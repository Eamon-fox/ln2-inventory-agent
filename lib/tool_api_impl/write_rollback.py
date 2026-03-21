"""Rollback-related write-operation implementations for Tool API."""

import os

from ..custom_fields import unsupported_box_fields_issue
from ..path_policy import PathPolicyError, resolve_dataset_backup_read_path
from ..yaml_ops import (
    list_alternative_backups,
    load_yaml,
    rollback_yaml,
    validate_backup_file,
)
from .audit_details import rollback_details as _rollback_details
from .write_common import api


def _attach_alternative_backups(payload: dict, yaml_path: str, failed_path: str) -> dict:
    """Enrich a failure payload with alternative backup suggestions."""
    try:
        alternatives = list_alternative_backups(yaml_path, exclude_path=failed_path, limit=5)
    except Exception:
        alternatives = []
    if alternatives:
        payload["alternative_backups"] = alternatives
    return payload


def tool_rollback(
    yaml_path,
    backup_path=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    source_event=None,
    request_backup_path=None,
):
    """Rollback inventory YAML using shared tool flow."""

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
        return _rollback_details(
            requested_backup=target_path,
            requested_from_event=normalized_source_event or None,
        )

    tool_input = {
        "backup_path": backup_path,
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
        "request_backup_path": request_backup_path,
    }
    if normalized_source_event:
        tool_input["source_event"] = dict(normalized_source_event)

    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload={"backup_path": backup_path},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation

    current_data = None
    try:
        current_data = load_yaml(yaml_path)
    except Exception:
        current_data = None
    unsupported_issue = unsupported_box_fields_issue((current_data or {}).get("meta"))
    if unsupported_issue:
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code=unsupported_issue.get("error_code", "unsupported_box_fields"),
            message=unsupported_issue.get("message", "Unsupported dataset model."),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
            details=unsupported_issue.get("details"),
        )

    normalized = validation.get("normalized") if isinstance(validation, dict) else {}
    normalized_backup_path = str((normalized or {}).get("backup_path") or backup_path or "").strip()
    is_preflight_source = str(source or "").strip().lower().startswith("plan_executor.preflight")
    if is_preflight_source:
        if not normalized_backup_path:
            payload = {
                "ok": False,
                "error_code": "path.invalid_input",
                "message": "backup_path must be a non-empty string.",
                "backup_path": "",
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
        target_backup_path = os.path.abspath(normalized_backup_path)
        if not os.path.exists(target_backup_path):
            return {
                "ok": False,
                "error_code": "path.not_found",
                "message": f"Path not found: {target_backup_path}",
            }
        if not os.path.isfile(target_backup_path):
            return {
                "ok": False,
                "error_code": "path.not_file",
                "message": f"Path is not a file: {target_backup_path}",
            }
    else:
        try:
            resolved_backup_path = resolve_dataset_backup_read_path(
                yaml_path=yaml_path,
                raw_path=normalized_backup_path,
                must_exist=True,
                must_be_file=True,
            )
            if normalized_backup_path and os.path.isabs(normalized_backup_path):
                target_backup_path = os.path.abspath(normalized_backup_path)
            else:
                target_backup_path = str(resolved_backup_path)
        except PathPolicyError as exc:
            payload = {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
                "backup_path": str(normalized_backup_path or ""),
            }
            extra = {"backup_path": payload["backup_path"]}
            if exc.resolved_path:
                extra["resolved_path"] = exc.resolved_path
            payload = _attach_alternative_backups(payload, yaml_path, normalized_backup_path or "")
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
                    details=_details_for_target(normalized_backup_path or None),
                    extra=extra,
                )
            return payload

    # Pre-rollback validation: check backup file integrity
    backup_validation = validate_backup_file(target_backup_path)
    if not backup_validation["valid"]:
        raw_code = backup_validation["error_code"] or "backup_load_failed"
        # Map integrity failures to the established API error code for compatibility
        error_code = "rollback_backup_invalid" if raw_code == "backup_integrity_failed" else raw_code
        message = backup_validation["error"] or "Backup validation failed"
        payload = {
            "ok": False,
            "error_code": error_code,
            "message": message,
            "backup_path": target_backup_path,
        }
        payload = _attach_alternative_backups(payload, yaml_path, target_backup_path)
        if not dry_run:
            return api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=error_code,
                message=message,
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=current_data,
                details=_details_for_target(target_backup_path),
                extra={
                    "backup_path": target_backup_path,
                    **({"alternative_backups": payload["alternative_backups"]}
                       if "alternative_backups" in payload else {}),
                },
            )
        return payload

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "result": {
                "requested_backup": target_backup_path,
            },
        }

    try:
        result = rollback_yaml(
            path=yaml_path,
            backup_path=target_backup_path,
            request_backup_path=request_backup_path,
            audit_meta=api._build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details=_details_for_target(target_backup_path),
                tool_input=tool_input,
            ),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "error_code": "rollback_failed",
            "message": f"Rollback failed: {exc}",
            "backup_path": target_backup_path,
        }
        payload = _attach_alternative_backups(payload, yaml_path, target_backup_path)
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
            details=_details_for_target(target_backup_path),
            extra={
                "backup_path": target_backup_path,
                **({"alternative_backups": payload.get("alternative_backups", [])}
                   if payload.get("alternative_backups") else {}),
            },
        )

    return {
        "ok": True,
        "dry_run": False,
        "result": result,
        "backup_path": request_backup_path or result.get("snapshot_before_rollback"),
    }
