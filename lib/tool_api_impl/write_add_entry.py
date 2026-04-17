"""Add-entry write-operation implementations for Tool API."""

from copy import deepcopy

from ..custom_fields import (
    get_effective_fields,
    get_required_field_keys,
)
from ..field_schema import normalize_input_fields
from ..legacy_field_policy import PHASE_STAGING
from ..migrate_cell_line_policy import normalize_field_options_policy_data
from ..operations import check_position_conflicts, get_next_id
from ..position_fmt import get_position_range
from ..validators import validate_box, validate_position
from ..yaml_ops import load_yaml, write_yaml
from .audit_details import add_entry_details, failure_details
from .write_common import api


def _get_addable_field_keys(meta, *, box=None, inventory=None):
    """Return (allowed_keys, effective_field_keys) for add_entry fields payload."""
    effective_field_keys = {
        str(field.get("key"))
        for field in get_effective_fields(
            meta,
            box=box,
            inventory=inventory,
            phase=PHASE_STAGING,
        )
        if isinstance(field, dict) and field.get("key")
    }
    return effective_field_keys, effective_field_keys


def _validate_add_entry_request_data(
    *,
    data,
    box,
    positions,
    fields,
    yaml_path,
    action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    layout = api._get_layout(data)
    _pos_lo, _pos_hi = get_position_range(layout)

    try:
        normalized_positions = api.normalize_positions_input(positions, layout=layout)
    except ValueError as exc:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_position",
            message=str(exc),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(op="add_entry", positions=positions),
        )

    if not normalized_positions:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="empty_positions",
            message="At least one position is required",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    for pos in normalized_positions:
        if not validate_position(pos, layout):
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_position",
                message=f"Position must be between {_pos_lo}-{_pos_hi}",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details=failure_details(op="add_entry", position=pos),
            )

    if not validate_box(box, layout):
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Box must be within {api._format_box_constraint(layout)}",
            actor_context=actor_context,
            tool_input=tool_input,
            details=failure_details(op="add_entry", box=box),
        )

    records = data.get("inventory", [])
    conflicts = check_position_conflicts(records, box, normalized_positions)
    if conflicts:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="position_conflict",
            message="Position conflict",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(op="add_entry", box=box, positions=list(normalized_positions), conflict_count=len(conflicts)),
            extra={"conflicts": conflicts},
        )

    meta = data.get("meta", {})
    alias_result = normalize_input_fields(fields, meta)
    if not alias_result.get("ok"):
        return None, api._failure_result(
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
                op="add_entry",
                alias_hits=alias_result.get("alias_hits"),
            ),
        )
    fields = dict(alias_result.get("fields") or {})
    alias_warnings = list(alias_result.get("warnings") or [])

    allowed_field_keys, effective_field_keys = _get_addable_field_keys(
        meta,
        box=box,
        inventory=records,
    )
    bad_keys = sorted(set(fields.keys()) - allowed_field_keys)
    if bad_keys:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="forbidden_fields",
            message=f"These fields are not allowed for add_entry: {', '.join(bad_keys)}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(op="add_entry", forbidden=bad_keys, allowed=sorted(allowed_field_keys)),
        )

    # Check required fields across all effective fields.
    required_keys = get_required_field_keys(
        meta,
        box=box,
        inventory=records,
        phase=PHASE_STAGING,
    )
    missing = [k for k in sorted(required_keys) if not str(fields.get(k) or "").strip()]

    if missing:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="missing_required_fields",
            message=f"Missing required fields: {', '.join(missing)}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(op="add_entry", missing=missing),
        )

    # Validate option-bearing fields
    effective = get_effective_fields(
        meta,
        box=box,
        inventory=records,
        phase=PHASE_STAGING,
    )
    for field_def in effective:
        fkey = field_def["key"]
        foptions = field_def.get("options")
        if not foptions:
            continue
        field_val = str(fields.get(fkey) or "").strip()
        if not field_val:
            continue
        if field_val not in foptions:
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_field_options",
                message=f"'{fkey}' must come from predefined options",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"field": fkey, "value": field_val, "options": foptions},
            )
        fields[fkey] = field_val

    return {
        "positions": normalized_positions,
        "records": records,
        "fields": fields,
        "user_field_keys": effective_field_keys,
        "alias_warnings": alias_warnings,
    }, None


