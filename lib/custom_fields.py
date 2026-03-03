"""Parse and validate custom field definitions from YAML meta."""

import sys

# Truly structural keys that cannot be user-configured fields.
STRUCTURAL_FIELD_KEYS = frozenset({
    "id", "box", "position", "frozen_at", "thaw_events",
})

_VALID_TYPES = {"str", "int", "float", "date"}

# Keep empty by default: users explicitly decide their own custom fields.
DEFAULT_PRESET_FIELDS = []

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

# Default note field definition (auto-injected when not explicitly declared).
DEFAULT_NOTE_FIELD = {
    "key": "note",
    "label": "Note",
    "type": "str",
    "default": None,
    "required": False,
    "multiline": True,
}


def _build_default_cell_line_field(meta):
    """Synthesize a cell_line field def from legacy ``meta`` keys.

    Reads ``meta.cell_line_options`` and ``meta.cell_line_required`` so that
    old YAML files work without modification.
    """
    meta = meta or {}
    raw_opts = meta.get("cell_line_options")
    if isinstance(raw_opts, list):
        options = [str(o) for o in raw_opts if o]
    else:
        options = list(DEFAULT_CELL_LINE_OPTIONS)
    required = bool(meta.get("cell_line_required", True))
    return {
        "key": "cell_line",
        "label": "Cell Line",
        "type": "str",
        "default": DEFAULT_UNKNOWN_CELL_LINE if required else None,
        "required": required,
        "options": options,
    }


def parse_custom_fields(meta):
    """Parse ``meta.custom_fields`` and return a validated list.

    Each item is normalised to
    ``{"key", "label", "type", "default", "required"}``
    with optional ``"options"`` (list of str) and ``"multiline"`` (bool).
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

        entry = {
            "key": key,
            "label": label,
            "type": field_type,
            "default": default,
            "required": required,
        }

        # Optional: dropdown options list
        options = item.get("options")
        if isinstance(options, list):
            entry["options"] = [str(o) for o in options if o]

        # Optional: multiline hint for GUI rendering
        if item.get("multiline"):
            entry["multiline"] = True

        seen_keys.add(key)
        result.append(entry)

    return result


def get_effective_fields(meta):
    """Return the full list of user-configurable field definitions.

    Always includes ``cell_line`` and ``note`` (auto-injected from legacy
    ``meta`` keys when not explicitly declared in ``meta.custom_fields``).
    """
    fields = parse_custom_fields(meta)
    keys = {f["key"] for f in fields}

    # Auto-inject cell_line if not explicitly declared
    if "cell_line" not in keys:
        fields.insert(0, _build_default_cell_line_field(meta))

    # Auto-inject note if not explicitly declared
    if "note" not in keys:
        # Insert after cell_line
        idx = next((i for i, f in enumerate(fields) if f["key"] == "cell_line"), 0) + 1
        fields.insert(idx, dict(DEFAULT_NOTE_FIELD))

    return fields


def get_field_options(meta, field_key):
    """Return the options list for any field, or ``[]`` if none defined."""
    for field in get_effective_fields(meta):
        if field["key"] == field_key:
            return field.get("options") or []
    return []


def is_field_required(meta, field_key):
    """Check if a given field is marked as required."""
    for field in get_effective_fields(meta):
        if field["key"] == field_key:
            return field.get("required", False)
    return False


def get_display_key(meta):
    """Return the field key used for grid cell labels.

    Uses ``meta.display_key`` if set, otherwise the first effective field's key,
    falling back to ``"cell_line"`` when no custom fields are defined.
    """
    dk = (meta or {}).get("display_key")
    if dk and isinstance(dk, str):
        return dk
    fields = get_effective_fields(meta)
    if fields:
        return fields[0]["key"]
    return "cell_line"


def get_color_key(meta):
    """Return the field key used for grid cell coloring and filter grouping.

    Uses ``meta.color_key`` if set, otherwise ``"cell_line"``.
    """
    ck = (meta or {}).get("color_key")
    if ck and isinstance(ck, str):
        return ck
    return "cell_line"


def get_cell_line_options(meta):
    """Return the list of predefined cell_line values from meta.

    Backward-compatible wrapper around :func:`get_field_options`.
    """
    opts = get_field_options(meta, "cell_line")
    return opts if isinstance(opts, list) else list(DEFAULT_CELL_LINE_OPTIONS)


def get_color_key_options(meta):
    """Return the list of predefined values for the color_key field.

    Looks up ``options`` on the effective field definition first, then
    falls back to ``{color_key}_options`` in meta for legacy support.
    Returns an empty list if no options are defined (will use hash-based fallback).
    """
    color_key = get_color_key(meta)
    # Try effective field options first
    opts = get_field_options(meta, color_key)
    if opts:
        return opts
    # Legacy fallback: {color_key}_options in meta
    opts_key = f"{color_key}_options"
    raw = (meta or {}).get(opts_key)
    if isinstance(raw, list):
        return [str(o) for o in raw if o]
    return []


def get_required_field_keys(meta):
    """Return the set of user-field keys marked as required."""
    fields = get_effective_fields(meta)
    return {f["key"] for f in fields if f.get("required")}


def is_cell_line_required(meta):
    """Check if cell_line is marked as required.

    Backward-compatible wrapper around :func:`is_field_required`.
    """
    return is_field_required(meta, "cell_line")


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
