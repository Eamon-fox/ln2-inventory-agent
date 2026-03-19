"""Migration helpers for options-bearing fields and legacy field canonicalization.

This module still powers the dedicated migration command, but its legacy
compatibility behavior is now delegated to ``lib.legacy_field_policy`` so
write-time canonicalization has a single owner.
"""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .custom_fields import (
    get_effective_fields,
    unsupported_box_fields_issue,
)
from .legacy_field_policy import (
    DEFAULT_UNKNOWN_CELL_LINE,
    PHASE_WRITE,
    canonicalize_legacy_document,
)
from .yaml_ops import load_yaml, write_yaml


def _normalize_options_list(raw_options: Any, fallback: List[str] | None = None) -> List[str]:
    """Normalize an options list to a deduplicated string list."""
    if not isinstance(raw_options, list):
        return list(fallback) if fallback else []

    options: List[str] = []
    seen: set[str] = set()
    for value in raw_options:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        options.append(text)
        seen.add(text)
    return options


def _normalize_field_value(raw_value: Any) -> Optional[str]:
    """Normalize one record field value; return None when empty."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def normalize_field_options_policy_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize options-bearing fields in-memory without touching disk.

    Flow:
    - Canonicalize legacy field compatibility through ``legacy_field_policy``.
    - Normalize options/defaults for every effective field with ``options``.
    - Materialize the effective field list back into ``meta.custom_fields``.

    Legacy ``meta.cell_line_options`` / ``meta.cell_line_required`` are never
    reintroduced here; canonical persisted state lives in ``meta.custom_fields``.
    """
    if not isinstance(data, dict):
        return {
            "ok": False,
            "error_code": "invalid_data",
            "message": "YAML root must be a mapping.",
        }

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return {
            "ok": False,
            "error_code": "invalid_inventory",
            "message": "YAML inventory must be a list.",
        }

    candidate = deepcopy(data)

    raw_meta = candidate.get("meta")
    meta_changed = False
    if not isinstance(raw_meta, dict):
        raw_meta = {}
        candidate["meta"] = raw_meta
        meta_changed = True
    meta = raw_meta

    unsupported_issue = unsupported_box_fields_issue(meta)
    if unsupported_issue:
        return {
            "ok": False,
            "error_code": unsupported_issue.get("error_code", "unsupported_box_fields"),
            "message": unsupported_issue.get("message", "Unsupported dataset model."),
            "details": unsupported_issue.get("details"),
        }

    legacy_result = canonicalize_legacy_document(candidate)
    if not legacy_result.get("ok"):
        return {
            "ok": False,
            "error_code": legacy_result.get("error_code", "canonicalize_failed"),
            "message": legacy_result.get("message", "Failed to canonicalize legacy fields."),
        }
    candidate = legacy_result.get("data")
    legacy_summary = dict(legacy_result.get("summary") or {})
    candidate_inventory = candidate.get("inventory", [])
    meta = candidate.get("meta", {})

    effective = get_effective_fields(meta, inventory=candidate_inventory, phase=PHASE_WRITE)

    total_records_changed = 0
    total_changed_record_ids: List[int] = []
    total_empty_or_missing = 0
    total_stripped = 0
    total_values_added: List[str] = []

    for field_def in effective:
        field_key = field_def["key"]
        field_options = field_def.get("options")
        if not field_options:
            continue

        field_default = _normalize_field_value(field_def.get("default"))
        field_required = bool(field_def.get("required", False))

        normalized_options = _normalize_options_list(field_options)
        options_seen = set(normalized_options)

        if field_default and field_default not in options_seen:
            normalized_options.insert(0, field_default)
            options_seen.add(field_default)

        existing_values_added: List[str] = []
        for rec in candidate_inventory:
            if not isinstance(rec, dict):
                continue

            record_changed = False
            current_value = rec.get(field_key)
            normalized_value = _normalize_field_value(current_value)

            if normalized_value is None:
                if field_required and field_default:
                    total_empty_or_missing += 1
                    if rec.get(field_key) != field_default:
                        rec[field_key] = field_default
                        record_changed = True
                    normalized_value = field_default
                else:
                    continue
            else:
                if current_value != normalized_value:
                    rec[field_key] = normalized_value
                    total_stripped += 1
                    record_changed = True

            if normalized_value and normalized_value not in options_seen:
                normalized_options.append(normalized_value)
                options_seen.add(normalized_value)
                existing_values_added.append(normalized_value)

            if record_changed:
                total_records_changed += 1
                with suppress(Exception):
                    total_changed_record_ids.append(int(rec.get("id")))

        total_values_added.extend(existing_values_added)
        field_def["options"] = normalized_options
        if field_default is not None:
            field_def["default"] = field_default

    existing_cf = meta.get("custom_fields")
    materialized: List[Dict[str, Any]] = []
    for fdef in effective:
        entry: Dict[str, Any] = {
            "key": fdef["key"],
            "label": fdef.get("label", fdef["key"]),
            "type": fdef.get("type", "str"),
        }
        if fdef.get("default") is not None:
            entry["default"] = fdef["default"]
        if fdef.get("required"):
            entry["required"] = True
        if fdef.get("options"):
            entry["options"] = list(fdef.get("options") or [])
        if fdef.get("multiline"):
            entry["multiline"] = True
        materialized.append(entry)

    if materialized != existing_cf:
        meta["custom_fields"] = materialized
        meta_changed = True

    for legacy_key in ("cell_line_options", "cell_line_required"):
        if legacy_key in meta:
            meta.pop(legacy_key, None)
            meta_changed = True

    changed = bool(
        legacy_result.get("changed")
        or meta_changed
        or total_records_changed > 0
    )
    summary = {
        "records_total": len(candidate_inventory),
        "records_changed": total_records_changed,
        "changed_record_ids": sorted(set(total_changed_record_ids)),
        "alias_records_changed": int(legacy_summary.get("alias_records_changed") or 0),
        "alias_changed_record_ids": sorted(set(legacy_summary.get("alias_changed_record_ids") or [])),
        "alias_conflict_count": int(legacy_summary.get("alias_conflict_count") or 0),
        "alias_changes": list(legacy_summary.get("alias_changes") or []),
        "custom_field_alias_changes": list(legacy_summary.get("custom_field_alias_changes") or []),
        "required_flag_added": False,
        "unknown_added_to_options": DEFAULT_UNKNOWN_CELL_LINE in [v for v in total_values_added],
        "existing_values_added_to_options": total_values_added,
        "empty_or_missing_records": total_empty_or_missing,
        "stripped_value_records": total_stripped,
        "options_count": sum(
            len(field.get("options") or []) for field in effective if field.get("options")
        ),
    }
    return {
        "ok": True,
        "data": candidate,
        "changed": changed,
        "summary": summary,
    }