def _build_add_entry_records(records, *, box, positions, frozen_at, fields, user_field_keys):
    # Tube-level model: one record == one physical tube.
    # Add multiple tubes by creating multiple records, one per position.
    next_id = get_next_id(records)
    new_records = []
    created = []

    for offset, pos in enumerate(list(positions)):
        tube_id = next_id + offset
        rec = {
            "id": tube_id,
            "box": box,
            "position": int(pos),
            "frozen_at": frozen_at,
        }
        # Write all effective fields uniformly.
        for key in user_field_keys:
            value = fields.get(key)
            if isinstance(value, str):
                value = value.strip() or None
            rec[key] = value if value is not None else ""
        new_records.append(rec)
        created.append({"id": tube_id, "box": box, "position": int(pos)})

    preview = {
        "new_ids": [item["id"] for item in created],
        "count": len(created),
        "box": box,
        "positions": list(int(p) for p in positions),
        "frozen_at": frozen_at,
        "fields": dict(fields),
        "created": created,
    }

    return {
        "new_records": new_records,
        "created": created,
        "preview": preview,
        "fields": fields,
    }


def _persist_add_entry(
    *,
    data,
    new_records,
    created,
    box,
    positions,
    frozen_at,
    fields,
    yaml_path,
    action,
    source,
    tool_name,
    actor_context,
    tool_input,
    auto_backup,
    request_backup_path,
):
    try:
        candidate_data = deepcopy(data)
        candidate_inventory = candidate_data.setdefault("inventory", [])
        if not isinstance(candidate_inventory, list):
            validation_error = api._validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, api._failure_result(
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
                errors_detail=validation_error.get("errors_detail"),
            )

        candidate_inventory.extend(new_records)
        validation_error = api._validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "Validation failed",
                "errors": [],
            }
            return None, api._failure_result(
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
                errors_detail=validation_error.get("errors_detail"),
                details=failure_details(
                    op="add_entry",
                    record_ids=[item["id"] for item in created],
                    box=box,
                    positions=list(int(p) for p in positions),
                ),
            )

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
                details=add_entry_details(
                    record_ids=[item["id"] for item in created],
                    box=box,
                    positions=list(int(p) for p in positions),
                    frozen_at=frozen_at,
                    fields=fields,
                ),
                tool_input={
                    "box": box,
                    "positions": list(int(p) for p in positions),
                    "frozen_at": frozen_at,
                    "fields": fields,
                },
            ),
        )
    except Exception as exc:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Add failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details=failure_details(
                op="add_entry",
                record_ids=[item["id"] for item in created],
                box=box,
            ),
        )

    return _backup_path, None


def _tool_add_entry_impl(
    yaml_path,
    box,
    positions,
    frozen_at,
    fields=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Add a new frozen entry using the shared tool flow.

    Args:
        fields: dict of effective field values exposed by the active field policy
    """
    action = "add_entry"
    tool_name = "tool_add_entry"
    fields = dict(fields or {})
    tool_input = {
        "box": box,
        "positions": list(positions) if isinstance(positions, list) else positions,
        "stored_at": frozen_at,
        "frozen_at": frozen_at,
        "fields": fields,
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
        payload={"stored_at": frozen_at, "positions": positions},
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
            details=failure_details(op="add_entry", load_error=str(exc)),
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

    prepared, failure = _validate_add_entry_request_data(
        data=data,
        box=box,
        positions=positions,
        fields=fields,
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    positions = prepared["positions"]
    records = prepared["records"]
    fields = prepared["fields"]
    user_field_keys = prepared["user_field_keys"]
    alias_warnings = prepared.get("alias_warnings") or []

    built = _build_add_entry_records(
        records,
        box=box,
        positions=positions,
        frozen_at=frozen_at,
        fields=fields,
        user_field_keys=user_field_keys,
    )
    new_records = built["new_records"]
    created = built["created"]
    preview = built["preview"]
    fields = built["fields"]

    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "preview": preview,
            "result": {
                "new_id": created[0]["id"] if created else None,
                "new_ids": [item["id"] for item in created],
                "count": len(created),
                "created": created,
                "records": new_records,
            },
        }
        if alias_warnings:
            payload["warnings"] = list(alias_warnings)
        return payload

    _backup_path, failure = _persist_add_entry(
        data=data,
        new_records=new_records,
        created=created,
        box=box,
        positions=positions,
        frozen_at=frozen_at,
        fields=fields,
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if failure:
        return failure

    payload = {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {
            "new_id": created[0]["id"] if created else None,
            "new_ids": [item["id"] for item in created],
            "count": len(created),
            "created": created,
            "records": new_records,
        },
        "backup_path": _backup_path,
    }
    if alias_warnings:
        payload["warnings"] = list(alias_warnings)
    return payload
