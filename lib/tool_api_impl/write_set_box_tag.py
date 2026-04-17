"""Set-box-tag write-operation implementations for Tool API."""

from copy import deepcopy

from ..box_layout_requests import normalize_box_tags
from ..migrate_cell_line_policy import normalize_field_options_policy_data
from ..position_fmt import get_box_numbers
from ..yaml_ops import load_yaml, write_yaml
from .audit_details import failure_details, set_box_tag_details
from .write_common import api

def tool_set_box_tag(
    yaml_path,
    box,
    tag="",
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Set or clear a per-box tag stored in meta.box_layout.box_tags."""
    action = "set_box_tag"
    tool_name = "tool_set_box_tag"
    tool_input = {
        "box": box,
        "tag": tag,
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
        payload={"box": box, "tag": tag},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation
    normalized_validation = validation.get("normalized") or {}
    box_num = normalized_validation.get("box")
    normalized_tag = normalized_validation.get("tag", "")

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

    layout = api._get_layout(data)
    box_numbers = list(get_box_numbers(layout))
    if box_num not in box_numbers:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Box {box_num} does not exist (allowed: {api._format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(op="set_box_tag", box=box_num),
        )

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

    box_tags_before = normalize_box_tags(candidate_layout.get("box_tags"), box_numbers)
    box_tags_after = dict(box_tags_before)
    if normalized_tag:
        box_tags_after[str(box_num)] = normalized_tag
    else:
        box_tags_after.pop(str(box_num), None)

    if box_tags_after:
        candidate_layout["box_tags"] = box_tags_after
    else:
        candidate_layout.pop("box_tags", None)

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
            details=failure_details(op="set_box_tag", box=box_num),
        )

    preview = {
        "box": box_num,
        "tag_before": box_tags_before.get(str(box_num), ""),
        "tag_after": box_tags_after.get(str(box_num), ""),
        "box_tags_before": box_tags_before,
        "box_tags_after": box_tags_after,
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    _audit_details = set_box_tag_details(
        box=box_num,
        tag_before=box_tags_before.get(str(box_num), ""),
        tag_after=box_tags_after.get(str(box_num), ""),
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
                details=_audit_details,
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
            message=f"Set box tag failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=_audit_details,
        )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": preview,
        "backup_path": backup_path,
    }
