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

from .schema_aliases import (
    CANONICAL_STORED_AT_KEY,
    get_storage_events,
    get_stored_at,
    structural_field_label,
)


class ValidationMessage(str):
    """Error/warning message that also carries structured detail metadata.

    Subclassing ``str`` keeps backward compatibility: every place that currently
    treats validator output as strings (formatting, logging, test assertions on
    message text) continues to work unchanged. GUI layers can probe
    ``getattr(msg, "detail", None)`` to recover the structured payload.
    """

    __slots__ = ("detail",)

    def __new__(cls, text: str, **detail: Any):
        instance = super().__new__(cls, text)
        instance.detail = dict(detail)
        return instance


def _vmsg(text: str, **detail: Any) -> ValidationMessage:
    return ValidationMessage(text, **detail)


def extract_error_details(errors: Any) -> List[Dict[str, Any]]:
    """Return structured detail dicts for every ValidationMessage in *errors*.

    Plain strings are returned with ``{"message": str}`` so callers always get a
    uniform list of dicts (possibly with sparse fields).
    """
    result: List[Dict[str, Any]] = []
    for err in errors or []:
        if isinstance(err, ValidationMessage):
            entry = dict(err.detail)
            entry.setdefault("message", str(err))
            result.append(entry)
        else:
            result.append({"message": str(err)})
    return result


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

    storage_events = get_storage_events(rec) or []
    if not isinstance(storage_events, list):
        return False
    for ev in storage_events:
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
    rec_id = rec.get("id") if isinstance(rec, dict) else None
    rec_box = rec.get("box") if isinstance(rec, dict) else None
    rec_position = rec.get("position") if isinstance(rec, dict) else None

    def _ctx(**extra: Any) -> Dict[str, Any]:
        base = {
            "record_id": rec_id,
            "record_index": idx,
            "box": rec_box,
            "position": rec_position,
        }
        base.update(extra)
        return base

    # --- required fields ---
    for field in required_fields:
        if field not in rec or rec[field] is None:
            errors.append(_vmsg(
                f"{label}: missing required field '{field}'",
                rule="missing_required",
                field=field,
                **_ctx(),
            ))

    # --- id ---
    rec_id_value = rec.get("id")
    if not is_plain_int(rec_id_value):
        errors.append(_vmsg(
            f"{label}: 'id' must be a positive integer",
            rule="invalid_id", field="id", value=rec_id_value, **_ctx(),
        ))
    elif rec_id_value <= 0:
        errors.append(_vmsg(
            f"{label}: 'id' must be a positive integer",
            rule="invalid_id", field="id", value=rec_id_value, **_ctx(),
        ))

    # --- box ---
    box = rec.get("box")
    if not is_plain_int(box):
        errors.append(_vmsg(
            f"{label}: 'box' must be an integer",
            rule="invalid_box", field="box", value=box, **_ctx(),
        ))
    elif not validate_box_fn(box):
        box_rule = format_box_constraint_fn()
        errors.append(_vmsg(
            f"{label}: 'box' out of range ({box_rule})",
            rule="box_out_of_range", field="box", value=box,
            expected=box_rule, **_ctx(),
        ))

    # --- position ---
    position = rec.get("position")
    if position is not None:
        if not is_plain_int(position):
            errors.append(_vmsg(
                f"{label}: 'position' must be an integer",
                rule="invalid_position", field="position", value=position, **_ctx(),
            ))
        elif not (pos_lo <= position <= pos_hi):
            errors.append(_vmsg(
                f"{label}: 'position' {position} out of range ({pos_lo}-{pos_hi})",
                rule="position_out_of_range", field="position", value=position,
                expected=f"{pos_lo}-{pos_hi}", **_ctx(),
            ))
    else:
        if not has_takeout_history(rec, normalize_action_fn):
            errors.append(_vmsg(
                f"{label}: 'position' is null but no takeout history found",
                rule="position_null_without_takeout", field="position", **_ctx(),
            ))

    # --- frozen_at ---
    stored_at = get_stored_at(rec)
    if not validate_date_format(stored_at):
        errors.append(_vmsg(
            f"{label}: '{CANONICAL_STORED_AT_KEY}' must be YYYY-MM-DD",
            rule="invalid_date", field=CANONICAL_STORED_AT_KEY,
            value=stored_at, expected="YYYY-MM-DD", **_ctx(),
        ))
    else:
        frozen_date = parse_date(stored_at)
        if frozen_date and frozen_date > datetime.now():
            errors.append(_vmsg(
                f"{label}: stored date {stored_at} is in the future",
                rule="date_in_future", field=CANONICAL_STORED_AT_KEY,
                value=stored_at, **_ctx(),
            ))

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
    event_field_label = structural_field_label("storage_events")
    rec_id = rec.get("id") if isinstance(rec, dict) else None
    rec_box = rec.get("box") if isinstance(rec, dict) else None
    rec_position = rec.get("position") if isinstance(rec, dict) else None

    def _ev_ctx(event_idx: int, **extra: Any) -> Dict[str, Any]:
        base = {
            "record_id": rec_id,
            "box": rec_box,
            "position": rec_position,
            "field": "storage_events",
            "event_index": event_idx,
        }
        base.update(extra)
        return base

    storage_events = get_storage_events(rec)
    if storage_events is None:
        return
    if not isinstance(storage_events, list):
        errors.append(_vmsg(
            f"{label}: '{event_field_label}' must be a list",
            rule="invalid_storage_events", field="storage_events",
            record_id=rec_id, box=rec_box, position=rec_position,
        ))
        return

    for event_idx, ev in enumerate(storage_events, 1):
        if not isinstance(ev, dict):
            errors.append(_vmsg(
                f"{label}: {event_field_label}[{event_idx}] must be an object",
                rule="invalid_event_shape", **_ev_ctx(event_idx),
            ))
            continue

        ev_action = normalize_action_fn(ev.get("action"))
        if not ev_action:
            errors.append(_vmsg(
                f"{label}: {event_field_label}[{event_idx}] has invalid action",
                rule="invalid_event_action", value=ev.get("action"),
                **_ev_ctx(event_idx),
            ))

        ev_date = ev.get("date")
        if not validate_date_format(ev_date):
            errors.append(_vmsg(
                f"{label}: {event_field_label}[{event_idx}] has invalid date",
                rule="invalid_event_date", value=ev_date,
                expected="YYYY-MM-DD", **_ev_ctx(event_idx),
            ))
        elif check_event_future_dates:
            parsed_ev_date = parse_date(ev_date)
            if parsed_ev_date and parsed_ev_date > datetime.now():
                errors.append(_vmsg(
                    f"{label}: {event_field_label}[{event_idx}] date {ev_date} is in the future",
                    rule="event_date_in_future", value=ev_date,
                    **_ev_ctx(event_idx),
                ))

        ev_positions = ev.get("positions")
        if isinstance(ev_positions, int):
            ev_positions = [ev_positions]
        if not isinstance(ev_positions, list) or not ev_positions:
            errors.append(_vmsg(
                f"{label}: {event_field_label}[{event_idx}] positions must be a non-empty list",
                rule="invalid_event_positions", value=ev.get("positions"),
                **_ev_ctx(event_idx),
            ))
            continue

        seen_ev_pos: Set[int] = set()
        for ev_pos in ev_positions:
            if not isinstance(ev_pos, int):
                errors.append(_vmsg(
                    f"{label}: {event_field_label}[{event_idx}] position {ev_pos} must be an integer",
                    rule="invalid_event_position_type", value=ev_pos,
                    **_ev_ctx(event_idx),
                ))
                continue
            if not (pos_lo <= ev_pos <= pos_hi):
                errors.append(_vmsg(
                    f"{label}: {event_field_label}[{event_idx}] position {ev_pos} out of range ({pos_lo}-{pos_hi})",
                    rule="event_position_out_of_range", value=ev_pos,
                    expected=f"{pos_lo}-{pos_hi}", **_ev_ctx(event_idx),
                ))
                continue
            if ev_pos in seen_ev_pos:
                errors.append(_vmsg(
                    f"{label}: {event_field_label}[{event_idx}] duplicate position {ev_pos}",
                    rule="duplicate_event_position", value=ev_pos,
                    **_ev_ctx(event_idx),
                ))
            seen_ev_pos.add(ev_pos)


