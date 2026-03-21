"""Shared helpers for Tool API write-operation modules."""

from copy import deepcopy

from ..schema_aliases import (
    CANONICAL_STORAGE_EVENTS_KEY,
    LEGACY_STORAGE_EVENTS_KEY,
)
from .. import tool_api_support as api


def _integrity_error_payload(candidate_data):
    return api._validate_data_or_error(candidate_data) or {
        "error_code": "integrity_validation_failed",
        "message": "Validation failed",
        "errors": [],
    }


def build_integrity_failure(
    *,
    candidate_data,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data=None,
    details=None,
    extra=None,
):
    payload = _integrity_error_payload(candidate_data)
    return api._failure_result(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        error_code=payload.get("error_code", "integrity_validation_failed"),
        message=payload.get("message", "Validation failed"),
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
        errors=payload.get("errors"),
        details=details,
        extra=extra,
    )


def get_candidate_inventory_or_failure(
    *,
    candidate_data,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data=None,
):
    candidate_records = candidate_data.get("inventory", [])
    if isinstance(candidate_records, list):
        return candidate_records, None
    return None, build_integrity_failure(
        candidate_data=candidate_data,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
    )


def ensure_record_events_list_or_failure(
    *,
    candidate_data,
    candidate_records,
    record_index,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data=None,
):
    record = candidate_records[record_index]
    if not isinstance(record, dict):
        return None, build_integrity_failure(
            candidate_data=candidate_data,
            yaml_path=yaml_path,
            audit_action=audit_action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=before_data,
        )

    storage_events = record.get(CANONICAL_STORAGE_EVENTS_KEY)
    legacy_events = record.get(LEGACY_STORAGE_EVENTS_KEY)
    if storage_events is None and legacy_events is not None:
        storage_events = deepcopy(legacy_events)
        record[CANONICAL_STORAGE_EVENTS_KEY] = storage_events
    elif storage_events is None:
        storage_events = []
        record[CANONICAL_STORAGE_EVENTS_KEY] = storage_events
    record.pop(LEGACY_STORAGE_EVENTS_KEY, None)
    if isinstance(storage_events, list):
        return storage_events, None
    return None, build_integrity_failure(
        candidate_data=candidate_data,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
    )


def append_record_events_or_failure(
    *,
    candidate_data,
    candidate_records,
    record_index,
    new_events,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data=None,
):
    storage_events, failure = ensure_record_events_list_or_failure(
        candidate_data=candidate_data,
        candidate_records=candidate_records,
        record_index=record_index,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
    )
    if failure:
        return failure
    if isinstance(new_events, list):
        storage_events.extend(new_events)
    else:
        storage_events.append(new_events)
    return None


def build_write_failed_result(
    *,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    before_data,
    exc,
    message_prefix,
    details=None,
):
    return api._failure_result(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        error_code="write_failed",
        message=f"{message_prefix}: {exc}",
        actor_context=actor_context,
        tool_input=tool_input,
        before_data=before_data,
        details=details,
    )
