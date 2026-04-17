"""Batch add-entry implementation for optimized plan execution.

Accepts multiple add-entry requests and executes them with a single
load/validate/write cycle, dramatically reducing I/O for large plans.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from ..migrate_cell_line_policy import normalize_field_options_policy_data
from ..schema_aliases import get_input_stored_at
from ..yaml_ops import append_audit_event, load_yaml, write_yaml
from .audit_details import add_entry_details
from .write_add_entry import (
    _build_add_entry_records,
    _validate_add_entry_request_data,
)
from .write_common import api


def tool_batch_add_entries(
    yaml_path: str,
    entries: List[Dict[str, Any]],
    *,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Add multiple entries in a single load/write cycle.

    Each entry dict must contain: box, positions, stored_at/frozen_at, fields.
    Returns a batch result with per-entry status in ``entry_results``.
    Atomicity: all entries must validate before any are written.
    """
    action = "add_entry"
    tool_name = "tool_batch_add_entries"

    if not entries:
        return {"ok": True, "entry_results": [], "count": 0}

    # Single execution-gate validation for the batch
    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        tool_input={"entries": entries, "request_backup_path": request_backup_path},
        payload={
            "stored_at": get_input_stored_at(entries[0]),
            "positions": entries[0].get("positions"),
        },
        dry_run=False,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation

    # Single YAML load
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input={"entries": entries},
        )

    normalized = normalize_field_options_policy_data(data)
    if not normalized.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=normalized.get("error_code", "normalize_failed"),
            message=normalized.get("message", "Failed to normalize field options policy."),
            actor_context=actor_context,
            tool_input={"entries": entries},
            before_data=data if isinstance(data, dict) else None,
        )
    data = normalized.get("data")

    # Phase 1: Validate all entries against progressively-updated in-memory data
    candidate_data = deepcopy(data)
    entry_results: List[Dict[str, Any]] = []
    all_audit_metas: List[Dict[str, Any]] = []
    has_failure = False

    for idx, entry in enumerate(entries):
        box = entry.get("box")
        positions = entry.get("positions")
        stored_at = get_input_stored_at(entry)
        fields = dict(entry.get("fields") or {})

        prepared, failure = _validate_add_entry_request_data(
            data=candidate_data,
            box=box,
            positions=positions,
            fields=fields,
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            actor_context=actor_context,
            tool_input=entry,
        )
        if failure:
            entry_results.append({
                "ok": False,
                "index": idx,
                "error_code": failure.get("error_code", "validation_failed"),
                "message": failure.get("message", "Validation failed"),
            })
            has_failure = True
            continue

        norm_positions = prepared["positions"]
        records = candidate_data.get("inventory", [])
        built = _build_add_entry_records(
            records,
            box=box,
            positions=norm_positions,
            frozen_at=stored_at,
            fields=prepared["fields"],
            user_field_keys=prepared["user_field_keys"],
        )

        # Append to candidate inventory in-memory for next iteration's conflict check
        candidate_inventory = candidate_data.setdefault("inventory", [])
        candidate_inventory.extend(built["new_records"])

        entry_results.append({
            "ok": True,
            "index": idx,
            "created": built["created"],
            "new_ids": [c["id"] for c in built["created"]],
            "count": len(built["created"]),
        })

        # Build audit meta for this entry (will be appended after write)
        all_audit_metas.append(api._build_audit_meta(
            action=action,
            source=source,
            tool_name="tool_add_entry",
            actor_context=actor_context,
            details=add_entry_details(
                record_ids=[c["id"] for c in built["created"]],
                box=box,
                positions=[int(p) for p in norm_positions],
                frozen_at=stored_at,
                fields=prepared["fields"],
            ),
            tool_input={
                "box": box,
                "positions": [int(p) for p in norm_positions],
                "frozen_at": stored_at,
                "fields": prepared["fields"],
            },
        ))

    # Atomic: if any entry failed validation, reject the entire batch
    if has_failure:
        failed_entries = [r for r in entry_results if not r["ok"]]
        messages = "; ".join(
            f"entry[{r['index']}]: {r['message']}" for r in failed_entries
        )
        return {
            "ok": False,
            "error_code": "batch_validation_failed",
            "message": f"Batch add blocked: {len(failed_entries)} entries failed validation ({messages})",
            "entry_results": entry_results,
            "blocked_items": [
                {
                    "record_id": entries[r["index"]].get("record_id"),
                    "box": entries[r["index"]].get("box"),
                    "position": (entries[r["index"]].get("positions") or [None])[0],
                    "error_code": r.get("error_code"),
                    "message": r.get("message"),
                }
                for r in failed_entries
            ],
        }

    # Phase 2: Single integrity validation on final state
    batch_changed_ids = []
    for r in entry_results:
        if r.get("ok"):
            batch_changed_ids.extend(r.get("new_ids") or [])
    validation_error = api._validate_data_or_error(
        candidate_data, changed_ids=batch_changed_ids or None
    )
    if validation_error:
        return {
            "ok": False,
            "error_code": validation_error.get("error_code", "integrity_validation_failed"),
            "message": validation_error.get("message", "Validation failed"),
            "errors": validation_error.get("errors"),
            "errors_detail": validation_error.get("errors_detail"),
        }

    # Phase 3: Single disk write
    try:
        # Write with the first audit meta; remaining will be appended separately
        first_audit = all_audit_metas[0] if all_audit_metas else None
        backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            backup_path=request_backup_path,
            audit_meta=first_audit,
        )
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Batch add failed: {exc}",
            actor_context=actor_context,
            tool_input={"entries": entries},
            before_data=data,
        )

    # Phase 4: Append remaining audit events (skip first, already written by write_yaml)
    for audit_meta in all_audit_metas[1:]:
        try:
            append_audit_event(
                yaml_path=yaml_path,
                before_data=data,
                after_data=candidate_data,
                backup_path=None,
                warnings=[],
                audit_meta=audit_meta,
            )
        except Exception:
            pass  # Audit failures must not affect operation outcome

    total_created = sum(r.get("count", 0) for r in entry_results if r.get("ok"))
    return {
        "ok": True,
        "entry_results": entry_results,
        "count": total_created,
        "backup_path": backup_path,
    }
