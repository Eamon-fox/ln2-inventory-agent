"""Shared primitive validation functions for inventory records.

This module contains the low-level validation helpers used by both
``validators.py`` (runtime single-record validation) and
``import_validation_core.py`` (batch import/migration validation).

These functions are intentionally kept free of module-level dependencies on
``config.py`` or ``position_fmt.py`` so that ``import_validation_core`` can
continue to operate without runtime configuration.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Scalar type helpers
# ---------------------------------------------------------------------------

def is_plain_int(value: Any) -> bool:
    """Return True only for integers, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def validate_date_format(date_str: Any) -> bool:
    """Validate that *date_str* matches YYYY-MM-DD format."""
    try:
        datetime.strptime(str(date_str), "%Y-%m-%d")
        return True
    except Exception:
        return False


def parse_date(date_str: Any) -> Optional[datetime]:
    """Parse YYYY-MM-DD string to datetime, or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Record labeling
# ---------------------------------------------------------------------------

def record_label(rec: Dict[str, Any], idx: Optional[int]) -> str:
    """Human-readable label for a record in error messages."""
    if idx is None:
        return f"Record (id={rec.get('id', 'N/A')})"
    return f"Record #{idx + 1} (id={rec.get('id', 'N/A')})"


# ---------------------------------------------------------------------------
# Depletion / takeout history
# ---------------------------------------------------------------------------

def has_takeout_history(rec: Dict[str, Any], normalize_action_fn: Any = None) -> bool:
    """Return True if record has a takeout event in thaw_events.

    Args:
        rec: Inventory record dict.
        normalize_action_fn: Callable that maps a raw action string to its
            canonical form.  Must return ``"takeout"`` for takeout actions.
            When *None*, a minimal built-in alias table is used.
    """
    if normalize_action_fn is None:
        normalize_action_fn = _builtin_normalize_action

    thaw_events = rec.get("thaw_events") or []
    if not isinstance(thaw_events, list):
        return False
    for ev in thaw_events:
        if not isinstance(ev, dict):
            continue
        if normalize_action_fn(ev.get("action")) == "takeout":
            return True
    return False


_BUILTIN_ACTION_ALIAS = {
    "takeout": "takeout",
    "move": "move",
    "\u53d6\u51fa": "takeout",
    "\u79fb\u52a8": "move",
}


def _builtin_normalize_action(action: Any) -> Optional[str]:
    if action is None:
        return None
    raw = str(action).strip()
    return _BUILTIN_ACTION_ALIAS.get(raw.lower()) or _BUILTIN_ACTION_ALIAS.get(raw)


# ---------------------------------------------------------------------------
# Core record field validation
# ---------------------------------------------------------------------------

def validate_record_fields(
    rec: Dict[str, Any],
    idx: Optional[int],
    *,
    pos_range: Tuple[int, int],
    validate_box_fn: Any,
    format_box_constraint_fn: Any,
    normalize_action_fn: Any,
    required_fields: List[str],
    option_fields: List[Dict[str, Any]],
    check_event_future_dates: bool = True,
) -> Tuple[List[str], List[str]]:
    """Validate the core fields of a single inventory record.

    This function centralises the field-level checks that are common to both
    runtime validation and import validation.  Callers supply context-specific
    helpers (box validation, action normalisation) so the function stays free
    of direct config/layout dependencies.

    Args:
        rec: The inventory record dict.
        idx: Record index for error messages (may be None).
        pos_range: ``(min_pos, max_pos)`` tuple for position validation.
        validate_box_fn: ``(box_value) -> bool``.
        format_box_constraint_fn: ``() -> str`` for error messages.
        normalize_action_fn: ``(action_str) -> Optional[str]``.
        required_fields: Field keys that must be present and non-None.
        option_fields: List of ``{"key", "options", "required"}`` dicts for
            relaxed option-bearing field validation (warnings only).
        check_event_future_dates: Whether to flag thaw event dates in the
            future.  Defaults to True.

    Returns:
        ``(errors, warnings)`` tuple.
    """
    errors: List[str] = []
    warnings: List[str] = []
    label = record_label(rec, idx)
    pos_lo, pos_hi = pos_range

    # --- required fields ---
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(f"{label}: missing required field '{field}'")

    # --- id ---
    rec_id_value = rec.get("id")
    if not is_plain_int(rec_id_value):
        errors.append(f"{label}: 'id' must be a positive integer")
    elif rec_id_value <= 0:
        errors.append(f"{label}: 'id' must be a positive integer")

    # --- box ---
    box = rec.get("box")
    if not is_plain_int(box):
        errors.append(f"{label}: 'box' must be an integer")
    elif not validate_box_fn(box):
        box_rule = format_box_constraint_fn()
        errors.append(f"{label}: 'box' out of range ({box_rule})")

    # --- position ---
    position = rec.get("position")
    if position is not None:
        if not is_plain_int(position):
            errors.append(f"{label}: 'position' must be an integer")
        elif not (pos_lo <= position <= pos_hi):
            errors.append(
                f"{label}: 'position' {position} out of range ({pos_lo}-{pos_hi})"
            )
    else:
        if not has_takeout_history(rec, normalize_action_fn):
            errors.append(
                f"{label}: 'position' is null but no takeout history found"
            )

    # --- frozen_at ---
    frozen_at = rec.get("frozen_at")
    if not validate_date_format(frozen_at):
        errors.append(f"{label}: 'frozen_at' must be YYYY-MM-DD")
    else:
        frozen_date = parse_date(frozen_at)
        if frozen_date and frozen_date > datetime.now():
            errors.append(f"{label}: frozen date {frozen_at} is in the future")

    # --- thaw_events ---
    _validate_thaw_events(
        rec, label, pos_lo, pos_hi, normalize_action_fn,
        errors, check_event_future_dates,
    )

    # --- option-bearing fields (warnings only) ---
    _validate_option_fields(rec, label, option_fields, warnings)

    return errors, warnings


def _validate_thaw_events(
    rec: Dict[str, Any],
    label: str,
    pos_lo: int,
    pos_hi: int,
    normalize_action_fn: Any,
    errors: List[str],
    check_event_future_dates: bool,
) -> None:
    """Validate the thaw_events list within a record."""
    thaw_events = rec.get("thaw_events")
    if thaw_events is None:
        return
    if not isinstance(thaw_events, list):
        errors.append(f"{label}: 'thaw_events' must be a list")
        return

    for event_idx, ev in enumerate(thaw_events, 1):
        if not isinstance(ev, dict):
            errors.append(f"{label}: thaw_events[{event_idx}] must be an object")
            continue

        ev_action = normalize_action_fn(ev.get("action"))
        if not ev_action:
            errors.append(f"{label}: thaw_events[{event_idx}] has invalid action")

        ev_date = ev.get("date")
        if not validate_date_format(ev_date):
            errors.append(f"{label}: thaw_events[{event_idx}] has invalid date")
        elif check_event_future_dates:
            parsed_ev_date = parse_date(ev_date)
            if parsed_ev_date and parsed_ev_date > datetime.now():
                errors.append(
                    f"{label}: thaw_events[{event_idx}] date {ev_date} is in the future"
                )

        ev_positions = ev.get("positions")
        if isinstance(ev_positions, int):
            ev_positions = [ev_positions]
        if not isinstance(ev_positions, list) or not ev_positions:
            errors.append(
                f"{label}: thaw_events[{event_idx}] positions must be a non-empty list"
            )
            continue

        seen_ev_pos: Set[int] = set()
        for ev_pos in ev_positions:
            if not isinstance(ev_pos, int):
                errors.append(
                    f"{label}: thaw_events[{event_idx}] position {ev_pos} must be an integer"
                )
                continue
            if not (pos_lo <= ev_pos <= pos_hi):
                errors.append(
                    f"{label}: thaw_events[{event_idx}] position {ev_pos} out of range ({pos_lo}-{pos_hi})"
                )
                continue
            if ev_pos in seen_ev_pos:
                errors.append(
                    f"{label}: thaw_events[{event_idx}] duplicate position {ev_pos}"
                )
            seen_ev_pos.add(ev_pos)


def _validate_option_fields(
    rec: Dict[str, Any],
    label: str,
    option_fields: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    """Validate option-bearing fields with relaxed (warning-only) semantics."""
    for field_def in option_fields:
        fkey = field_def["key"]
        foptions = field_def.get("options") or []
        frequired = field_def.get("required", False)

        if fkey not in rec:
            warnings.append(f"{label}: missing '{fkey}' (legacy-compatible warning)")
            continue

        raw_val = rec.get(fkey)
        if raw_val is None:
            val = ""
        elif isinstance(raw_val, str):
            val = raw_val.strip()
        else:
            val = str(raw_val).strip()
            warnings.append(
                f"{label}: '{fkey}' is not a string (legacy-compatible warning)"
            )

        if frequired and not val:
            warnings.append(
                f"{label}: '{fkey}' is empty while required=true (legacy-compatible warning)"
            )
        elif val and foptions and val not in foptions:
            opts_str = ", ".join(foptions[:5])
            if len(foptions) > 5:
                opts_str += f" ... total {len(foptions)}"
            warnings.append(
                f"{label}: '{fkey}' not in configured options ({opts_str}) "
                "(legacy-compatible warning)"
            )
