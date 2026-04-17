"""Set-box-layout-indexing write-operation implementation for Tool API."""

from copy import deepcopy

from ..migrate_cell_line_policy import normalize_field_options_policy_data
from ..position_fmt import (
    DEFAULT_BOX_LAYOUT_INDEXING,
    normalize_box_layout_indexing,
)
from ..yaml_ops import load_yaml, write_yaml
from .audit_details import failure_details, set_box_layout_indexing_details
from .write_common import api

def tool_set_box_layout_indexing(
    yaml_path,
    indexing,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Set meta.box_layout.indexing without rewriting stored inventory positions."""

    action = "set_box_layout_indexing"
    tool_name = "tool_set_box_layout_indexing"
    tool_input = {
        "indexing": indexing,
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
        payload={"indexing": indexing},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation
    normalized_validation = validation.get("normalized") or {}
    normalized_indexing = normalized_validation.get("indexing")

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

    normalized = normalize_field_options_policy_data(data)
    if not normalized.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=normalized.get("error_code", "normalize_failed"),
            message=normalized.get("message", "Failed to normalize field options policy."),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data if isinstance(data, dict) else None,
        )
    data = normalized.get("data")

    candidate_data = deepcopy(data if isinstance(data, dict) else {})
    meta = candidate_data.setdefault("meta", {})
    if not isinstance(meta, dict):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_meta",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    candidate_layout = meta.setdefault("box_layout", {})
    if not isinstance(candidate_layout, dict):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box_layout",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    indexing_before = normalize_box_layout_indexing(candidate_layout.get("indexing"))
    if normalized_indexing == DEFAULT_BOX_LAYOUT_INDEXING:
        candidate_layout.pop("indexing", None)
    else:
        candidate_layout["indexing"] = normalized_indexing

    integrity_error = api._validate_data_or_error(candidate_data)
    if integrity_error:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=integrity_error.get("error_code", "integrity_validation_failed"),
            message=integrity_error.get("message", "Validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            errors=integrity_error.get("errors"),
            errors_detail=integrity_error.get("errors_detail"),
            details=failure_details(op="set_box_layout_indexing", indexing=normalized_indexing),
        )

    preview = {
        "indexing_before": indexing_before,
        "indexing_after": normalized_indexing,
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    audit_details = set_box_layout_indexing_details(
        indexing_before=indexing_before,
        indexing_after=normalized_indexing,
    )
    try:
        backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            backup_path=request_backup_path,
            audit_meta=api._build_audit_meta(
                action=action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details=audit_details,
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
            message=f"Set box layout indexing failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=audit_details,
        )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": preview,
        "backup_path": backup_path,
    }
