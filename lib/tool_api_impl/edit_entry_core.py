"""Shared edit-entry domain logic for single and batch write paths."""

from __future__ import annotations

from typing import Any, Callable

from ..custom_fields import get_effective_fields
from ..field_schema import normalize_input_fields, split_record_fields
from ..legacy_field_policy import PHASE_STAGING, resolve_legacy_field_policy
from ..migrate_cell_line_policy import normalize_field_options_policy_data
from ..operations import find_record_by_id
from ..schema_aliases import (
    CANONICAL_STORED_AT_KEY,
    LEGACY_STORED_AT_KEY,
    canonicalize_inventory_document,
    expand_structural_aliases_in_sections,
    normalize_structural_alias_input_map,
)
from .audit_details import edit_entry_details, failure_details

_EDITABLE_FIELDS = {CANONICAL_STORED_AT_KEY, LEGACY_STORED_AT_KEY}


def prepare_edit_document(data: Any) -> dict[str, Any]:
    """Canonicalize a loaded inventory document before edit mutation."""
    data, alias_errors = canonicalize_inventory_document(data)
    if alias_errors:
        return {
            "ok": False,
            "error_code": "integrity_validation_failed",
            "message": "Edit blocked: structural alias conflict",
            "errors": alias_errors,
            "data": data if isinstance(data, dict) else None,
        }

    normalized = normalize_field_options_policy_data(data)
    if not normalized.get("ok"):
        return {
            "ok": False,
            "error_code": normalized.get("error_code", "normalize_failed"),
            "message": normalized.get("message", "Failed to normalize field options policy."),
            "data": data if isinstance(data, dict) else None,
        }
    return {"ok": True, "data": normalized.get("data")}


def editable_fields_for_data(data: dict[str, Any]) -> set[str]:
    """Return the edit input keys accepted for this document."""
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    inventory = data.get("inventory", []) if isinstance(data, dict) else []
    fields = get_effective_fields(
        meta,
        inventory=inventory,
        phase=PHASE_STAGING,
    )
    editable = _EDITABLE_FIELDS | {field["key"] for field in fields}
    policy = resolve_legacy_field_policy(
        meta,
        inventory,
        declared_fields=(meta or {}).get("custom_fields"),
        phase=PHASE_STAGING,
    )
    editable.update(set(policy.get("staging_input_keys") or set()))
    return editable


