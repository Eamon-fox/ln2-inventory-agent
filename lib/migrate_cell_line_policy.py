"""Migration helpers to normalize field-options defaults and legacy values.

Originally cell_line-specific; now generalized to handle any field that
carries ``options`` and a ``default`` value in its custom-field definition.
"""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .custom_fields import (
    DEFAULT_CELL_LINE_OPTIONS,
    DEFAULT_UNKNOWN_CELL_LINE,
    get_effective_fields,
)
from .field_schema import migrate_record_aliases
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
    """Normalize all options-bearing fields in-memory, without touching disk.

    For every effective field that has ``options`` defined:
    - Normalize the options list (dedup, strip whitespace).
    - Ensure the field's ``default`` value is in the options list.
    - Fill missing/empty record values with ``default`` when ``required``.
    - Append unknown record values to the options list.
    - Materialize the updated options back into ``meta.custom_fields``.

    Also keeps legacy ``meta.cell_line_options`` / ``meta.cell_line_required``
    in sync for backward compatibility.
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
    candidate_inventory = candidate.get("inventory", [])

    raw_meta = candidate.get("meta")
    meta_changed = False
    if not isinstance(raw_meta, dict):
        raw_meta = {}
        candidate["meta"] = raw_meta
        meta_changed = True
    meta = raw_meta

    # --- Legacy cell_line compat: ensure required flag exists ---
    required_flag_added = False
    if "cell_line_required" not in meta:
        meta["cell_line_required"] = True
        required_flag_added = True
        meta_changed = True

    # Get effective fields (auto-injects cell_line/note from legacy meta)
    effective = get_effective_fields(meta)

    # Migrate legacy alias keys (for example: parent_cell_line -> cell_line)
    # before options/default normalization so the rest of the pipeline works
    # on canonical field names.
    alias_records_changed = 0
    alias_conflict_count = 0
    alias_changes: List[Dict[str, Any]] = []
    alias_changed_record_ids: List[int] = []
    for rec in candidate_inventory:
        if not isinstance(rec, dict):
            continue
        migrated = migrate_record_aliases(rec, meta)
        if not migrated.get("changed"):
            continue
        alias_records_changed += 1
        alias_conflict_count += int(migrated.get("conflicts") or 0)
        alias_changes.extend(list(migrated.get("alias_changes") or []))
        with suppress(Exception):
            alias_changed_record_ids.append(int(rec.get("id")))

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

        field_default = field_def.get("default")
        field_required = field_def.get("required", False)

        # For cell_line, use legacy meta.cell_line_options as canonical source
        if field_key == "cell_line":
            normalized_options = _normalize_options_list(
                meta.get("cell_line_options"),
                fallback=DEFAULT_CELL_LINE_OPTIONS,
            )
        else:
            normalized_options = _normalize_options_list(field_options)

        options_seen = set(normalized_options)

        # Ensure default value is in options
        if field_default and field_default not in options_seen:
            normalized_options.insert(0, str(field_default))
            options_seen.add(str(field_default))

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
                    default_str = str(field_default)
                    if rec.get(field_key) != default_str:
                        rec[field_key] = default_str
                        record_changed = True
                    normalized_value = default_str
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

        # Write back normalized options: keep legacy cell_line_options in sync
        if field_key == "cell_line":
            if meta.get("cell_line_options") != normalized_options:
                meta["cell_line_options"] = normalized_options
                meta_changed = True
        # Update field options in custom_fields definition
        field_def["options"] = normalized_options

    # Materialize effective field definitions into meta.custom_fields
    # so old YAML files self-upgrade on first write.
    existing_cf = meta.get("custom_fields")
    materialized = []
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
            entry["options"] = fdef["options"]
        if fdef.get("multiline"):
            entry["multiline"] = True
        materialized.append(entry)

    if materialized != existing_cf:
        meta["custom_fields"] = materialized
        meta_changed = True

    changed = bool(meta_changed or total_records_changed > 0)
    if alias_records_changed > 0:
        changed = True
    summary = {
        "records_total": len(candidate_inventory),
        "records_changed": total_records_changed,
        "changed_record_ids": sorted(set(total_changed_record_ids)),
        "alias_records_changed": alias_records_changed,
        "alias_changed_record_ids": sorted(set(alias_changed_record_ids)),
        "alias_conflict_count": alias_conflict_count,
        "alias_changes": alias_changes,
        "required_flag_added": required_flag_added,
        "unknown_added_to_options": DEFAULT_UNKNOWN_CELL_LINE in [v for v in total_values_added],
        "existing_values_added_to_options": total_values_added,
        "empty_or_missing_records": total_empty_or_missing,
        "stripped_value_records": total_stripped,
        "options_count": sum(
            len(f.get("options") or []) for f in effective if f.get("options")
        ),
    }
    return {
        "ok": True,
        "data": candidate,
        "changed": changed,
        "summary": summary,
    }


# Backward-compatible alias
normalize_cell_line_policy_data = normalize_field_options_policy_data


def migrate_cell_line_policy(
    yaml_path: str,
    *,
    dry_run: bool = False,
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    audit_source: str = "migration",
) -> Dict[str, Any]:
    """Normalize field-options defaults and legacy record values.

    Migration behavior:
    - missing ``meta.cell_line_required`` -> ``True``
    - normalize ``meta.cell_line_options`` to a list and ensure ``"Unknown"``
    - missing/blank record ``cell_line`` -> ``"Unknown"``
    - legacy non-empty record values not in options -> append to options
    - materialize effective fields into ``meta.custom_fields``
    """
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
