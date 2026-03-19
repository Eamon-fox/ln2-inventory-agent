"""Shared YAML validation entrypoints for tools and other callers."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .import_validation_core import validate_inventory_document
from .inventory_paths import is_managed_inventory_yaml_path
from .validators import format_validation_errors, validate_inventory
from .yaml_ops import load_yaml


VALIDATION_MODE_AUTO = "auto"
VALIDATION_MODE_CURRENT_INVENTORY = "current_inventory"
VALIDATION_MODE_DOCUMENT = "document"
VALIDATION_MODE_META_ONLY = "meta_only"

_VALIDATION_MODES = {
    VALIDATION_MODE_AUTO,
    VALIDATION_MODE_CURRENT_INVENTORY,
    VALIDATION_MODE_DOCUMENT,
    VALIDATION_MODE_META_ONLY,
}
_YAML_SUFFIXES = {".yaml", ".yml"}


def _build_report(errors: List[str], warnings: List[str], *, mode: str) -> Dict[str, Any]:
    errors = list(errors or [])
    warnings = list(warnings or [])
    return {
        "mode": str(mode or ""),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def _error_payload(
    error_code: str,
    message: str,
    *,
    errors: List[str] = None,
    warnings: List[str] = None,
    mode: str = "",
) -> Dict[str, Any]:
    return {
        "ok": False,
        "error_code": str(error_code or "unknown_error"),
        "message": str(message or ""),
        "report": _build_report(errors, warnings, mode=mode),
    }


def _summarize_ok(warnings: List[str]) -> str:
    warnings = list(warnings or [])
    if not warnings:
        return "Validation passed."
    return f"Validation passed with {len(warnings)} warning(s)."


def normalize_validation_mode(mode: str) -> str:
    normalized = str(mode or VALIDATION_MODE_AUTO).strip().lower() or VALIDATION_MODE_AUTO
    if normalized not in _VALIDATION_MODES:
        raise ValueError(
            f"invalid validation mode {mode!r}; expected one of {sorted(_VALIDATION_MODES)}"
        )
    return normalized


def detect_validation_mode(source_path: str = "") -> str:
    candidate = os.path.abspath(str(source_path or "").strip()) if str(source_path or "").strip() else ""
    if candidate and is_managed_inventory_yaml_path(candidate):
        return VALIDATION_MODE_CURRENT_INVENTORY
    return VALIDATION_MODE_DOCUMENT


def validate_yaml_data(
    data: Any,
    *,
    source_path: str = "",
    mode: str = VALIDATION_MODE_AUTO,
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    requested_mode = normalize_validation_mode(mode)
    effective_mode = (
        detect_validation_mode(source_path)
        if requested_mode == VALIDATION_MODE_AUTO
        else requested_mode
    )

    if effective_mode == VALIDATION_MODE_CURRENT_INVENTORY:
        errors, warnings = validate_inventory(data)
    elif effective_mode == VALIDATION_MODE_META_ONLY:
        errors, warnings = validate_inventory_document(
            data,
            skip_record_validation=True,
        )
    else:
        errors, warnings = validate_inventory_document(data)

    errors = list(errors or [])
    warnings = list(warnings or [])
    if fail_on_warnings and warnings:
        errors.extend([f"Warning treated as error: {item}" for item in warnings])

    if errors:
        return _error_payload(
            "validation_failed",
            format_validation_errors(errors, prefix="Validation failed"),
            errors=errors,
            warnings=warnings,
            mode=effective_mode,
        )

    return {
        "ok": True,
        "message": _summarize_ok(warnings),
        "report": _build_report([], warnings, mode=effective_mode),
    }


def validate_yaml_file(
    path: str,
    *,
    mode: str = VALIDATION_MODE_AUTO,
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    candidate = os.path.abspath(str(path or "").strip())
    if not candidate:
        return _error_payload("invalid_path", "YAML path is required.")

    if os.path.splitext(candidate)[1].lower() not in _YAML_SUFFIXES:
        return _error_payload(
            "invalid_path",
            "YAML path must end with .yaml or .yml.",
        )

    if not os.path.isfile(candidate):
        return _error_payload("file_not_found", f"YAML file not found: {candidate}")

    try:
        data = load_yaml(candidate)
    except Exception as exc:
        return _error_payload("load_failed", f"Failed to load YAML: {exc}")

    return validate_yaml_data(
        data,
        source_path=candidate,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