def effective_fields_for_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return effective field definitions used for edit value validation."""
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    inventory = data.get("inventory", []) if isinstance(data, dict) else []
    return get_effective_fields(meta, inventory=inventory, phase=PHASE_STAGING)


def _entry_payload(index: int | None, payload: dict[str, Any]) -> dict[str, Any]:
    if index is not None:
        payload.setdefault("index", index)
    return payload


def edit_entry_error(
    index: int | None,
    error_code: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error_code": str(error_code or "validation_failed"),
        "message": str(message or "Validation failed"),
    }
    payload.update(extra)
    return _entry_payload(index, payload)


def normalize_edit_fields(
    *,
    fields: Any,
    meta: dict[str, Any],
    index: int | None = None,
) -> dict[str, Any]:
    """Normalize one edit fields payload and preserve alias warnings."""
    if not isinstance(fields, dict) or not fields:
        return edit_entry_error(index, "invalid_tool_input", "fields must be a non-empty object")

    alias_result = normalize_input_fields(fields, meta)
    if not alias_result.get("ok"):
        return edit_entry_error(
            index,
            alias_result.get("error_code", "deprecated_field_alias_removed"),
            alias_result.get("message", "Deprecated field alias is no longer accepted."),
            details=failure_details(
                op="edit_entry",
                alias_hits=alias_result.get("alias_hits"),
            ),
        )

    alias_warnings = list(alias_result.get("warnings") or [])
    normalized_fields = dict(alias_result.get("fields") or {})
    normalized_fields, alias_errors = normalize_structural_alias_input_map(
        normalized_fields,
        scope="fields",
    )
    if alias_errors:
        return edit_entry_error(
            index,
            "invalid_field_alias_conflict",
            alias_errors[0],
            alias_warnings=alias_warnings,
        )
    return {
        "ok": True,
        "fields": normalized_fields,
        "alias_warnings": alias_warnings,
    }


def validate_and_coerce_edit_fields(
    *,
    normalized_fields: dict[str, Any],
    effective_fields: list[dict[str, Any]],
    allowed_fields: set[str],
    index: int | None = None,
) -> dict[str, Any]:
    """Validate editable field names and coerce values in place."""
    bad_keys = set(normalized_fields.keys()) - allowed_fields
    if bad_keys:
        return edit_entry_error(
            index,
            "forbidden_fields",
            f"These fields are not editable: {', '.join(sorted(bad_keys))}",
            details=failure_details(
                op="edit_entry",
                forbidden=sorted(bad_keys),
                allowed=sorted(allowed_fields),
            ),
        )

    for field_def in effective_fields:
        fkey = field_def["key"]
        if fkey not in normalized_fields:
            continue
        foptions = field_def.get("options")
        frequired = field_def.get("required", False)
        raw_val = normalized_fields.get(fkey)
        field_text = str(raw_val or "").strip()

        if frequired and not field_text:
            return edit_entry_error(
                index,
                "invalid_field_options",
                f"'{fkey}' is required and cannot be empty",
            )

        if field_text and foptions and field_text not in foptions:
            return edit_entry_error(
                index,
                "invalid_field_options",
                f"'{fkey}' must come from predefined options",
                details={"field": fkey, "value": field_text, "options": foptions},
            )

        if foptions or field_def.get("type") in (None, "str"):
            normalized_fields[fkey] = field_text
        else:
            normalized_fields[fkey] = raw_val

    return {"ok": True, "fields": normalized_fields}


def apply_edit_to_candidate(
    *,
    candidate_data: dict[str, Any],
    record_id: int,
    fields: Any,
    validate_fn: Callable[..., dict[str, Any] | None],
    effective_fields: list[dict[str, Any]] | None = None,
    allowed_fields: set[str] | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    """Apply one normalized edit to an in-memory candidate document."""
    meta = candidate_data.get("meta", {}) if isinstance(candidate_data, dict) else {}
    inventory = candidate_data.get("inventory", []) if isinstance(candidate_data, dict) else []
    record_index, candidate_record = find_record_by_id(inventory, record_id)
    if record_index is None or candidate_record is None:
        return edit_entry_error(index, "record_not_found", f"Record ID={record_id} not found")

    normalized = normalize_edit_fields(fields=fields, meta=meta, index=index)
    if not normalized.get("ok"):
        return normalized

    normalized_fields = dict(normalized.get("fields") or {})
    value_result = validate_and_coerce_edit_fields(
        normalized_fields=normalized_fields,
        effective_fields=effective_fields if effective_fields is not None else effective_fields_for_data(candidate_data),
        allowed_fields=allowed_fields if allowed_fields is not None else editable_fields_for_data(candidate_data),
        index=index,
    )
    if not value_result.get("ok"):
        return value_result

    before = {key: candidate_record.get(key) for key in normalized_fields}
    for key, value in normalized_fields.items():
        candidate_record[key] = value

    validation_error = validate_fn(candidate_data, changed_ids=[record_id])
    if validation_error:
        return edit_entry_error(
            index,
            validation_error.get("error_code", "integrity_validation_failed"),
            validation_error.get("message", "Validation failed"),
            errors=validation_error.get("errors"),
            errors_detail=validation_error.get("errors_detail"),
        )

    response_sections = {
        "before": dict(before),
        "after": dict(normalized_fields),
    }
    expand_structural_aliases_in_sections(response_sections)

    split_fields = split_record_fields(candidate_record, meta)
    audit_details = edit_entry_details(
        record_id=record_id,
        box=candidate_record.get("box"),
        position=candidate_record.get("position"),
        field_changes={key: (before[key], normalized_fields[key]) for key in normalized_fields},
        fields=split_fields.get("fields"),
        legacy_fields=split_fields.get("legacy_fields"),
    )

    return _entry_payload(
        index,
        {
            "ok": True,
            "record_id": record_id,
            "before": response_sections["before"],
            "after": response_sections["after"],
            "normalized_fields": normalized_fields,
            "alias_warnings": list(normalized.get("alias_warnings") or []),
            "audit_details": audit_details,
        },
    )
