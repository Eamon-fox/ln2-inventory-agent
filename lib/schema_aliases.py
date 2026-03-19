"""Helpers for bridging legacy and canonical structural record field names.

Canonical persisted names:
- ``stored_at`` replaces legacy ``frozen_at``
- ``storage_events`` replaces legacy ``thaw_events``

Runtime code may still encounter either shape during the bridge period.
These helpers let read paths accept both while write paths persist only the
canonical names.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple


CANONICAL_STORED_AT_KEY = "stored_at"
LEGACY_STORED_AT_KEY = "frozen_at"
CANONICAL_STORAGE_EVENTS_KEY = "storage_events"
LEGACY_STORAGE_EVENTS_KEY = "thaw_events"
DEFAULT_RECORD_SORT_FIELD = CANONICAL_STORED_AT_KEY
VALID_RECORD_SORT_FIELDS = frozenset({"box", "position", DEFAULT_RECORD_SORT_FIELD, "id"})

CANONICAL_STRUCTURAL_FIELD_KEYS = frozenset(
    {
        "id",
        "box",
        "position",
        CANONICAL_STORED_AT_KEY,
        CANONICAL_STORAGE_EVENTS_KEY,
    }
)

LEGACY_STRUCTURAL_FIELD_KEYS = frozenset(
    {
        LEGACY_STORED_AT_KEY,
        LEGACY_STORAGE_EVENTS_KEY,
    }
)

ALL_STRUCTURAL_FIELD_KEYS = frozenset(
    set(CANONICAL_STRUCTURAL_FIELD_KEYS) | set(LEGACY_STRUCTURAL_FIELD_KEYS)
)

STRUCTURAL_ALIAS_MAP = {
    CANONICAL_STORED_AT_KEY: LEGACY_STORED_AT_KEY,
    CANONICAL_STORAGE_EVENTS_KEY: LEGACY_STORAGE_EVENTS_KEY,
}

LEGACY_TO_CANONICAL_MAP = {
    legacy_key: canonical_key
    for canonical_key, legacy_key in STRUCTURAL_ALIAS_MAP.items()
}


def _is_present(value: Any) -> bool:
    return value not in (None, "")


def coalesce_structural_alias_value(*, canonical_value=None, legacy_value=None):
    """Return canonical value when present, otherwise the legacy value."""
    if _is_present(canonical_value):
        return canonical_value
    return legacy_value


def coalesce_stored_at_value(stored_at=None, frozen_at=None):
    """Return the effective stored-at value from canonical/legacy inputs."""
    return coalesce_structural_alias_value(
        canonical_value=stored_at,
        legacy_value=frozen_at,
    )


def get_input_stored_at(value: Dict[str, Any] | None, default=None):
    """Read stored_at/frozen_at from one mapping-shaped payload."""
    if not isinstance(value, dict):
        return default
    resolved = coalesce_stored_at_value(
        stored_at=value.get(CANONICAL_STORED_AT_KEY),
        frozen_at=value.get(LEGACY_STORED_AT_KEY),
    )
    if resolved in (None, ""):
        return default
    return resolved


def get_alias_value(record: Dict[str, Any] | None, canonical_key: str, default=None):
    """Return canonical or legacy alias value for one structural key."""
    if not isinstance(record, dict):
        return default
    legacy_key = STRUCTURAL_ALIAS_MAP.get(canonical_key)
    value = coalesce_structural_alias_value(
        canonical_value=record.get(canonical_key),
        legacy_value=record.get(legacy_key) if legacy_key else None,
    )
    if value in (None, ""):
        return default
    return value


def get_stored_at(record: Dict[str, Any] | None, default=None):
    return get_alias_value(record, CANONICAL_STORED_AT_KEY, default=default)


def get_storage_events(record: Dict[str, Any] | None):
    return get_alias_value(record, CANONICAL_STORAGE_EVENTS_KEY, default=None)


def structural_field_label(canonical_key: str) -> str:
    """Return a human-readable canonical/legacy field label."""
    key = str(canonical_key or "").strip()
    legacy_key = STRUCTURAL_ALIAS_MAP.get(key)
    if legacy_key:
        return f"{key}/{legacy_key}"
    return key


def normalize_record_sort_field(sort_by, *, default=DEFAULT_RECORD_SORT_FIELD):
    """Normalize one record-sort field name to the canonical internal form."""
    if sort_by in (None, ""):
        return default
    text = str(sort_by).strip().lower()
    if not text:
        return default
    if text == LEGACY_STORED_AT_KEY:
        return CANONICAL_STORED_AT_KEY
    return text


def present_record_sort_field(sort_by, *, requested=None, default_legacy=False):
    """Return a user-facing sort field label for canonical internal state."""
    normalized = normalize_record_sort_field(sort_by)
    if normalized != CANONICAL_STORED_AT_KEY:
        return normalized

    requested_text = str(requested or "").strip().lower()
    if requested_text == CANONICAL_STORED_AT_KEY:
        return CANONICAL_STORED_AT_KEY
    if requested_text == LEGACY_STORED_AT_KEY:
        return LEGACY_STORED_AT_KEY
    if default_legacy:
        return LEGACY_STORED_AT_KEY
    return CANONICAL_STORED_AT_KEY


def normalize_structural_alias_input_map(
    field_map: Dict[str, Any] | None,
    *,
    scope: str = "fields",
) -> Tuple[Dict[str, Any], List[str]]:
    """Normalize canonical/legacy structural aliases inside one input mapping."""
    normalized = dict(field_map or {})
    errors: List[str] = []

    for canonical_key, legacy_key in STRUCTURAL_ALIAS_MAP.items():
        canonical_has_key = canonical_key in normalized
        legacy_has_key = legacy_key in normalized
        canonical_value = normalized.get(canonical_key)
        legacy_value = normalized.get(legacy_key)
        canonical_present = _is_present(canonical_value)
        legacy_present = _is_present(legacy_value)

        if canonical_present and legacy_present:
            if canonical_value != legacy_value:
                errors.append(f"{scope}.{canonical_key} conflicts with {scope}.{legacy_key}")
        elif legacy_has_key and (not canonical_has_key or not canonical_present):
            normalized[canonical_key] = deepcopy(legacy_value)

        normalized.pop(legacy_key, None)

    return normalized, errors


def expand_record_structural_aliases(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Populate missing structural aliases in-place for runtime compatibility."""
    if not isinstance(record, dict):
        return record

    for canonical_key, legacy_key in STRUCTURAL_ALIAS_MAP.items():
        if canonical_key in record and legacy_key not in record:
            record[legacy_key] = deepcopy(record.get(canonical_key))
        elif legacy_key in record and canonical_key not in record:
            record[canonical_key] = deepcopy(record.get(legacy_key))
    return record


