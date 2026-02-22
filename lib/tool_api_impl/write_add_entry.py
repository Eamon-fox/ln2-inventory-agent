"""Add-entry write-operation implementations for Tool API."""

from copy import deepcopy

from ..custom_fields import (
    get_cell_line_options,
    get_effective_fields,
    get_required_field_keys,
    is_cell_line_required,
)
from ..operations import check_position_conflicts, get_next_id
from ..position_fmt import get_position_range
from ..validators import validate_box, validate_position
from ..yaml_ops import load_yaml, write_yaml
from .write_common import api


_ADD_STRUCTURAL_FIELDS = {"cell_line", "note"}


def _get_addable_field_keys(meta):
    """Return (allowed_keys, user_field_keys) for add_entry fields payload."""
    user_field_keys = {
        str(field.get("key"))
        for field in get_effective_fields(meta)
        if isinstance(field, dict) and field.get("key")
    }
    allowed_keys = set(_ADD_STRUCTURAL_FIELDS) | user_field_keys
    return allowed_keys, user_field_keys


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
        normalized_positions = api._normalize_positions_input(positions, layout=layout)
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
            details={"positions": positions},
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
                details={"position": pos},
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
            details={"box": box},
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
            details={"box": box, "positions": list(normalized_positions), "conflict_count": len(conflicts)},
            extra={"conflicts": conflicts},
        )

    meta = data.get("meta", {})
    allowed_field_keys, user_field_keys = _get_addable_field_keys(meta)
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
            details={"forbidden": bad_keys, "allowed": sorted(allowed_field_keys)},
        )

    required_keys = get_required_field_keys(meta)
    missing = [k for k in sorted(required_keys) if not fields.get(k)]

    cell_line_text = str(fields.get("cell_line") or "").strip()
    if is_cell_line_required(meta) and not cell_line_text:
        missing.append("cell_line")

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
            details={"missing": missing},
        )

    if cell_line_text:
        cell_line_options = get_cell_line_options(meta)
        if not cell_line_options:
            return None, api._failure_result(
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
            return None, api._failure_result(
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

        fields["cell_line"] = cell_line_text

    return {
        "positions": normalized_positions,
        "records": records,
        "fields": fields,
        "user_field_keys": user_field_keys,
    }, None


def _build_add_entry_records(records, *, box, positions, frozen_at, fields, user_field_keys):
    # Tube-level model: one record == one physical tube.
    # Add multiple tubes by creating multiple records, one per position.
    next_id = get_next_id(records)
    new_records = []
    created = []
    cell_line = fields.pop("cell_line", None)
    raw_note = fields.pop("note", None)
    note_value = None
    if raw_note is not None:
        note_text = str(raw_note).strip()
        note_value = note_text or None

    for offset, pos in enumerate(list(positions)):
        tube_id = next_id + offset
        rec = {
            "id": tube_id,
            "cell_line": cell_line or "",
            "note": note_value,
            "box": box,
            "position": int(pos),
            "frozen_at": frozen_at,
        }
        for key, value in fields.items():
            if key in user_field_keys:
                rec[key] = value
        new_records.append(rec)
        created.append({"id": tube_id, "box": box, "position": int(pos)})

    preview = {
        "new_ids": [item["id"] for item in created],
        "count": len(created),
        "box": box,
        "positions": list(int(p) for p in positions),
        "frozen_at": frozen_at,
        "note": note_value,
        "fields": fields,
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
                details={
                    "new_ids": [item["id"] for item in created],
                    "count": len(created),
                    "box": box,
                    "positions": list(int(p) for p in positions),
                },
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
                details={
                    "new_ids": [item["id"] for item in created],
                    "count": len(created),
                    "box": box,
                    "positions": list(int(p) for p in positions),
                    "fields": fields,
                },
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
            details={
                "new_ids": [item["id"] for item in created],
                "count": len(created),
                "box": box,
            },
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
        fields: dict of user-configurable field values (e.g. cell_line, note, and keys in meta.custom_fields)
    """
    action = "add_entry"
    tool_name = "tool_add_entry"
    fields = dict(fields or {})
    tool_input = {
        "box": box,
        "positions": list(positions) if isinstance(positions, list) else positions,
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
        payload={"frozen_at": frozen_at, "positions": positions},
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
            details={"load_error": str(exc)},
        )

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
        return {
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

    return {
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
