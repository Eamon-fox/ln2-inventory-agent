"""Edit-entry write-operation implementations for Tool API."""

from copy import deepcopy

from ..yaml_ops import load_yaml, write_yaml
from .edit_entry_core import (
    _EDITABLE_FIELDS,
    apply_edit_to_candidate,
    editable_fields_for_data,
    prepare_edit_document,
)
from .write_common import api


def _get_editable_fields(yaml_path, box=None):
    """Return editable field set: stored_at/frozen_at + all effective fields."""
    _ = box
    try:
        data = load_yaml(yaml_path)
        prepared = prepare_edit_document(data)
        if prepared.get("ok"):
            return editable_fields_for_data(prepared.get("data") or {})
    except Exception:
        pass
    return _EDITABLE_FIELDS


def tool_edit_entry(
    yaml_path,
    record_id,
    fields,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Edit metadata fields of an existing record."""
    action = "edit_entry"
    tool_name = "tool_edit_entry"
    tool_input = {
        "record_id": record_id,
        "fields": dict(fields or {}),
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
        "request_backup_path": request_backup_path,
    }

    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload={"fields": fields or {}},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
        )
    prepared = prepare_edit_document(data)
    if not prepared.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=prepared.get("error_code", "normalize_failed"),
            message=prepared.get("message", "Failed to normalize field options policy."),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=prepared.get("data") if isinstance(prepared.get("data"), dict) else data if isinstance(data, dict) else None,
            errors=prepared.get("errors"),
        )
    data = prepared.get("data")
    candidate_data = deepcopy(data)
    edit_result = apply_edit_to_candidate(
        candidate_data=candidate_data,
        record_id=record_id,
        fields=fields,
        validate_fn=api._validate_data_or_error,
    )
    if not edit_result.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=edit_result.get("error_code", "validation_failed"),
            message=edit_result.get("message", "Validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            errors=edit_result.get("errors"),
            errors_detail=edit_result.get("errors_detail"),
            details=edit_result.get("details"),
        )

    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "preview": {
                "record_id": record_id,
                "before": edit_result.get("before") or {},
                "after": edit_result.get("after") or {},
            },
        }
        if edit_result.get("alias_warnings"):
            payload["warnings"] = list(edit_result.get("alias_warnings") or [])
        return payload

    try:
        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            backup_path=request_backup_path,
            audit_meta=api._build_audit_meta(
                action=action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details=edit_result.get("audit_details"),
                tool_input=tool_input,
            ),
        )
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Edit failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    payload = {
        "ok": True,
        "result": {
            "record_id": record_id,
            "before": edit_result.get("before") or {},
            "after": edit_result.get("after") or {},
        },
        "backup_path": _backup_path,
    }
    if edit_result.get("alias_warnings"):
        payload["warnings"] = list(edit_result.get("alias_warnings") or [])
    return payload