def expand_structural_aliases_in_sections(
    container: Dict[str, Any] | None,
    *,
    section_keys: Iterable[str] = ("before", "after"),
) -> Dict[str, Any] | None:
    """Expand structural aliases inside named child mappings of one container."""
    if not isinstance(container, dict):
        return container

    for key in section_keys:
        section = container.get(str(key))
        if isinstance(section, dict):
            expand_record_structural_aliases(section)
    return container


def _conflict_message(canonical_key: str, legacy_key: str, *, label: str) -> str:
    return (
        f"{label}: conflicting structural aliases '{canonical_key}' and "
        f"legacy '{legacy_key}'"
    )


def canonicalize_record_structural_aliases(
    record: Dict[str, Any] | None,
    *,
    label: str = "Record",
) -> Tuple[Dict[str, Any] | None, List[str]]:
    """Return a copy using only canonical structural keys plus conflict errors."""
    if not isinstance(record, dict):
        return record, []

    normalized = deepcopy(record)
    errors: List[str] = []

    for canonical_key, legacy_key in STRUCTURAL_ALIAS_MAP.items():
        canonical_has_key = canonical_key in normalized
        legacy_has_key = legacy_key in normalized
        canonical_value = normalized.get(canonical_key)
        legacy_value = normalized.get(legacy_key)
        canonical_present = _is_present(canonical_value)
        legacy_present = _is_present(legacy_value)

        if canonical_present and legacy_present:
            if canonical_value != legacy_value:
                errors.append(_conflict_message(canonical_key, legacy_key, label=label))
        elif legacy_has_key and (not canonical_has_key or not canonical_present):
            normalized[canonical_key] = deepcopy(legacy_value)

        normalized.pop(legacy_key, None)

    return normalized, errors


def expand_document_structural_aliases(data: Any) -> Any:
    """Populate missing structural aliases across one inventory document."""
    if not isinstance(data, dict):
        return data

    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        return data

    for record in inventory:
        expand_record_structural_aliases(record)
    return data


def canonicalize_inventory_document(data: Any) -> Tuple[Any, List[str]]:
    """Return canonicalized document copy plus structural alias conflict errors."""
    if not isinstance(data, dict):
        return data, []

    normalized = deepcopy(data)
    inventory = normalized.get("inventory")
    if not isinstance(inventory, list):
        return normalized, []

    errors: List[str] = []
    for idx, record in enumerate(inventory):
        label = (
            f"Record #{idx + 1} (id={record.get('id', 'N/A')})"
            if isinstance(record, dict)
            else f"Record #{idx + 1}"
        )
        canonical_record, rec_errors = canonicalize_record_structural_aliases(
            record,
            label=label,
        )
        inventory[idx] = canonical_record
        errors.extend(rec_errors)

    return normalized, errors
