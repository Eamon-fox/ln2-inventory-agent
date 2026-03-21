"""Single-owner policy for legacy field compatibility and canonicalization.

This module currently centralizes the compatibility rules for the legacy
``cell_line`` field family:

- legacy meta keys: ``meta.cell_line_options`` / ``meta.cell_line_required``
- legacy record alias: ``parent_cell_line`` -> ``cell_line``
- phase-specific tolerance:
  - ``runtime`` / ``write``: tolerate explicit schema, legacy meta, or legacy
    persisted record values
  - ``schema``: expose only explicit schema or legacy meta-backed schema
  - ``staging`` / ``import``: same as runtime plus the historical
    ``custom_fields missing`` compatibility window

All other layers should consume this module instead of re-deriving one-off
compatibility checks.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple


CELL_LINE_FIELD_KEY = "cell_line"
PARENT_CELL_LINE_FIELD_KEY = "parent_cell_line"
CELL_LINE_OPTIONS_META_KEY = "cell_line_options"
CELL_LINE_REQUIRED_META_KEY = "cell_line_required"

ALIAS_COMPAT_END_DATE = date(2026, 5, 27)

DEFAULT_UNKNOWN_CELL_LINE = "Unknown"

DEFAULT_CELL_LINE_OPTIONS = [
    DEFAULT_UNKNOWN_CELL_LINE,
    "K562",
    "HeLa",
    "NCCIT",
    "HEK293T",
    "HCT116",
    "U2OS",
    "A549",
    "MCF7",
    "HepG2",
    "Huh7",
    "SW480",
    "SW620",
    "HT29",
    "DLD1",
    "RKO",
    "PC3",
    "DU145",
    "LNCaP",
    "A375",
    "SK-MEL-28",
    "Jurkat",
    "Raji",
    "THP-1",
    "MDA-MB-231",
    "mESC",
]

PHASE_RUNTIME = "runtime"
PHASE_SCHEMA = "schema"
PHASE_STAGING = "staging"
PHASE_IMPORT = "import"
PHASE_WRITE = "write"

_PHASES = {
    PHASE_RUNTIME,
    PHASE_SCHEMA,
    PHASE_STAGING,
    PHASE_IMPORT,
    PHASE_WRITE,
}

LEGACY_FIELD_ALIAS_MAP = {
    PARENT_CELL_LINE_FIELD_KEY: CELL_LINE_FIELD_KEY,
}


def _declared_raw_field_keys(meta: Dict[str, Any] | None) -> set[str]:
    meta_dict = meta if isinstance(meta, dict) else {}
    raw_fields = meta_dict.get("custom_fields")
    if not isinstance(raw_fields, list):
        return set()

    keys: set[str] = set()
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def get_active_legacy_alias_map(meta: Dict[str, Any] | None = None) -> Dict[str, str]:
    """Return legacy alias rules that remain active for the current schema."""
    declared_raw_keys = _declared_raw_field_keys(meta)
    return {
        alias_key: canonical_key
        for alias_key, canonical_key in LEGACY_FIELD_ALIAS_MAP.items()
        if alias_key not in declared_raw_keys
    }


def _is_nonempty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def normalize_legacy_field_key(key: Any) -> str:
    text = str(key or "").strip()
    return LEGACY_FIELD_ALIAS_MAP.get(text, text)


def normalize_legacy_custom_field_defs(raw_fields: Any) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """Return a shallow-copied field list with legacy field keys canonicalized."""
    if not isinstance(raw_fields, list):
        return [], []

    normalized: List[Any] = []
    alias_changes: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_fields):
        if not isinstance(item, dict):
            normalized.append(item)
            continue

        copied = dict(item)
        raw_key = str(copied.get("key") or "").strip()
        canonical_key = normalize_legacy_field_key(raw_key)
        if canonical_key != raw_key:
            copied["key"] = canonical_key
            alias_changes.append(
                {
                    "index": idx,
                    "alias": raw_key,
                    "canonical": canonical_key,
                }
            )
        normalized.append(copied)

    return normalized, alias_changes


def _normalized_text_options(raw_options: Any) -> Optional[List[str]]:
    if not isinstance(raw_options, list):
        return None
    normalized: List[str] = []
    seen: set[str] = set()
    for item in raw_options:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _legacy_meta_present(meta: Dict[str, Any]) -> bool:
    return (
        isinstance(meta, dict)
        and (
            CELL_LINE_OPTIONS_META_KEY in meta
            or CELL_LINE_REQUIRED_META_KEY in meta
        )
    )


def _legacy_inventory_present(inventory: Any) -> bool:
    if not isinstance(inventory, list):
        return False
    for record in inventory:
        if not isinstance(record, dict):
            continue
        for key in (CELL_LINE_FIELD_KEY, PARENT_CELL_LINE_FIELD_KEY):
            if _is_nonempty_value(record.get(key)):
                return True
    return False


def _canonical_declared_fields(declared_fields: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(declared_fields, list):
        return normalized

    seen: dict[str, int] = {}
    for item in declared_fields:
        if not isinstance(item, dict):
            continue
        copied = deepcopy(item)
        raw_key = str(copied.get("key") or "").strip()
        canonical_key = normalize_legacy_field_key(raw_key)
        if not canonical_key:
            continue
        copied["key"] = canonical_key
        existing_idx = seen.get(canonical_key)
        if existing_idx is None:
            seen[canonical_key] = len(normalized)
            normalized.append(copied)
            continue
        if raw_key == canonical_key:
            normalized[existing_idx] = copied
    return normalized


def _declared_cell_line_field(declared_fields: Any) -> Optional[Dict[str, Any]]:
    for item in _canonical_declared_fields(declared_fields):
        if str(item.get("key") or "").strip() == CELL_LINE_FIELD_KEY:
            return item
    return None


def _build_meta_backed_cell_line_field(meta: Dict[str, Any]) -> Dict[str, Any]:
    field: Dict[str, Any] = {
        "key": CELL_LINE_FIELD_KEY,
        "label": "Cell Line",
        "type": "str",
    }
    options = _normalized_text_options((meta or {}).get(CELL_LINE_OPTIONS_META_KEY))
    if options is None:
        options = list(DEFAULT_CELL_LINE_OPTIONS)
    if options:
        field["options"] = options
    required = bool((meta or {}).get(CELL_LINE_REQUIRED_META_KEY)) if CELL_LINE_REQUIRED_META_KEY in (meta or {}) else False
    if required:
        field["required"] = True
        field["default"] = DEFAULT_UNKNOWN_CELL_LINE
    return field


def _build_record_backed_cell_line_field() -> Dict[str, Any]:
    return {
        "key": CELL_LINE_FIELD_KEY,
        "label": "Cell Line",
        "type": "str",
    }


def resolve_legacy_field_policy(
    meta: Dict[str, Any] | None,
    inventory: Any = None,
    *,
    declared_fields: Any = None,
    phase: str = PHASE_RUNTIME,
) -> Dict[str, Any]:
    """Resolve phase-specific compatibility behavior for legacy field families."""
    phase_text = str(phase or PHASE_RUNTIME).strip().lower()
    if phase_text not in _PHASES:
        phase_text = PHASE_RUNTIME

    meta_dict = meta if isinstance(meta, dict) else {}
    declared = _canonical_declared_fields(declared_fields)
    declared_keys = {
        str(item.get("key") or "").strip()
        for item in declared
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }

    explicit_cell_line = _declared_cell_line_field(declared)
    has_legacy_meta = _legacy_meta_present(meta_dict)
    has_legacy_inventory = _legacy_inventory_present(inventory)
    custom_fields_missing = "custom_fields" not in meta_dict

    runtime_cell_line = bool(explicit_cell_line or has_legacy_meta or has_legacy_inventory)
    staging_cell_line = bool(runtime_cell_line)
    schema_cell_line = bool(explicit_cell_line or has_legacy_meta)
    write_cell_line = bool(explicit_cell_line or has_legacy_meta or has_legacy_inventory)

    synthetic_reason = None
    if explicit_cell_line is None:
        if phase_text in {PHASE_SCHEMA}:
            if has_legacy_meta:
                synthetic_reason = "legacy_meta"
        elif phase_text in {PHASE_STAGING, PHASE_IMPORT}:
            if has_legacy_meta:
                synthetic_reason = "legacy_meta"
            elif has_legacy_inventory:
                synthetic_reason = "legacy_inventory"
        elif phase_text in {PHASE_RUNTIME, PHASE_WRITE}:
            if has_legacy_meta:
                synthetic_reason = "legacy_meta"
            elif has_legacy_inventory:
                synthetic_reason = "legacy_inventory"

    effective_fields = list(declared)
    if explicit_cell_line is None and synthetic_reason:
        if synthetic_reason == "legacy_meta":
            effective_fields.insert(0, _build_meta_backed_cell_line_field(meta_dict))
        elif synthetic_reason == "legacy_inventory":
            effective_fields.insert(0, _build_record_backed_cell_line_field())

    effective_keys = [
        str(item.get("key") or "").strip()
        for item in effective_fields
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]
    visible_keys = set(effective_keys)

    staging_input_keys = set(visible_keys)
    if staging_cell_line:
        staging_input_keys.add(CELL_LINE_FIELD_KEY)
        staging_input_keys.add(PARENT_CELL_LINE_FIELD_KEY)

    hidden_staging_input_keys = {
        key for key in (CELL_LINE_FIELD_KEY, PARENT_CELL_LINE_FIELD_KEY)
        if key in staging_input_keys and key not in visible_keys
    }

    return {
        "phase": phase_text,
        "declared_fields": declared,
        "declared_keys": declared_keys,
        "effective_fields": effective_fields,
        "effective_keys": effective_keys,
        "explicit_cell_line": explicit_cell_line,
        "runtime_cell_line": runtime_cell_line,
        "schema_cell_line": schema_cell_line,
        "staging_cell_line": staging_cell_line,
        "write_cell_line": write_cell_line,
        "has_legacy_meta": has_legacy_meta,
        "has_legacy_inventory": has_legacy_inventory,
        "custom_fields_missing": custom_fields_missing,
        "synthetic_reason": synthetic_reason,
        "staging_input_keys": staging_input_keys,
        "hidden_staging_input_keys": hidden_staging_input_keys,
        "alias_map": dict(LEGACY_FIELD_ALIAS_MAP),
    }


def normalize_legacy_input_fields(
    fields: Dict[str, Any] | None,
    meta: Dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> Dict[str, Any]:
    """Normalize legacy user-input aliases into canonical field names."""
    normalized = dict(fields or {})
    alias_hits: List[Dict[str, str]] = []
    warnings: List[str] = []
    alias_map = get_active_legacy_alias_map(meta)

    for alias_key, canonical_key in alias_map.items():
        if alias_key not in normalized:
            continue

        alias_value = normalized.pop(alias_key, None)
        canonical_present = (
            canonical_key in normalized
            and _is_nonempty_value(normalized.get(canonical_key))
        )
        if not canonical_present:
            normalized[canonical_key] = alias_value
            behavior = "mapped"
        else:
            behavior = "ignored"

        alias_hits.append(
            {
                "alias": alias_key,
                "canonical": canonical_key,
                "behavior": behavior,
            }
        )
        warnings.append(
            "deprecated_field_alias: "
            f"{alias_key} -> {canonical_key}; support ends {ALIAS_COMPAT_END_DATE.isoformat()}"
        )

    current_date = today or date.today()
    if alias_hits and current_date > ALIAS_COMPAT_END_DATE:
        hits = ", ".join(f"{hit['alias']}->{hit['canonical']}" for hit in alias_hits)
        return {
            "ok": False,
            "error_code": "deprecated_field_alias_removed",
            "message": (
                "Deprecated field aliases are no longer accepted: "
                f"{hits}. Support ended on {ALIAS_COMPAT_END_DATE.isoformat()}."
            ),
            "fields": normalized,
            "warnings": warnings,
            "alias_hits": alias_hits,
        }

    return {
        "ok": True,
        "fields": normalized,
        "warnings": warnings,
        "alias_hits": alias_hits,
    }


def canonicalize_record_legacy_fields(record: Dict[str, Any] | None) -> Dict[str, Any]:
    """Canonicalize legacy record aliases in-place for persisted documents."""
    if not isinstance(record, dict):
        return {"changed": False, "conflicts": 0, "alias_changes": []}

    changed = False
    conflicts = 0
    alias_changes: List[Dict[str, Any]] = []

    for alias_key, canonical_key in LEGACY_FIELD_ALIAS_MAP.items():
        if alias_key not in record:
            continue

        alias_value = record.get(alias_key)
        canonical_value = record.get(canonical_key)
        alias_nonempty = _is_nonempty_value(alias_value)
        canonical_nonempty = _is_nonempty_value(canonical_value)

        action = "dropped_empty_alias"
        if alias_nonempty and not canonical_nonempty:
            record[canonical_key] = alias_value
            changed = True
            action = "mapped"
        elif alias_nonempty and canonical_nonempty and canonical_value != alias_value:
            conflicts += 1
            action = "dropped_conflict"

        if alias_key in record:
            record.pop(alias_key, None)
            changed = True

        alias_changes.append(
            {
                "alias": alias_key,
                "canonical": canonical_key,
                "action": action,
            }
        )

    return {
        "changed": changed,
        "conflicts": conflicts,
        "alias_changes": alias_changes,
    }


def _canonicalize_meta_custom_fields(meta: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw_fields = meta.get("custom_fields")
    if not isinstance(raw_fields, list):
        return False, [], []

    normalized_fields, alias_changes = normalize_legacy_custom_field_defs(raw_fields)
    canonical_fields: List[Dict[str, Any]] = []
    seen: dict[str, int] = {}
    changed = bool(alias_changes)

    for item in normalized_fields:
        if not isinstance(item, dict):
            canonical_fields.append(item)
            changed = True
            continue

        copied = dict(item)
        key = str(copied.get("key") or "").strip()
        existing_idx = seen.get(key)
        if existing_idx is None:
            seen[key] = len(canonical_fields)
            canonical_fields.append(copied)
            continue

        previous = canonical_fields[existing_idx]
        previous_raw = str(previous.get("key") or "").strip() if isinstance(previous, dict) else ""
        raw_key = str(item.get("key") or "").strip()
        if raw_key == key and previous_raw != key:
            canonical_fields[existing_idx] = copied
        changed = True

    if canonical_fields != raw_fields:
        meta["custom_fields"] = canonical_fields
        changed = True

    return changed, canonical_fields, alias_changes


def canonicalize_legacy_document(data: Dict[str, Any] | None) -> Dict[str, Any]:
    """Canonicalize one full document to the write-time schema."""
    if not isinstance(data, dict):
        return {
            "ok": False,
            "error_code": "invalid_data",
            "message": "YAML root must be a mapping.",
        }

    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        inventory = []
        data["inventory"] = inventory

    changed = False
    meta_changed, canonical_fields, field_alias_changes = _canonicalize_meta_custom_fields(meta)
    changed = changed or meta_changed

    alias_records_changed = 0
    alias_conflict_count = 0
    alias_changes: List[Dict[str, Any]] = []
    alias_changed_record_ids: List[int] = []
    for record in inventory:
        if not isinstance(record, dict):
            continue
        migrated = canonicalize_record_legacy_fields(record)
        if not migrated.get("changed"):
            continue
        changed = True
        alias_records_changed += 1
        alias_conflict_count += int(migrated.get("conflicts") or 0)
        alias_changes.extend(list(migrated.get("alias_changes") or []))
        try:
            alias_changed_record_ids.append(int(record.get("id")))
        except Exception:
            pass

    resolved = resolve_legacy_field_policy(
        meta,
        inventory,
        declared_fields=canonical_fields if canonical_fields else meta.get("custom_fields"),
        phase=PHASE_WRITE,
    )
    explicit_cell_line = resolved.get("explicit_cell_line")
    if explicit_cell_line is None and resolved.get("write_cell_line"):
        custom_fields = meta.get("custom_fields")
        normalized_custom_fields, _alias_changes = normalize_legacy_custom_field_defs(custom_fields)
        if not isinstance(normalized_custom_fields, list):
            normalized_custom_fields = []
        synthetic_reason = str(resolved.get("synthetic_reason") or "").strip()
        if synthetic_reason == "legacy_meta":
            cell_line_field = _build_meta_backed_cell_line_field(meta)
        else:
            cell_line_field = _build_record_backed_cell_line_field()
        meta["custom_fields"] = [cell_line_field] + [
            item for item in normalized_custom_fields
            if not (
                isinstance(item, dict)
                and normalize_legacy_field_key(item.get("key")) == CELL_LINE_FIELD_KEY
            )
        ]
        changed = True

    for legacy_key in (CELL_LINE_OPTIONS_META_KEY, CELL_LINE_REQUIRED_META_KEY):
        if legacy_key in meta:
            meta.pop(legacy_key, None)
            changed = True

    return {
        "ok": True,
        "data": data,
        "changed": changed,
        "summary": {
            "custom_field_alias_changes": field_alias_changes,
            "alias_records_changed": alias_records_changed,
            "alias_changed_record_ids": sorted(set(alias_changed_record_ids)),
            "alias_conflict_count": alias_conflict_count,
            "alias_changes": alias_changes,
        },
    }
__all__ = [
    "ALIAS_COMPAT_END_DATE",
    "CELL_LINE_FIELD_KEY",
    "CELL_LINE_OPTIONS_META_KEY",
    "CELL_LINE_REQUIRED_META_KEY",
    "DEFAULT_CELL_LINE_OPTIONS",
    "DEFAULT_UNKNOWN_CELL_LINE",
    "LEGACY_FIELD_ALIAS_MAP",
    "PARENT_CELL_LINE_FIELD_KEY",
    "PHASE_IMPORT",
    "PHASE_RUNTIME",
    "PHASE_SCHEMA",
    "PHASE_STAGING",
    "PHASE_WRITE",
    "canonicalize_legacy_document",
    "canonicalize_record_legacy_fields",
    "get_active_legacy_alias_map",
    "normalize_legacy_custom_field_defs",
    "normalize_legacy_field_key",
    "normalize_legacy_input_fields",
    "resolve_legacy_field_policy",
]