def migrate_cell_line_policy(
    yaml_path: str,
    *,
    dry_run: bool = False,
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    audit_source: str = "migration",
) -> Dict[str, Any]:
    """Canonicalize legacy field state and normalize options/default values."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML: {exc}",
        }

    normalized = normalize_field_options_policy_data(data)
    if not normalized.get("ok"):
        return {
            "ok": False,
            "error_code": normalized.get("error_code", "normalize_failed"),
            "message": normalized.get("message", "Failed to normalize field options policy."),
        }
    candidate = normalized.get("data")
    changed = bool(normalized.get("changed"))
    summary = dict(normalized.get("summary") or {})

    if dry_run or not changed:
        return {
            "ok": True,
            "dry_run": bool(dry_run),
            "changed": changed,
            "summary": summary,
            "backup_path": None,
        }

    try:
        backup_path = write_yaml(
            candidate,
            yaml_path,
            auto_backup=auto_backup,
            backup_path=request_backup_path,
            audit_meta={
                "source": audit_source,
                "tool_name": "migrate_cell_line_policy",
                "details": summary,
                "tool_input": {
                    "yaml_path": yaml_path,
                    "dry_run": False,
                },
            },
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "write_failed",
            "message": f"Failed to write migrated YAML: {exc}",
            "summary": summary,
        }

    return {
        "ok": True,
        "dry_run": False,
        "changed": True,
        "summary": summary,
        "backup_path": backup_path,
    }
