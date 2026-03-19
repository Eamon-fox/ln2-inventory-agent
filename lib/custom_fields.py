"""Parse and validate custom field definitions from YAML meta."""

import sys

from .legacy_field_policy import (
    CELL_LINE_FIELD_KEY,
    PHASE_RUNTIME,
    resolve_legacy_field_policy,
    normalize_legacy_custom_field_defs,
    normalize_legacy_field_key,
)
from .schema_aliases import (
    ALL_STRUCTURAL_FIELD_KEYS,
    CANONICAL_STRUCTURAL_FIELD_KEYS,
)

# Truly structural keys that cannot be user-configured fields.
STRUCTURAL_FIELD_KEYS = CANONICAL_STRUCTURAL_FIELD_KEYS

_VALID_TYPES = {"str", "int", "float", "date"}

# Keep empty by default: users explicitly decide their own custom fields.
DEFAULT_PRESET_FIELDS = []

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

    raw, _alias_changes = normalize_legacy_custom_field_defs(raw)

    result = []
    seen_keys = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            print(f"warning: meta.custom_fields[{idx}] is not a dict, skipping", file=sys.stderr)
            continue

        key = normalize_legacy_field_key(item.get("key"))
        if not key or not key.isidentifier():
            print(f"warning: meta.custom_fields[{idx}] has invalid key={key!r}, skipping", file=sys.stderr)
            continue

        if key in ALL_STRUCTURAL_FIELD_KEYS:
            print(
                f"warning: meta.custom_fields[{idx}] key={key!r} conflicts with structural field, skipping",
                file=sys.stderr,
            )
            continue

        if key in seen_keys:
            print(f"warning: meta.custom_fields[{idx}] duplicate key={key!r}, skipping", file=sys.stderr)
            continue

        label = str(item.get("label") or key)
        if key == "note":
            entry = dict(DEFAULT_NOTE_FIELD)
            entry["label"] = label or DEFAULT_NOTE_FIELD["label"]
            seen_keys.add(key)
            result.append(entry)
            continue

        field_type = str(item.get("type") or "str").strip().lower()
        if field_type not in _VALID_TYPES:
            print(
                f"warning: meta.custom_fields[{idx}] unknown type={field_type!r}, defaulting to str",
                file=sys.stderr,
            )
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

        options = item.get("options")
        if isinstance(options, list):
            entry["options"] = [str(option) for option in options if option]

        if item.get("multiline"):
            entry["multiline"] = True

        seen_keys.add(key)
        result.append(entry)

    return result


def get_effective_fields(meta, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the full list of user-configurable field definitions.

    ``box`` is accepted for backward-compatible call signatures but ignored.
    The only supported schema source is the global ``meta.custom_fields`` list.

    Always includes fixed ``note``.
    Injects a synthetic ``cell_line`` field only when the centralized legacy
    policy says that phase should still expose it.
    """
    _ = box
    meta = meta or {}
    declared_fields = parse_custom_fields(meta)
    policy = resolve_legacy_field_policy(
        meta,
        inventory,
        declared_fields=declared_fields,
        phase=phase,
    )
    fields = list(policy.get("effective_fields") or [])
    keys = {str(field.get("key") or "").strip() for field in fields if isinstance(field, dict)}

    if "note" not in keys:
        idx = next((i for i, field in enumerate(fields) if field.get("key") == CELL_LINE_FIELD_KEY), -1) + 1
        fields.insert(idx, dict(DEFAULT_NOTE_FIELD))

    return fields


def get_field_options(meta, field_key, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the options list for any field, or ``[]`` if none defined."""
    for field in get_effective_fields(meta, box=box, inventory=inventory, phase=phase):
        if field["key"] == normalize_legacy_field_key(field_key):
            return field.get("options") or []
    return []


def is_field_required(meta, field_key, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Check if a given field is marked as required."""
    canonical_key = normalize_legacy_field_key(field_key)
    for field in get_effective_fields(meta, box=box, inventory=inventory, phase=phase):
        if field["key"] == canonical_key:
            return bool(field.get("required", False))
    return False


def get_display_key(meta, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the field key used for grid cell labels."""
    dk = (meta or {}).get("display_key")
    if isinstance(dk, str) and dk.strip():
        return dk
    fields = get_effective_fields(meta, box=box, inventory=inventory, phase=phase)
    for field in fields:
        key = str((field or {}).get("key") or "").strip()
        if key and key != "note":
            return key
    if fields:
        return str(fields[0].get("key") or "note")
    return "note"


def get_color_key(meta, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the field key used for grid cell coloring and filter grouping."""
    ck = (meta or {}).get("color_key")
    if isinstance(ck, str) and ck.strip():
        return ck
    fields = get_effective_fields(meta, box=box, inventory=inventory, phase=phase)
    keys = [str((field or {}).get("key") or "").strip() for field in fields]
    if CELL_LINE_FIELD_KEY in keys:
        return CELL_LINE_FIELD_KEY
    for key in keys:
        if key and key != "note":
            return key
    return "note"


def get_color_key_options(meta, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the list of predefined values for the color_key field."""
    color_key = get_color_key(meta, box=box, inventory=inventory, phase=phase)
    opts = get_field_options(meta, color_key, box=box, inventory=inventory, phase=phase)
    if opts:
        return opts
    opts_key = f"{color_key}_options"
    raw = (meta or {}).get(opts_key)
    if isinstance(raw, list):
        return [str(option) for option in raw if option]
    return []


def get_required_field_keys(meta, box=None, inventory=None, phase=PHASE_RUNTIME):
    """Return the set of user-field keys marked as required."""
    fields = get_effective_fields(meta, box=box, inventory=inventory, phase=phase)
    return {field["key"] for field in fields if field.get("required")}


def coerce_value(value, field_type):
    """Coerce a user-input value to the declared type.

    Returns the coerced value, or *None* if the input is empty/blank.
    Raises ``ValueError`` on type mismatch.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if field_type == "int":
        return int(text)
    if field_type == "float":
        return float(text)
    if field_type == "date":
        from lib.validators import validate_date

        if not validate_date(text):
            raise ValueError(f"invalid date: {text}")
        return text
    return text
