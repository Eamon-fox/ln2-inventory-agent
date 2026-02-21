"""Shared helpers for Tool API write-operation modules."""


class _ApiProxy:
    def __getattr__(self, name):
        from .. import tool_api as _api_mod

        return getattr(_api_mod, name)


api = _ApiProxy()


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
    thaw_events = candidate_records[record_index].get("thaw_events")
    if thaw_events is None:
        candidate_records[record_index]["thaw_events"] = []
        thaw_events = candidate_records[record_index]["thaw_events"]
    if isinstance(thaw_events, list):
        return thaw_events, None
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
    thaw_events, failure = ensure_record_events_list_or_failure(
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
        thaw_events.extend(new_events)
    else:
        thaw_events.append(new_events)
    return None


def build_batch_write_details(*, operations, action_en, date_str):
    return {
        "count": len(operations),
        "action": action_en,
        "date": date_str,
    }


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
