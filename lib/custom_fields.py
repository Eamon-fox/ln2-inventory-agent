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

UNSUPPORTED_BOX_FIELDS_ERROR_CODE = "unsupported_box_fields"


def unsupported_box_fields_issue(meta):
    """Return a structured issue when legacy ``meta.box_fields`` is present."""
    if not isinstance(meta, dict):
        return None
    if "box_fields" not in meta:
        return None

    raw_box_fields = meta.get("box_fields")
    details = {
        "unsupported_meta_key": "box_fields",
        "box_fields_type": type(raw_box_fields).__name__,
    }
    if isinstance(raw_box_fields, dict):
        box_ids = [str(key).strip() for key in raw_box_fields.keys() if str(key).strip()]
        if box_ids:
            details["boxes"] = box_ids[:10]
            details["box_count"] = len(box_ids)

    return {
        "error_code": UNSUPPORTED_BOX_FIELDS_ERROR_CODE,
        "message": (
            "Unsupported dataset model: meta.box_fields is no longer supported. "
            "Use a single global meta.custom_fields schema."
        ),
        "details": details,
    }


def ensure_supported_field_model(meta):
    """Raise ``ValueError`` when metadata uses an unsupported field model."""
    issue = unsupported_box_fields_issue(meta)
    if issue:
        raise ValueError(issue["message"])


def _has_legacy_cell_line_policy(meta):
    """Return True when legacy cell_line behavior should remain enabled."""
    meta = meta or {}
    if not isinstance(meta, dict):
        return True
    if "cell_line_options" in meta or "cell_line_required" in meta:
        return True
    # Legacy datasets may not have declared ``meta.custom_fields``.
    return "custom_fields" not in meta


def _has_declared_custom_field(meta, key):
    raw = (meta or {}).get("custom_fields")
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("key") or "").strip()
        if text == key:
            return True
    return False


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


def parse_custom_fields(meta, *, field_list=None):
    """Parse ``meta.custom_fields`` (or an explicit *field_list*) and return a validated list.

    Each item is normalised to
    ``{"key", "label", "type", "default", "required"}``
    with optional ``"options"`` (list of str) and ``"multiline"`` (bool).
    Invalid or conflicting entries are silently dropped with a stderr warning.

    Args:
        meta: The ``meta`` dict from the YAML document.
        field_list: When provided, parse this list instead of ``meta.custom_fields``.
            Used for explicit alternate field lists during parsing.
    """
    raw = field_list if field_list is not None else (meta or {}).get("custom_fields")
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
        if key == "note":
            # ``note`` is a fixed system field: only label is customizable.
            entry = dict(DEFAULT_NOTE_FIELD)
            entry["label"] = label or DEFAULT_NOTE_FIELD["label"]
            seen_keys.add(key)
            result.append(entry)
            continue

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


def get_effective_fields(meta, box=None):
    """Return the full list of user-configurable field definitions.

    ``box`` is accepted for backward-compatible call signatures but ignored.
    The only supported schema source is the global ``meta.custom_fields`` list.

    Always includes fixed ``note``.
    Includes ``cell_line`` only when explicitly declared or legacy metadata
    indicates compatibility mode.
    """
    meta = meta or {}
    fields = parse_custom_fields(meta)
    keys = {f["key"] for f in fields}

    # Auto-inject cell_line only for legacy compatibility windows.
    if "cell_line" not in keys and _has_legacy_cell_line_policy(meta):
        fields.insert(0, _build_default_cell_line_field(meta))
        keys.add("cell_line")

    # Auto-inject fixed note if not explicitly declared.
    if "note" not in keys:
        # Insert after cell_line when present so legacy defaults remain familiar.
        idx = next((i for i, f in enumerate(fields) if f["key"] == "cell_line"), -1) + 1
        fields.insert(idx, dict(DEFAULT_NOTE_FIELD))

    return fields


def get_field_options(meta, field_key, box=None):
    """Return the options list for any field, or ``[]`` if none defined."""
    for field in get_effective_fields(meta, box=box):
        if field["key"] == field_key:
            return field.get("options") or []
    return []


def is_field_required(meta, field_key, box=None):
    """Check if a given field is marked as required."""
    for field in get_effective_fields(meta, box=box):
        if field["key"] == field_key:
            return field.get("required", False)
    return False


def get_display_key(meta, box=None):
    """Return the field key used for grid cell labels.

    Uses ``meta.display_key`` if set, otherwise the first effective field's key,
    falling back to ``"cell_line"`` when no custom fields are defined.
    """
    dk = (meta or {}).get("display_key")
    if isinstance(dk, str) and dk.strip():
        return dk
    fields = get_effective_fields(meta, box=box)
    for field in fields:
        key = str((field or {}).get("key") or "").strip()
        if key and key != "note":
            return key
    if fields:
        return str(fields[0].get("key") or "note")
    return "note"


def get_color_key(meta, box=None):
    """Return the field key used for grid cell coloring and filter grouping.

    Uses ``meta.color_key`` if set, otherwise ``"cell_line"``.
    """
    ck = (meta or {}).get("color_key")
    if isinstance(ck, str) and ck.strip():
        return ck
    fields = get_effective_fields(meta, box=box)
    keys = [str((field or {}).get("key") or "").strip() for field in fields]
    if "cell_line" in keys:
        return "cell_line"
    for key in keys:
        if key and key != "note":
            return key
    return "note"


def get_cell_line_options(meta, box=None):
    """Return the list of predefined cell_line values from meta.

    Backward-compatible wrapper around :func:`get_field_options`.
    """
    opts = get_field_options(meta, "cell_line", box=box)
    if isinstance(opts, list):
        if opts:
            return opts
        if _has_declared_custom_field(meta, "cell_line"):
            return []
    raw = (meta or {}).get("cell_line_options")
    if isinstance(raw, list):
        return [str(o) for o in raw if o]
    if _has_legacy_cell_line_policy(meta):
        return list(DEFAULT_CELL_LINE_OPTIONS)
    return []


def get_color_key_options(meta, box=None):
    """Return the list of predefined values for the color_key field.

    Looks up ``options`` on the effective field definition first, then
    falls back to ``{color_key}_options`` in meta for legacy support.
    Returns an empty list if no options are defined (will use hash-based fallback).
    """
    color_key = get_color_key(meta, box=box)
    # Try effective field options first
    opts = get_field_options(meta, color_key, box=box)
    if opts:
        return opts
    # Legacy fallback: {color_key}_options in meta
    opts_key = f"{color_key}_options"
    raw = (meta or {}).get(opts_key)
    if isinstance(raw, list):
        return [str(o) for o in raw if o]
    return []


def get_required_field_keys(meta, box=None):
    """Return the set of user-field keys marked as required."""
    fields = get_effective_fields(meta, box=box)
    return {f["key"] for f in fields if f.get("required")}


def is_cell_line_required(meta, box=None):
    """Check if cell_line is marked as required.

    Backward-compatible wrapper around :func:`is_field_required`.
    """
    for field in get_effective_fields(meta, box=box):
        if field.get("key") == "cell_line":
            return bool(field.get("required", False))
    if isinstance(meta, dict) and "cell_line_required" in meta:
        return bool(meta.get("cell_line_required"))
    return bool(_has_legacy_cell_line_policy(meta))


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
