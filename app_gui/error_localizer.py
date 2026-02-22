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
    "invalid_agent_result": "Invalid agent response payload.",
    "agent_runtime_failed": "Agent runtime failed.",
    "api_key_required": "API key is required.",
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
    "validation_failed": "Validation failed.",
    "write_failed": "Failed to write YAML file.",
    "write_requires_execute_mode": "Writes are only allowed during plan execution.",
    "unknown_tool": "Unknown tool.",
}


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
    return localize_error(
        payload.get("error_code"),
        message=payload.get("message"),
        details=payload.get("details"),
        fallback=fallback,
    )
