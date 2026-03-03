"""Edit-entry write-operation implementations for Tool API."""

from copy import deepcopy

from ..custom_fields import get_effective_fields
from ..field_schema import normalize_input_fields
from ..field_schema import split_record_fields
from ..migrate_cell_line_policy import normalize_cell_line_policy_data
from ..operations import find_record_by_id
from ..yaml_ops import load_yaml, write_yaml
from .audit_details import edit_entry_details, failure_details
from .write_common import api

_EDITABLE_FIELDS = {"frozen_at"}


def _get_editable_fields(yaml_path):
    """Return editable field set: frozen_at + all effective fields from meta."""
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

    meta = data.get("meta", {})
    alias_result = normalize_input_fields(fields, meta)
    if not alias_result.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=alias_result.get("error_code", "deprecated_field_alias_removed"),
            message=alias_result.get("message", "Deprecated field alias is no longer accepted."),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(
                op="edit_entry",
                alias_hits=alias_result.get("alias_hits"),
            ),
        )
    alias_warnings = list(alias_result.get("warnings") or [])
    normalized_fields = dict(alias_result.get("fields") or {})

    # Validate all option-bearing fields generically
    effective = get_effective_fields(meta)
    allowed = _EDITABLE_FIELDS | {field["key"] for field in effective}
    bad_keys = set(normalized_fields.keys()) - allowed
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
            before_data=data,
            details=failure_details(op="edit_entry", forbidden=sorted(bad_keys), allowed=sorted(allowed)),
        )

    for field_def in effective:
        fkey = field_def["key"]
        if fkey not in normalized_fields:
            continue
        foptions = field_def.get("options")
        frequired = field_def.get("required", False)
        raw_val = normalized_fields.get(fkey)
        field_text = str(raw_val or "").strip()

        if frequired and not field_text:
            return api._failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_field_options",
                message=f"'{fkey}' is required and cannot be empty",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
            )

        if field_text and foptions and field_text not in foptions:
            return api._failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_field_options",
                message=f"'{fkey}' must come from predefined options",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"field": fkey, "value": field_text, "options": foptions},
            )

        # Only coerce to string for option-bearing or text fields;
        # preserve original type for others (int, float, etc.)
        if foptions or field_def.get("type") in (None, "str"):
            normalized_fields[fkey] = field_text
        else:
            normalized_fields[fkey] = raw_val

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
        payload = {
            "ok": True,
            "dry_run": True,
            "preview": {
                "record_id": record_id,
                "before": before,
                "after": dict(normalized_fields),
            },
        }
        if alias_warnings:
            payload["warnings"] = list(alias_warnings)
        return payload

    try:
        split_fields = split_record_fields(record, meta)
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
                details=edit_entry_details(
                    record_id=record_id,
                    box=record.get("box"),
                    position=record.get("position"),
                    field_changes={k: (before[k], normalized_fields[k]) for k in normalized_fields},
                    fields=split_fields.get("fields"),
                    legacy_fields=split_fields.get("legacy_fields"),
                ),
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
            "before": before,
            "after": dict(normalized_fields),
        },
        "backup_path": _backup_path,
    }
    if alias_warnings:
        payload["warnings"] = list(alias_warnings)
    return payload
