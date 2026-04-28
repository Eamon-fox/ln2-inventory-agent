import re
from typing import Any, Dict, Optional

from app_gui.i18n import tr


_LEGACY_MOJIBAKE_MAP = {
    # Legacy mojibake payloads preserved for backward-compatible sanitization.
    "\u9350\u6b0f\u53c6\u741a\ue0a6\u6a06\u59dd\ue76e\u7d30\u6434\u64b3\u74e8\u7039\u5c7e\u66a3\u93ac\u0444\u724e\u6960\u5c7d\u3051\u7490": "Write blocked: integrity validation failed",
    "\u7481\u677f\u7d8d": "Record",
    "\u95b2\u5d85\ue632\u9428": "Duplicate",
    "\u6d63\u5d87\u7586\u9350\u832c\u734a": "Position conflict",
}




_QT_FONT_FACE_FROM_HDC_RE = re.compile(
    r'qt\.qpa\.fonts:\s*DirectWrite:\s*CreateFontFaceFromHDC\(\)\s*failed.*?'
    r'QFontDef\(Family="(?P<family>[^"]+)".*?dpi=(?P<dpi>\d+)',
    re.IGNORECASE | re.DOTALL,
)

_MOVE_TARGET_OCCUPIED_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+target\s+box\s+"
    r"(?P<box>\d+)\s+position\s+(?P<position>\d+)\s+is\s+occupied\s+by\s+record\s+#(?P<occupant_id>\d+)",
    re.IGNORECASE,
)
_MOVE_TARGET_ALREADY_MOVED_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+target\s+position\s+"
    r"(?P<position>\d+)\s+has\s+already\s+been\s+moved\s+in\s+this\s+request",
    re.IGNORECASE,
)
_MOVE_TARGET_SAME_RECORD_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+target\s+position\s+"
    r"(?P<position>\d+)\s+already\s+belongs\s+to\s+this\s+record",
    re.IGNORECASE,
)
_MOVE_TARGET_SAME_POSITION_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+source\s+and\s+target\s+positions\s+must\s+differ\s+for\s+move",
    re.IGNORECASE,
)
_MOVE_SOURCE_MISMATCH_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+source\s+position\s+"
    r"(?P<source_position>\d+)\s+does\s+not\s+match\s+current\s+(?P<current_position>\d+)",
    re.IGNORECASE,
)
_MOVE_RECORD_NOT_FOUND_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+record\s+not\s+found",
    re.IGNORECASE,
)
_MOVE_RECORD_INACTIVE_RE = re.compile(
    r"Row\s+(?P<row>\d+)\s+ID\s+(?P<record_id>\d+):\s+record\s+has\s+no\s+active\s+position",
    re.IGNORECASE,
)


