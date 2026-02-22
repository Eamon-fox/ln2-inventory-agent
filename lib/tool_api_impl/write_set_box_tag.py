"""Set-box-tag write-operation implementations for Tool API."""

from copy import deepcopy

from ..migrate_cell_line_policy import normalize_cell_line_policy_data
from ..position_fmt import get_box_numbers
from ..yaml_ops import load_yaml, write_yaml
from .write_common import api


_BOX_TAG_MAX_LENGTH = 80


def _normalize_box_tag_value(raw_tag):
    text = "" if raw_tag is None else str(raw_tag)
    if "\n" in text or "\r" in text:
        return None, "Box tag must be a single line"
    normalized = text.strip()
    if len(normalized) > _BOX_TAG_MAX_LENGTH:
        return None, f"Box tag must be <= {_BOX_TAG_MAX_LENGTH} characters"
    return normalized, None


def _normalize_box_tags(raw_tags, allowed_boxes):
    if not isinstance(raw_tags, dict):
        return {}

    allowed = {int(box_num) for box_num in list(allowed_boxes or [])}
    normalized = {}
    for raw_box, raw_tag in raw_tags.items():
        try:
            box_num = int(raw_box)
        except Exception:
            continue
        if box_num not in allowed:
            continue

        tag_text, _err = _normalize_box_tag_value(raw_tag)
        if tag_text:
            normalized[str(box_num)] = tag_text
    return normalized


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
    """Set or clear per-box single-line tag stored in meta.box_layout.box_tags."""
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

    try:
        box_num = int(box)
    except Exception:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message="box must be an integer",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"box": box},
        )
    if box_num <= 0:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message="box must be >= 1",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"box": box},
        )

    normalized_tag, tag_error = _normalize_box_tag_value(tag)
    if tag_error:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_tag",
            message=tag_error,
            actor_context=actor_context,
            tool_input=tool_input,
            details={"max_length": _BOX_TAG_MAX_LENGTH},
        )

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
    normalized = normalize_cell_line_policy_data(data)
    if not normalized.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=normalized.get("error_code", "normalize_failed"),
            message=normalized.get("message", "Failed to normalize cell_line policy."),
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
            details={"box": box_num},
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

    box_tags_before = _normalize_box_tags(candidate_layout.get("box_tags"), box_numbers)
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
            details={"box": box_num},
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
                details=preview,
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
            details=preview,
        )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": preview,
        "backup_path": backup_path,
    }
