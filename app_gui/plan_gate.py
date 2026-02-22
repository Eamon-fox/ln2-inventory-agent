"""Shared validation gate for staging plan items."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app_gui.plan_executor import preflight_plan
from app_gui.plan_model import validate_plan_item


def _blocked_item_payload(error: Dict[str, Any]) -> Dict[str, Any]:
    item = error.get("item") or {}
    return {
        "action": item.get("action"),
        "record_id": item.get("record_id"),
        "box": item.get("box"),
        "position": item.get("position"),
        "to_position": item.get("to_position"),
        "to_box": item.get("to_box"),
        "error_code": error.get("error_code"),
        "message": error.get("message"),
    }


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_item_payload_schema(item: Dict[str, Any]) -> Optional[str]:
    action = str(item.get("action") or "").lower()
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return "payload must be an object"

    if action == "rollback":
        backup_path = payload.get("backup_path")
        if not isinstance(backup_path, str) or not backup_path.strip():
            return "payload.backup_path is required"
        source_event = payload.get("source_event")
        if source_event is not None and not isinstance(source_event, dict):
            return "payload.source_event must be an object"
        return None

    if action == "add":
        positions = payload.get("positions")
        if not isinstance(positions, list) or not positions:
            return "payload.positions must be a non-empty list"
        for idx, position in enumerate(positions):
            if not _is_positive_int(position):
                return f"payload.positions[{idx}] must be a positive integer"

        payload_box = payload.get("box")
        if not _is_positive_int(payload_box):
            return "payload.box must be a positive integer"
        if int(item.get("box")) != payload_box:
            return "payload.box must match item.box"

        if item.get("position") not in positions:
            return "item.position must be included in payload.positions"

        frozen_at = payload.get("frozen_at")
        if not isinstance(frozen_at, str) or not frozen_at.strip():
            return "payload.frozen_at is required"

        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return "payload.fields must be an object"
        return None

    if action == "edit":
        payload_record_id = payload.get("record_id")
        if not _is_positive_int(payload_record_id):
            return "payload.record_id must be a positive integer"
        if int(item.get("record_id")) != payload_record_id:
            return "payload.record_id must match item.record_id"

        fields = payload.get("fields")
        if not isinstance(fields, dict) or not fields:
            return "payload.fields must be a non-empty object"
        return None

    payload_record_id = payload.get("record_id")
    if not _is_positive_int(payload_record_id):
        return "payload.record_id must be a positive integer"
    if int(item.get("record_id")) != payload_record_id:
        return "payload.record_id must match item.record_id"

    payload_position = payload.get("position")
    if not _is_positive_int(payload_position):
        return "payload.position must be a positive integer"
    if int(item.get("position")) != payload_position:
        return "payload.position must match item.position"

    date_str = payload.get("date_str")
    if not isinstance(date_str, str) or not date_str.strip():
        return "payload.date_str is required"

    if action == "move":
        payload_to_position = payload.get("to_position")
        if not _is_positive_int(payload_to_position):
            return "payload.to_position must be a positive integer"
        if int(item.get("to_position")) != payload_to_position:
            return "payload.to_position must match item.to_position"

        source_box = int(item.get("box"))
        payload_to_box = payload.get("to_box")
        target_box = source_box
        if payload_to_box not in (None, ""):
            if not _is_positive_int(payload_to_box):
                return "payload.to_box must be a positive integer"
            target_box = int(payload_to_box)
            item_to_box = item.get("to_box")
            if item_to_box not in (None, "") and int(item_to_box) != payload_to_box:
                return "payload.to_box must match item.to_box"
        if target_box == source_box and payload_to_position == payload_position:
            return "payload.to_position must differ from payload.position"

    return None


def validate_plan_batch(
    *,
    items: List[Dict[str, Any]],
    yaml_path: Optional[str],
    bridge: Any = None,
    run_preflight: bool = True,
) -> Dict[str, Any]:
    """Validate plan items with shared schema and optional preflight checks."""
    schema_errors: List[Dict[str, Any]] = []
    valid_items: List[Dict[str, Any]] = []

    for item in items or []:
        err = validate_plan_item(item)
        if err:
            schema_errors.append(
                {
                    "kind": "schema",
                    "item": item,
                    "error_code": "plan_validation_failed",
                    "message": err,
                }
            )
            continue

        payload_err = _validate_item_payload_schema(item)
        if payload_err:
            schema_errors.append(
                {
                    "kind": "schema",
                    "item": item,
                    "error_code": "plan_validation_failed",
                    "message": payload_err,
                }
            )
        else:
            valid_items.append(item)

    # Cross-item constraint: rollback must be executed alone (no mixing).
    has_rollback = any(str(it.get("action") or "").lower() == "rollback" for it in valid_items)
    if has_rollback and len(valid_items) != 1:
        message = "Rollback must be the only item in a plan (clear other operations first)."
        for item in valid_items:
            schema_errors.append(
                {
                    "kind": "schema",
                    "item": item,
                    "error_code": "plan_validation_failed",
                    "message": message,
                }
            )
        valid_items = []

    preflight_errors: List[Dict[str, Any]] = []
    preflight_report = None
    if run_preflight and valid_items and yaml_path and os.path.isfile(yaml_path):
        try:
            preflight_report = preflight_plan(yaml_path, valid_items, bridge)
        except Exception as exc:
            preflight_errors.append(
                {
                    "kind": "preflight",
                    "item": valid_items[0],
                    "error_code": "plan_preflight_failed",
                    "message": f"Preflight exception: {exc}",
                }
            )
            preflight_report = {
                "ok": False,
                "blocked": True,
                "items": [],
                "stats": {
                    "total": len(valid_items),
                    "ok": 0,
                    "blocked": len(valid_items),
                },
                "summary": f"Preflight exception: {exc}",
            }
        if isinstance(preflight_report, dict):
            for report_item in preflight_report.get("items", []):
                if report_item.get("blocked"):
                    preflight_errors.append(
                        {
                            "kind": "preflight",
                            "item": report_item.get("item") or {},
                            "error_code": report_item.get("error_code") or "plan_preflight_failed",
                            "message": report_item.get("message") or "Preflight validation failed",
                        }
                    )

    errors = schema_errors + preflight_errors
    blocked_items = [_blocked_item_payload(err) for err in errors]

    blocked_by_preflight = {
        id(err.get("item"))
        for err in preflight_errors
        if isinstance(err.get("item"), dict)
    }
    accepted_items = [item for item in valid_items if id(item) not in blocked_by_preflight]

    return {
        "ok": not errors,
        "blocked": bool(errors),
        "errors": errors,
        "blocked_items": blocked_items,
        "valid_items": valid_items,
        "accepted_items": accepted_items,
        "preflight_report": preflight_report,
        "stats": {
            "total": len(items or []),
            "valid": len(valid_items),
            "accepted": len(accepted_items),
            "blocked": len(blocked_items),
        },
    }


def validate_stage_request(
    *,
    existing_items: List[Dict[str, Any]],
    incoming_items: List[Dict[str, Any]],
    yaml_path: Optional[str],
    bridge: Any = None,
    run_preflight: bool = True,
) -> Dict[str, Any]:
    """Validate a staging request as one atomic batch.

    The validation target is always ``existing_items + incoming_items`` so GUI and
    agent staging share the same full validation outcome.
    """
    existing = list(existing_items or [])
    incoming = list(incoming_items or [])
    combined = existing + incoming

    gate = validate_plan_batch(
        items=combined,
        yaml_path=yaml_path,
        bridge=bridge,
        run_preflight=run_preflight,
    )

    if gate.get("blocked"):
        incoming_ids = {id(item) for item in incoming}
        incoming_errors = [
            err
            for err in (gate.get("errors") or [])
            if isinstance(err.get("item"), dict) and id(err.get("item")) in incoming_ids
        ]
        relevant_errors = incoming_errors or list(gate.get("errors") or [])
        blocked_items = [_blocked_item_payload(err) for err in relevant_errors]
        return {
            "ok": False,
            "blocked": True,
            "errors": relevant_errors,
            "blocked_items": blocked_items,
            "accepted_items": [],
            "preflight_report": gate.get("preflight_report"),
            "stats": {
                "existing": len(existing),
                "incoming": len(incoming),
                "total": len(combined),
                "blocked": len(blocked_items),
            },
        }

    return {
        "ok": True,
        "blocked": False,
        "errors": [],
        "blocked_items": [],
        "accepted_items": incoming,
        "preflight_report": gate.get("preflight_report"),
        "stats": {
            "existing": len(existing),
            "incoming": len(incoming),
            "total": len(combined),
            "blocked": 0,
        },
    }
