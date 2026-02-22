"""Migration helpers to normalize cell_line defaults and legacy values."""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .custom_fields import DEFAULT_CELL_LINE_OPTIONS, DEFAULT_UNKNOWN_CELL_LINE
from .yaml_ops import load_yaml, write_yaml


def _normalize_meta_options(raw_options: Any) -> List[str]:
    """Normalize ``meta.cell_line_options`` to a deduplicated string list."""
    if not isinstance(raw_options, list):
        return list(DEFAULT_CELL_LINE_OPTIONS)

    options: List[str] = []
    seen = set()
    for value in raw_options:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        options.append(text)
        seen.add(text)
    return options


def _normalize_cell_line_value(raw_value: Any) -> Optional[str]:
    """Normalize one record ``cell_line`` value; return None when empty."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def migrate_cell_line_policy(
    yaml_path: str,
    *,
    dry_run: bool = False,
    auto_backup: bool = True,
    audit_source: str = "migration",
) -> Dict[str, Any]:
    """Normalize ``cell_line`` policy defaults and legacy record values.

    Migration behavior:
    - missing ``meta.cell_line_required`` -> ``True``
    - normalize ``meta.cell_line_options`` to a list and ensure ``"Unknown"``
    - missing/blank record ``cell_line`` -> ``"Unknown"``
    - legacy non-empty record values not in options -> append to options
    """
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"Failed to load YAML: {exc}",
        }

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return {
            "ok": False,
            "error_code": "invalid_inventory",
            "message": "YAML inventory must be a list.",
        }

    candidate = deepcopy(data)
    candidate_inventory = candidate.get("inventory", [])

    raw_meta = candidate.get("meta")
    meta_changed = False
    if not isinstance(raw_meta, dict):
        raw_meta = {}
        candidate["meta"] = raw_meta
        meta_changed = True
    meta = raw_meta

    required_flag_added = False
    if "cell_line_required" not in meta:
        meta["cell_line_required"] = True
        required_flag_added = True
        meta_changed = True

    normalized_options = _normalize_meta_options(meta.get("cell_line_options"))
    options_seen = set(normalized_options)
    unknown_added_to_options = False
    if DEFAULT_UNKNOWN_CELL_LINE not in options_seen:
        normalized_options.insert(0, DEFAULT_UNKNOWN_CELL_LINE)
        options_seen.add(DEFAULT_UNKNOWN_CELL_LINE)
        unknown_added_to_options = True

    existing_values_added: List[str] = []
    records_changed = 0
    changed_record_ids: List[int] = []
    empty_or_missing_records = 0
    stripped_value_records = 0

    for rec in candidate_inventory:
        if not isinstance(rec, dict):
            continue

        record_changed = False
        current_value = rec.get("cell_line")
        normalized_value = _normalize_cell_line_value(current_value)

        if normalized_value is None:
            empty_or_missing_records += 1
            normalized_value = DEFAULT_UNKNOWN_CELL_LINE
            if rec.get("cell_line") != DEFAULT_UNKNOWN_CELL_LINE:
                rec["cell_line"] = DEFAULT_UNKNOWN_CELL_LINE
                record_changed = True
        else:
            if current_value != normalized_value:
                rec["cell_line"] = normalized_value
                stripped_value_records += 1
                record_changed = True

        if normalized_value not in options_seen:
            normalized_options.append(normalized_value)
            options_seen.add(normalized_value)
            existing_values_added.append(normalized_value)

        if record_changed:
            records_changed += 1
            with suppress(Exception):
                changed_record_ids.append(int(rec.get("id")))

    if meta.get("cell_line_options") != normalized_options:
        meta["cell_line_options"] = normalized_options
        meta_changed = True

    if unknown_added_to_options or existing_values_added:
        meta_changed = True

    changed = bool(meta_changed or records_changed > 0)
    summary = {
        "records_total": len(candidate_inventory),
        "records_changed": records_changed,
        "changed_record_ids": sorted(set(changed_record_ids)),
        "required_flag_added": required_flag_added,
        "unknown_added_to_options": unknown_added_to_options,
        "existing_values_added_to_options": existing_values_added,
        "empty_or_missing_records": empty_or_missing_records,
        "stripped_value_records": stripped_value_records,
        "options_count": len(normalized_options),
    }

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
            audit_meta={
                "action": "migrate_cell_line_policy",
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
