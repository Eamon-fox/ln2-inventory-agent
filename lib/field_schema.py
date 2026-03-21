"""Schema-first field helpers for input compatibility and audit rendering."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Tuple

from .custom_fields import get_effective_fields
from .legacy_field_policy import (
    ALIAS_COMPAT_END_DATE,
    canonicalize_record_legacy_fields,
    get_active_legacy_alias_map,
    normalize_legacy_input_fields,
)
from .schema_aliases import ALL_STRUCTURAL_FIELD_KEYS


_BASE_RECORD_STRUCTURAL_KEYS = ALL_STRUCTURAL_FIELD_KEYS


def _is_nonempty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def effective_field_keys(meta: Dict[str, Any] | None, *, inventory: Any = None) -> List[str]:
    """Return ordered effective field keys from metadata."""
    keys: List[str] = []
    for field_def in get_effective_fields(meta or {}, inventory=inventory):
        key = str((field_def or {}).get("key") or "").strip()
        if not key or key in keys:
            continue
        keys.append(key)
    return keys


def get_applicable_alias_map(
    meta: Dict[str, Any] | None,
    *,
    inventory: Any = None,
) -> Dict[str, str]:
    """Return alias map applicable for current schema."""
    _ = inventory
    return get_active_legacy_alias_map(meta)


def normalize_input_fields(
    fields: Dict[str, Any] | None,
    meta: Dict[str, Any] | None,
    *,
    today: date | None = None,
) -> Dict[str, Any]:
    """Normalize input fields by applying active alias compatibility rules."""
    return normalize_legacy_input_fields(fields, meta, today=today)


def migrate_record_aliases(record: Dict[str, Any], meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """Migrate alias keys inside one record to canonical keys."""
    _ = meta
    return canonicalize_record_legacy_fields(record)


def split_record_fields(record: Dict[str, Any] | None, meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """Split one record into schema-ordered fields and legacy residual fields."""
    if not isinstance(record, dict):
        return {"fields": {}, "legacy_fields": {}, "field_order": []}

    field_order = effective_field_keys(meta, inventory=[record])
    declared_keys = set(field_order)
    alias_map = get_applicable_alias_map(meta, inventory=[record])

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


__all__ = [
    "ALIAS_COMPAT_END_DATE",
    "effective_field_keys",
    "get_applicable_alias_map",
    "normalize_input_fields",
    "migrate_record_aliases",
    "split_record_fields",
    "ordered_field_items",
]
