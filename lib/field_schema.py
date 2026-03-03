"""Schema-first field helpers for input compatibility and audit rendering."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Tuple

from .custom_fields import STRUCTURAL_FIELD_KEYS, get_effective_fields


# Alias compatibility window chosen in plan: keep for 12 weeks.
ALIAS_COMPAT_END_DATE = date(2026, 5, 27)

# Known legacy-to-canonical aliases. Rules are applied only when canonical key
# exists in effective schema and alias key does not.
FIELD_ALIAS_RULES: Dict[str, str] = {
    "parent_cell_line": "cell_line",
}

_BASE_RECORD_STRUCTURAL_KEYS = frozenset(set(STRUCTURAL_FIELD_KEYS) | {"thaw_events"})


def _is_nonempty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def effective_field_keys(meta: Dict[str, Any] | None) -> List[str]:
    """Return ordered effective field keys from metadata."""
    keys: List[str] = []
    for field_def in get_effective_fields(meta or {}):
        key = str((field_def or {}).get("key") or "").strip()
        if not key or key in keys:
            continue
        keys.append(key)
    return keys


def get_applicable_alias_map(meta: Dict[str, Any] | None) -> Dict[str, str]:
    """Return alias map applicable for current schema."""
    field_keys = set(effective_field_keys(meta))
    alias_map: Dict[str, str] = {}
    for alias_key, canonical_key in FIELD_ALIAS_RULES.items():
        if canonical_key in field_keys and alias_key not in field_keys:
            alias_map[alias_key] = canonical_key
    return alias_map


def normalize_input_fields(
    fields: Dict[str, Any] | None,
    meta: Dict[str, Any] | None,
    *,
    today: date | None = None,
) -> Dict[str, Any]:
    """Normalize input fields by applying active alias compatibility rules."""
    normalized = dict(fields or {})
    alias_map = get_applicable_alias_map(meta)
    if not alias_map:
        return {
            "ok": True,
            "fields": normalized,
            "warnings": [],
            "alias_hits": [],
        }

    current_date = today or date.today()
    alias_hits: List[Dict[str, str]] = []
    warnings: List[str] = []

    for alias_key, canonical_key in alias_map.items():
        if alias_key not in normalized:
            continue

        alias_value = normalized.pop(alias_key, None)
        canonical_present = canonical_key in normalized and _is_nonempty_value(normalized.get(canonical_key))

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

    if alias_hits and current_date > ALIAS_COMPAT_END_DATE:
        hits = ", ".join(f"{h['alias']}->{h['canonical']}" for h in alias_hits)
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


def migrate_record_aliases(record: Dict[str, Any], meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """Migrate alias keys inside one record to canonical keys."""
    if not isinstance(record, dict):
        return {"changed": False, "conflicts": 0, "alias_changes": []}

    alias_map = get_applicable_alias_map(meta)
    changed = False
    conflicts = 0
    alias_changes: List[Dict[str, Any]] = []

    for alias_key, canonical_key in alias_map.items():
        if alias_key not in record:
            continue

        alias_value = record.get(alias_key)
        canonical_value = record.get(canonical_key)
        canonical_nonempty = _is_nonempty_value(canonical_value)
        alias_nonempty = _is_nonempty_value(alias_value)

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


def split_record_fields(record: Dict[str, Any] | None, meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """Split one record into schema-ordered fields and legacy residual fields."""
    if not isinstance(record, dict):
        return {"fields": {}, "legacy_fields": {}, "field_order": []}

    field_order = effective_field_keys(meta)
    declared_keys = set(field_order)
    alias_map = get_applicable_alias_map(meta)

    fields: Dict[str, Any] = {}
    for key in field_order:
        value = record.get(key)
        if not _is_nonempty_value(value):
            for alias_key, canonical_key in alias_map.items():
                if canonical_key != key:
                    continue
                value = record.get(alias_key)
                if _is_nonempty_value(value):
                    break
        if _is_nonempty_value(value):
            fields[key] = value

    # Keep any declared key that appears in record but not in ordered list (defensive).
    for key, value in record.items():
        if key in fields:
            continue
        if key in declared_keys and _is_nonempty_value(value):
            fields[key] = value

    legacy_fields: Dict[str, Any] = {}
    for key, value in record.items():
        if key in _BASE_RECORD_STRUCTURAL_KEYS:
            continue
        if key in declared_keys:
            continue
        if key in alias_map and alias_map[key] in declared_keys and alias_map[key] in fields:
            continue
        if _is_nonempty_value(value):
            legacy_fields[str(key)] = value

    return {
        "fields": fields,
        "legacy_fields": legacy_fields,
        "field_order": field_order,
    }


def ordered_field_items(
    field_map: Dict[str, Any] | None,
    *,
    field_order: Iterable[str] | None = None,
) -> List[Tuple[str, Any]]:
    """Return field key/value pairs in schema-first order."""
    raw = dict(field_map or {})
    ordered: List[Tuple[str, Any]] = []
    seen: set[str] = set()

    for key in field_order or []:
        if key in raw:
            ordered.append((key, raw[key]))
            seen.add(key)

    for key in sorted(raw.keys()):
        if key in seen:
            continue
        ordered.append((key, raw[key]))
    return ordered
