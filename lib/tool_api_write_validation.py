"""Write-tool execution gate and request validation helpers."""

from .migrate_cell_line_policy import migrate_cell_line_policy
from .takeout_parser import normalize_action
from .validators import validate_date


_ALLOWED_EXECUTION_MODES = {"direct", "preflight", "execute"}


def _normalize_execution_mode(execution_mode):
    mode = str(execution_mode or "").strip().lower()
    return mode or "direct"


def _enforce_execute_mode_for_source(source):
    """Return True when this caller must execute writes via execute mode.

    Keep plain ``tool_api`` source backward compatible for direct library users,
    while enforcing plan execution for GUI/agent channels.
    """
    src = str(source or "").strip().lower()
    if src in {"", "tool_api"}:
        return False
    return src.startswith("agent") or src.startswith("app_gui") or src.startswith("plan_executor")


def _validate_execution_gate(*, dry_run=False, execution_mode=None, source="tool_api"):
    mode = _normalize_execution_mode(execution_mode)
    if mode not in _ALLOWED_EXECUTION_MODES:
        return {
            "error_code": "invalid_execution_mode",
            "message": "execution_mode must be direct/preflight/execute",
            "details": {"execution_mode": execution_mode},
        }, mode

    if bool(dry_run):
        return None, mode

    if _enforce_execute_mode_for_source(source) and mode != "execute":
        return {
            "error_code": "write_requires_execute_mode",
            "message": "Writes are only allowed during plan execution (save to Plan first, then click Execute).",
            "details": {"execution_mode": mode, "source": source},
        }, mode

    return None, mode


def _validate_add_entry_request(payload):
    frozen_at = payload.get("frozen_at")
    positions = payload.get("positions")
    if not validate_date(frozen_at):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {frozen_at}",
            "details": {"frozen_at": frozen_at},
        }, {}
    if not positions:
        return {
            "error_code": "empty_positions",
            "message": "At least one position is required",
        }, {}
    return None, {}


def _validate_edit_entry_request(payload):
    fields = payload.get("fields")
    if not fields:
        return {
            "error_code": "no_fields",
            "message": "At least one field must be provided",
        }, {}
    if "frozen_at" in fields and not validate_date(fields["frozen_at"]):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {fields['frozen_at']}",
            "details": {"frozen_at": fields["frozen_at"]},
        }, {}
    return None, {}


def _validate_record_takeout_request(payload):
    date_str = payload.get("date_str")
    action = payload.get("action")
    to_position = payload.get("to_position")

    if not validate_date(date_str):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {date_str}",
            "details": {"date": date_str},
        }, {}

    action_en = normalize_action(action)
    if not action_en:
        return {
            "error_code": "invalid_action",
            "message": "Action must be takeout/move",
            "details": {"action": action},
        }, {}

    normalized = {"action_en": action_en, "move_to_position": None}
    if action_en == "move":
        if to_position in (None, ""):
            return {
                "error_code": "invalid_move_target",
                "message": "Move operation requires to_position (target position)",
            }, normalized
        normalized["move_to_position"] = to_position

    return None, normalized


def _validate_batch_takeout_request(payload):
    date_str = payload.get("date_str")
    action = payload.get("action")
    entries = payload.get("entries")

    if not validate_date(date_str):
        return {
            "error_code": "invalid_date",
            "message": f"Invalid date format: {date_str}",
            "details": {"date": date_str},
        }, {}

    if not entries:
        return {
            "error_code": "empty_entries",
            "message": "No entries provided",
        }, {}

    action_en = normalize_action(action)
    if not action_en:
        return {
            "error_code": "invalid_action",
            "message": "Action must be takeout/move",
            "details": {"action": action},
        }, {}

    return None, {"action_en": action_en}


def _validate_adjust_box_count_request(payload):
    operation = payload.get("operation")
    op_text = str(operation or "").strip().lower()
    op_alias = {
        "add": "add",
        "add_boxes": "add",
        "increase": "add",
        "remove": "remove",
        "remove_box": "remove",
        "delete": "remove",
    }
    op = op_alias.get(op_text)
    if not op:
        return {
            "error_code": "invalid_operation",
            "message": "operation must be add/remove",
            "details": {"operation": operation},
        }, {}
    return None, {"op": op}


_WRITE_REQUEST_VALIDATORS = {
    "tool_add_entry": _validate_add_entry_request,
    "tool_edit_entry": _validate_edit_entry_request,
    "tool_record_takeout": _validate_record_takeout_request,
    "tool_batch_takeout": _validate_batch_takeout_request,
    "tool_rollback": lambda _payload: (None, {}),
    "tool_adjust_box_count": _validate_adjust_box_count_request,
}


def _source_is_plan_preflight(source):
    src = str(source or "").strip().lower()
    return src.startswith("plan_executor.preflight")


def validate_write_tool_call(
    *,
    yaml_path,
    action,
    source,
    tool_name,
    tool_input,
    payload,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    before_data=None,
    auto_backup=True,
    request_backup_path=None,
    failure_result_fn,
):
    """Unified write-tool validation gate.

    1) Enforce execute-mode write policy for GUI/agent channels.
    2) Dispatch to each tool's request-level validator.
    3) Return either a normalized success payload or unified failure payload.
    """
    gate_issue, normalized_mode = _validate_execution_gate(
        dry_run=dry_run,
        execution_mode=execution_mode,
        source=source,
    )
    if gate_issue:
        return failure_result_fn(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=gate_issue.get("error_code", "validation_failed"),
            message=gate_issue.get("message", "Write validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=before_data,
            errors=gate_issue.get("errors"),
            details=gate_issue.get("details"),
            extra=gate_issue.get("extra"),
        )

    requires_backup_ref = (
        (not bool(dry_run))
        and normalized_mode == "execute"
        and not _source_is_plan_preflight(source)
    )
    if requires_backup_ref:
        backup_ref = str(request_backup_path or "").strip()
        if not backup_ref:
            return failure_result_fn(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="missing_backup_path",
                message="Execute-mode write requires request_backup_path.",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                details={"execution_mode": normalized_mode, "source": source},
            )

    validator = _WRITE_REQUEST_VALIDATORS.get(tool_name)
    if callable(validator):
        payload_dict = payload if isinstance(payload, dict) else {}
        validator_result = validator(payload_dict)
        if isinstance(validator_result, tuple) and len(validator_result) == 2:
            issue, normalized = validator_result
        else:
            issue, normalized = None, {}
        if issue:
            return failure_result_fn(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code=issue.get("error_code", "validation_failed"),
                message=issue.get("message", "Write validation failed"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                errors=issue.get("errors"),
                details=issue.get("details"),
                extra=issue.get("extra"),
            )
    else:
        normalized = {}

    if (not bool(dry_run)) and normalized_mode == "execute" and tool_name != "tool_rollback":
        migration_result = migrate_cell_line_policy(
            yaml_path=yaml_path,
            dry_run=False,
            auto_backup=False,
            request_backup_path=request_backup_path,
            audit_source="tool_api.validate_write_tool_call",
        )
        if not migration_result.get("ok"):
            migration_code = migration_result.get("error_code", "migration_failed")
            migration_message = migration_result.get("message", "Unknown migration error")
            return failure_result_fn(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code="migration_failed",
                message=(
                    "Write blocked: failed to normalize cell_line policy before write "
                    f"({migration_code}): {migration_message}"
                ),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=before_data,
                details={"migration_error_code": migration_code},
                extra={"migration": migration_result},
            )

    return {
        "ok": True,
        "execution_mode": normalized_mode,
        "normalized": normalized,
    }
