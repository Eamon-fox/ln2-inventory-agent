"""Edit-entry write-operation implementations for Tool API."""

from copy import deepcopy

from ..custom_fields import get_cell_line_options, get_effective_fields, is_cell_line_required
from ..operations import find_record_by_id
from ..yaml_ops import load_yaml, write_yaml
from .write_common import api

_EDITABLE_FIELDS = {"frozen_at", "cell_line", "note"}


def _get_editable_fields(yaml_path):
    """Return editable field set: frozen_at + cell_line + note + user fields from meta."""
    try:
        data = load_yaml(yaml_path)
        meta = data.get("meta", {})
        fields = get_effective_fields(meta)
        return _EDITABLE_FIELDS | {field["key"] for field in fields}
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
):
    """Edit metadata fields of an existing record."""
    action = "edit_entry"
    tool_name = "tool_edit_entry"
    tool_input = {
        "record_id": record_id,
        "fields": dict(fields or {}),
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
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
    )
    if not validation.get("ok"):
        return validation

    allowed = _get_editable_fields(yaml_path)
    bad_keys = set(fields.keys()) - allowed
    if bad_keys:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="forbidden_fields",
            message=f"These fields are not editable: {', '.join(sorted(bad_keys))}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"forbidden": sorted(bad_keys), "allowed": sorted(allowed)},
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

    meta = data.get("meta", {})
    normalized_fields = dict(fields)
    if "cell_line" in normalized_fields:
        raw_cell_line = normalized_fields.get("cell_line")
        cell_line_text = str(raw_cell_line or "").strip()

        if is_cell_line_required(meta) and not cell_line_text:
            return api._failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_cell_line",
                message="cell_line is required and cannot be empty",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
            )

        if cell_line_text:
            cell_line_options = get_cell_line_options(meta)
            if not cell_line_options:
                return api._failure_result(
                    yaml_path=yaml_path,
                    action=action,
                    source=source,
                    tool_name=tool_name,
                    error_code="invalid_cell_line_options",
                    message="cell_line requires predefined options, but meta.cell_line_options is empty",
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                )
            if cell_line_text not in cell_line_options:
                return api._failure_result(
                    yaml_path=yaml_path,
                    action=action,
                    source=source,
                    tool_name=tool_name,
                    error_code="invalid_cell_line",
                    message="cell_line must come from predefined options",
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    details={"cell_line": cell_line_text, "options": cell_line_options},
                )

        normalized_fields["cell_line"] = cell_line_text

    _idx, record = find_record_by_id(data.get("inventory", []), record_id)
    if record is None:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="record_not_found",
            message=f"Record ID={record_id} not found",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    before = {key: record.get(key) for key in normalized_fields}
    candidate_data = deepcopy(data)
    _cidx, candidate_record = find_record_by_id(candidate_data.get("inventory", []), record_id)
    for key, value in normalized_fields.items():
        candidate_record[key] = value

    validation_error = api._validate_data_or_error(candidate_data)
    if validation_error:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=validation_error.get("error_code", "integrity_validation_failed"),
            message=validation_error.get("message", "Validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            errors=validation_error.get("errors"),
        )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": {
                "record_id": record_id,
                "before": before,
                "after": dict(normalized_fields),
            },
        }

    try:
        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            audit_meta=api._build_audit_meta(
                action=action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details={"record_id": record_id, "before": before, "after": dict(normalized_fields)},
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

    return {
        "ok": True,
        "result": {
            "record_id": record_id,
            "before": before,
            "after": dict(normalized_fields),
        },
        "backup_path": _backup_path,
    }


