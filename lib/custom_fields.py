"""Parse and validate custom field definitions from YAML meta."""

import sys

CORE_FIELD_KEYS = frozenset({
    "id", "parent_cell_line", "short_name", "box", "positions",
    "frozen_at", "plasmid_name", "plasmid_id", "note", "thaw_events",
})

_VALID_TYPES = {"str", "int", "float", "date"}


def parse_custom_fields(meta):
    """Parse ``meta.custom_fields`` and return a validated list.

    Each item is normalised to ``{"key", "label", "type", "default"}``.
    Invalid or conflicting entries are silently dropped with a stderr warning.
    """
    raw = (meta or {}).get("custom_fields")
    if not raw:
        return []

    if not isinstance(raw, list):
        print(f"warning: meta.custom_fields must be a list, got {type(raw).__name__}", file=sys.stderr)
        return []

    result = []
    seen_keys = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            print(f"warning: meta.custom_fields[{idx}] is not a dict, skipping", file=sys.stderr)
            continue

        key = str(item.get("key") or "").strip()
        if not key or not key.isidentifier():
            print(f"warning: meta.custom_fields[{idx}] has invalid key={key!r}, skipping", file=sys.stderr)
            continue

        if key in CORE_FIELD_KEYS:
            print(f"warning: meta.custom_fields[{idx}] key={key!r} conflicts with core field, skipping", file=sys.stderr)
            continue

        if key in seen_keys:
            print(f"warning: meta.custom_fields[{idx}] duplicate key={key!r}, skipping", file=sys.stderr)
            continue

        label = str(item.get("label") or key)
        field_type = str(item.get("type") or "str").strip().lower()
        if field_type not in _VALID_TYPES:
            print(f"warning: meta.custom_fields[{idx}] unknown type={field_type!r}, defaulting to str", file=sys.stderr)
            field_type = "str"

        default = item.get("default")

        seen_keys.add(key)
        result.append({
            "key": key,
            "label": label,
            "type": field_type,
            "default": default,
        })

    return result


def coerce_value(value, field_type):
    """Coerce a user-input value to the declared type.

    Returns the coerced value, or *None* if the input is empty/blank.
    Raises ``ValueError`` on type mismatch.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    if field_type == "int":
        return int(s)
    if field_type == "float":
        return float(s)
    if field_type == "date":
        # Basic YYYY-MM-DD validation
        from lib.validators import validate_date
        if not validate_date(s):
            raise ValueError(f"invalid date: {s}")
        return s
    return s
