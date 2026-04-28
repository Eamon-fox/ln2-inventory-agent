"""Batch edit-entry implementation for plan execution.

The batch path applies many edit_entry operations with one YAML load and one
YAML write while preserving the same validation rules as the single-entry
Tool API.  The batch is atomic: any failed entry blocks the whole write.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from .edit_entry_core import (
    apply_edit_to_candidate,
    editable_fields_for_data,
    effective_fields_for_data,
    edit_entry_error,
    prepare_edit_document,
)
from ..yaml_ops import append_audit_event, load_yaml, write_yaml
from .write_common import api


def _batch_failure_result(
    *,
    entries: List[Dict[str, Any]],
    entry_results: List[Dict[str, Any]],
    error_code: str = "batch_validation_failed",
    message_prefix: str = "Batch edit blocked",
) -> Dict[str, Any]:
    failed_entries = [r for r in entry_results if not r.get("ok")]
    messages = "; ".join(
        f"entry[{r.get('index')}]: {r.get('message') or 'Validation failed'}"
        for r in failed_entries
    )
    blocked_items = []
    for result in failed_entries:
        idx = int(result.get("index") or 0)
        entry = entries[idx] if 0 <= idx < len(entries) else {}
        blocked_items.append(
            {
                "record_id": entry.get("record_id"),
                "box": entry.get("box"),
                "position": entry.get("position"),
                "error_code": result.get("error_code") or error_code,
                "message": result.get("message") or "Validation failed",
            }
        )
    return {
        "ok": False,
        "error_code": error_code,
        "message": f"{message_prefix}: {len(failed_entries)} entries failed validation ({messages})",
        "entry_results": entry_results,
        "blocked_items": blocked_items,
    }


def tool_batch_edit_entries(
    yaml_path: str,
    entries: List[Dict[str, Any]],
    *,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Edit multiple records in one load/validate/write cycle."""

    action = "edit_entry"
    tool_name = "tool_batch_edit_entries"

    if not entries:
        return {"ok": True, "entry_results": [], "count": 0}

    first_entry = entries[0] if isinstance(entries[0], dict) else {}
    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        tool_input={"entries": entries, "request_backup_path": request_backup_path},
        payload={"fields": first_entry.get("fields") or {}},
        dry_run=False,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation

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

    prepared = prepare_edit_document(data)
    if not prepared.get("ok"):
        return api._failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code=prepared.get("error_code", "normalize_failed"),
            message=prepared.get("message", "Failed to normalize field options policy."),
            actor_context=actor_context,
            tool_input={"entries": entries},
            before_data=prepared.get("data") if isinstance(prepared.get("data"), dict) else data if isinstance(data, dict) else None,
            errors=prepared.get("errors"),
        )
    data = prepared.get("data")

    candidate_data = deepcopy(data)
    effective_fields = effective_fields_for_data(candidate_data)
    allowed = editable_fields_for_data(candidate_data)

    entry_results: List[Dict[str, Any]] = []
    audit_metas: List[Dict[str, Any]] = []
    changed_ids: List[int] = []
    has_failure = False

    for idx, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            entry_results.append(edit_entry_error(idx, "invalid_tool_input", "entry must be an object"))
            has_failure = True
            continue

        try:
            record_id = int(raw_entry.get("record_id"))
        except Exception:
            entry_results.append(edit_entry_error(idx, "invalid_tool_input", "record_id must be an integer"))
            has_failure = True
            continue

        edit_result = apply_edit_to_candidate(
            candidate_data=candidate_data,
            record_id=record_id,
            fields=raw_entry.get("fields"),
            validate_fn=api._validate_data_or_error,
            effective_fields=effective_fields,
            allowed_fields=allowed,
            index=idx,
        )
        if not edit_result.get("ok"):
            entry_results.append(edit_result)
            has_failure = True
            continue

        entry_payload = {
            "ok": True,
            "index": idx,
            "record_id": record_id,
            "before": edit_result.get("before") or {},
            "after": edit_result.get("after") or {},
        }
        if edit_result.get("alias_warnings"):
            entry_payload["warnings"] = list(edit_result.get("alias_warnings") or [])
        entry_results.append(entry_payload)
        changed_ids.append(record_id)

        audit_metas.append(
            api._build_audit_meta(
                action=action,
                source=source,
                tool_name="tool_edit_entry",
                actor_context=actor_context,
                details=edit_result.get("audit_details"),
                tool_input={
                    "record_id": record_id,
                    "fields": dict(edit_result.get("normalized_fields") or {}),
                },
            )
        )

    if has_failure:
        return _batch_failure_result(entries=entries, entry_results=entry_results)

    validation_error = api._validate_data_or_error(candidate_data, changed_ids=changed_ids or None)
    if validation_error:
        return {
            "ok": False,
            "error_code": validation_error.get("error_code", "integrity_validation_failed"),
            "message": validation_error.get("message", "Validation failed"),
            "errors": validation_error.get("errors"),
            "errors_detail": validation_error.get("errors_detail"),
        }

    try:
        first_audit = audit_metas[0] if audit_metas else None
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
            message=f"Batch edit failed: {exc}",
            actor_context=actor_context,
            tool_input={"entries": entries},
            before_data=data,
        )

    for audit_meta in audit_metas[1:]:
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
            pass

    return {
        "ok": True,
        "entry_results": entry_results,
        "count": len(entry_results),
        "backup_path": backup_path,
    }