def _validate_option_fields(
    rec: Dict[str, Any],
    label: str,
    option_fields: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    """Validate option-bearing fields with relaxed (warning-only) semantics."""
    rec_id = rec.get("id") if isinstance(rec, dict) else None
    rec_box = rec.get("box") if isinstance(rec, dict) else None
    rec_position = rec.get("position") if isinstance(rec, dict) else None

    def _opt_ctx(fkey: str, **extra: Any) -> Dict[str, Any]:
        base = {
            "record_id": rec_id,
            "box": rec_box,
            "position": rec_position,
            "field": fkey,
        }
        base.update(extra)
        return base

    for field_def in option_fields:
        fkey = field_def["key"]
        foptions = field_def.get("options") or []
        frequired = field_def.get("required", False)

        if fkey not in rec:
            warnings.append(_vmsg(
                f"{label}: missing '{fkey}' (legacy-compatible warning)",
                rule="option_field_missing", **_opt_ctx(fkey),
            ))
            continue

        raw_val = rec.get(fkey)
        if raw_val is None:
            val = ""
        elif isinstance(raw_val, str):
            val = raw_val.strip()
        else:
            val = str(raw_val).strip()
            warnings.append(_vmsg(
                f"{label}: '{fkey}' is not a string (legacy-compatible warning)",
                rule="option_field_not_string", value=raw_val,
                **_opt_ctx(fkey),
            ))

        if frequired and not val:
            warnings.append(_vmsg(
                f"{label}: '{fkey}' is empty while required=true (legacy-compatible warning)",
                rule="option_field_empty_required", value=raw_val,
                **_opt_ctx(fkey),
            ))
        elif val and foptions and val not in foptions:
            opts_str = ", ".join(foptions[:5])
            if len(foptions) > 5:
                opts_str += f" ... total {len(foptions)}"
            warnings.append(_vmsg(
                f"{label}: '{fkey}' not in configured options ({opts_str}) "
                "(legacy-compatible warning)",
                rule="option_field_not_in_options", value=val,
                expected=list(foptions), **_opt_ctx(fkey),
            ))
