"""Parse and validate custom field definitions from YAML meta."""

import sys

STRUCTURAL_FIELD_KEYS = frozenset({
    "id", "box", "positions", "frozen_at", "thaw_events", "cell_line",
})

_VALID_TYPES = {"str", "int", "float", "date"}

DEFAULT_PRESET_FIELDS = [
    {"key": "short_name", "label": "Short Name", "type": "str", "required": True},
]

DEFAULT_CELL_LINE_OPTIONS = ["K562", "HeLa", "NCCIT", "HEK293T"]


def parse_custom_fields(meta):
    """Parse ``meta.custom_fields`` and return a validated list.

    Each item is normalised to ``{"key", "label", "type", "default", "required"}``.
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

        if key in STRUCTURAL_FIELD_KEYS:
            print(f"warning: meta.custom_fields[{idx}] key={key!r} conflicts with structural field, skipping", file=sys.stderr)
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
        required = bool(item.get("required", False))

        seen_keys.add(key)
        result.append({
            "key": key,
            "label": label,
            "type": field_type,
            "default": default,
            "required": required,
        })

    return result


def get_effective_fields(meta):
    """Return the list of user-configurable field definitions from meta.

    Returns parsed custom_fields, or DEFAULT_PRESET_FIELDS if none defined.
    """
    fields = parse_custom_fields(meta)
    if fields:
        return fields
    return list(DEFAULT_PRESET_FIELDS)


def get_display_key(meta):
    """Return the field key used for grid cell labels.

    Uses ``meta.display_key`` if set, otherwise the first effective field's key.
    """
    dk = (meta or {}).get("display_key")
    if dk and isinstance(dk, str):
        return dk
    fields = get_effective_fields(meta)
    return fields[0]["key"] if fields else "id"


def get_color_key(meta):
    """Return the field key used for grid cell coloring and filter grouping.

    Uses ``meta.color_key`` if set, otherwise ``"cell_line"``.
    """
    ck = (meta or {}).get("color_key")
    if ck and isinstance(ck, str):
        return ck
    return "cell_line"


def get_cell_line_options(meta):
    """Return the list of predefined cell_line values from meta."""
    opts = (meta or {}).get("cell_line_options")
    if isinstance(opts, list):
        return [str(o) for o in opts if o]
    return list(DEFAULT_CELL_LINE_OPTIONS)


def get_required_field_keys(meta):
    """Return the set of user-field keys marked as required."""
    fields = get_effective_fields(meta)
    return {f["key"] for f in fields if f.get("required")}


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