_ERROR_DEFAULTS_EN = {
    "backup_create_failed": "Failed to create backup before write.",
    "backup_load_failed": "Failed to load backup file.",
    "backup_not_found": "Backup file not found.",
    "box_not_empty": "Box is not empty.",
    "empty_entries": "At least one entry is required.",
    "empty_positions": "At least one position is required.",
    "export_failed": "Export failed.",
    "forbidden_fields": "Some fields are not allowed for this operation.",
    "integrity_validation_failed": "Write blocked: integrity validation failed.",
    "invalid_action": "Invalid action.",
    "invalid_box": "Invalid box.",
    "invalid_box_layout": "Invalid box layout metadata.",
    "invalid_cell_line": "Invalid cell line.",
    "invalid_cell_line_options": "Cell line options are not configured.",
    "invalid_field_options": "Value is not in the allowed options for this field.",
    "invalid_count": "Count must be greater than 0.",
    "invalid_date": "Invalid date format. Use YYYY-MM-DD.",
    "invalid_execution_mode": "Invalid execution mode.",
    "invalid_max_steps": "Invalid max_steps value.",
    "invalid_meta": "Invalid metadata format.",
    "invalid_mode": "Invalid mode. Use fuzzy/exact/keywords.",
    "invalid_move_target": "Invalid move target.",
    "invalid_operation": "Invalid operation.",
    "invalid_output_path": "Invalid output path.",
    "invalid_position": "Invalid position.",
    "invalid_record_id": "Invalid record ID.",
    "invalid_renumber_mode": "Invalid renumber mode.",
    "invalid_tool_input": "Invalid input.",
    "invalid_tag": "Invalid box tag.",
    "invalid_agent_result": "Invalid agent response payload.",
    "agent_runtime_failed": "Agent runtime failed.",
    "api_key_required": "API key is required.",
    "llm_api_error": "LLM API returned an error.",
    "llm_http_error": "LLM request failed with an HTTP error.",
    "llm_stream_failed": "LLM stream failed.",
    "llm_transport_error": "LLM transport error.",
    "empty_query": "Query cannot be empty.",
    "load_failed": "Failed to load YAML file.",
    "min_box_count": "At least one box must remain.",
    "missing_required_fields": "Missing required fields.",
    "missing_backup_path": "Execute-mode write requires request backup path.",
    "no_backups": "No backups available.",
    "no_plan_store": "Plan storage is not available.",
    "no_fields": "At least one field must be provided.",
    "not_found": "Requested records were not found.",
    "plan_preflight_failed": "Plan preflight failed.",
    "plan_validation_failed": "Plan validation failed.",
    "position_conflict": "Position conflict.",
    "position_not_found": "Position not found in record.",
    "record_not_found": "Record not found.",
    "renumber_mode_required": "renumber_mode is required when removing a middle box.",
    "rollback_backup_invalid": "Selected backup is invalid for current dataset.",
    "rollback_failed": "Rollback failed.",
    "unsupported_box_fields": (
        "Unsupported dataset model: meta.box_fields is no longer supported. "
        "Use a single global meta.custom_fields schema."
    ),
    "invalid_dataset_name": "Dataset name is invalid.",
    "dataset_name_unchanged": "Dataset name is unchanged.",
    "dataset_name_conflict": "Target dataset already exists.",
    "dataset_rename_failed": "Failed to rename dataset.",
    "dataset_delete_failed": "Failed to delete dataset.",
    "path.policy_invalid": "Path policy is invalid.",
    "path.invalid_input": "Path input is invalid.",
    "path.absolute_not_allowed": "Absolute path is not allowed.",
    "path.escape_detected": "Path escapes allowed scope.",
    "path.scope_read_denied": "Read path is outside allowed scope.",
    "path.scope_write_denied": "Write operations are allowed only under migrate/.",
    "path.scope_workdir_denied": "workdir must stay within repository scope.",
    "path.backup_scope_denied": "Backup path must stay under dataset backups/.",
    "path.not_found": "Path not found.",
    "path.not_file": "Path is not a file.",
    "validation_failed": "Validation failed.",
    "write_failed": "Failed to write YAML file.",
    "write_requires_execute_mode": "Writes are only allowed during plan execution.",
    "unknown_tool": "Unknown tool.",
}


_DETAIL_FIRST_ERROR_CODES = frozenset(
    {
        "batch_validation_failed",
        "integrity_validation_failed",
        "plan_preflight_failed",
        "plan_validation_failed",
        "position_conflict",
        "validation_failed",
    }
)

_GENERIC_ERROR_MESSAGES = frozenset(
    {
        "batch operation parameter validation failed",
        "plan preflight failed",
        "plan validation failed",
        "takeout/move parameter validation failed",
        "validation failed",
        "validation failed.",
        "write blocked: integrity validation failed",
        "write blocked: integrity validation failed.",
    }
)


def _sanitize_legacy_mojibake(text: str) -> str:
    clean = str(text or "")
    if not clean:
        return ""
    for src, dst in _LEGACY_MOJIBAKE_MAP.items():
        clean = clean.replace(src, dst)
    return clean


def _localize_known_runtime_warning(text: str) -> str:
    clean = str(text or "")
    if not clean:
        return ""

    match = _QT_FONT_FACE_FROM_HDC_RE.search(clean)
    if match:
        family = str(match.group("family") or "Unknown")
        dpi = str(match.group("dpi") or "?")
        return tr(
            "errors.qtFontFaceFromHdcFailed",
            default=(
                'Font rendering warning: failed to load "{family}" via DirectWrite (DPI {dpi}). '
                "The app will use a fallback font."
            ),
            family=family,
            dpi=dpi,
        )

    return clean


def _humanize_error_code(error_code: str) -> str:
    text = str(error_code or "").strip().replace("_", " ")
    return text.capitalize() if text else ""


def _is_generic_error_message(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return True
    return text in _GENERIC_ERROR_MESSAGES


def _localize_validation_detail(message: str) -> str:
    text = _sanitize_legacy_mojibake(str(message or "").strip())
    if not text:
        return ""

    patterns = [
        (
            _MOVE_TARGET_OCCUPIED_RE,
            "errors.detail.moveTargetOccupied",
            "Row {row}, record ID {record_id}: target slot Box {box} Position {position} is occupied by record #{occupant_id}.",
        ),
        (
            _MOVE_TARGET_ALREADY_MOVED_RE,
            "errors.detail.moveTargetAlreadyMoved",
            "Row {row}, record ID {record_id}: target position {position} has already been moved in this request.",
        ),
        (
            _MOVE_TARGET_SAME_RECORD_RE,
            "errors.detail.moveTargetSameRecord",
            "Row {row}, record ID {record_id}: target position {position} already belongs to this record.",
        ),
        (
            _MOVE_TARGET_SAME_POSITION_RE,
            "errors.detail.moveTargetSamePosition",
            "Row {row}, record ID {record_id}: source and target positions must differ for move.",
        ),
        (
            _MOVE_SOURCE_MISMATCH_RE,
            "errors.detail.moveSourceMismatch",
            "Row {row}, record ID {record_id}: source position {source_position} does not match current position {current_position}.",
        ),
        (
            _MOVE_RECORD_NOT_FOUND_RE,
            "errors.detail.moveRecordNotFound",
            "Row {row}, record ID {record_id}: record not found.",
        ),
        (
            _MOVE_RECORD_INACTIVE_RE,
            "errors.detail.moveRecordInactive",
            "Row {row}, record ID {record_id}: record has no active position.",
        ),
    ]
    for pattern, key, default in patterns:
        match = pattern.fullmatch(text)
        if not match:
            continue
        return tr(key, default=default, **match.groupdict())
    return _localize_known_runtime_warning(text)


def _format_error_list(errors: Any) -> str:
    if not isinstance(errors, list):
        return ""
    lines = []
    for raw in errors:
        if isinstance(raw, dict):
            text = str(raw.get("message") or raw.get("error_code") or "").strip()
        else:
            text = str(raw or "").strip()
        if text:
            lines.append(_localize_validation_detail(text))
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return "\n".join(f"- {line}" for line in lines[:5])


def _specific_payload_message(payload: Dict[str, Any], code: str) -> str:
    raw_message = _localize_validation_detail(str(payload.get("message") or "").strip())
    detail_message = _format_error_list(payload.get("errors"))

    if code in _DETAIL_FIRST_ERROR_CODES:
        if detail_message:
            return detail_message
        if raw_message and not _is_generic_error_message(raw_message):
            return raw_message
    return ""


def _coerce_format_kwargs(details: Any) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (list, tuple, set)):
            out[key] = ", ".join(str(item) for item in value)
        else:
            out[key] = value
    return out


def localize_error(
    error_code: Optional[str],
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    fallback: Optional[str] = None,
) -> str:
    code = str(error_code or "").strip()
    raw_message = _localize_known_runtime_warning(
        _sanitize_legacy_mojibake(str(message or "").strip())
    )
    if code:
        key = f"errors.code.{code}"
        kwargs = _coerce_format_kwargs(details)
        default = _ERROR_DEFAULTS_EN.get(code)
        if default:
            text = tr(key, default=default, **kwargs)
            if text and text != key:
                return text
            return default

        text = tr(key, default=key, **kwargs)
        if text and text != key:
            return text
    if raw_message:
        return raw_message
    if code:
        humanized = _humanize_error_code(code)
        if humanized:
            return humanized
    return str(fallback or tr("errors.unknown", default="Unknown error"))


def localize_error_payload(payload: Any, fallback: Optional[str] = None) -> str:
    if not isinstance(payload, dict):
        return str(fallback or tr("errors.unknown", default="Unknown error"))
    has_error = bool(str(payload.get("error_code") or "").strip()) or bool(str(payload.get("message") or "").strip())
    if not has_error and fallback is not None:
        return str(fallback)
    code = str(payload.get("error_code") or "").strip()
    specific_message = _specific_payload_message(payload, code)
    if specific_message:
        return specific_message
    return localize_error(
        code,
        message=payload.get("message"),
        details=payload.get("details"),
        fallback=fallback,
    )
