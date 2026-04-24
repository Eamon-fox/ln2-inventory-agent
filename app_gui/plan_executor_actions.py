"""Action helpers for plan executor batch/preflight flows."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app_gui.bridge_write_runner import execute_bridge_write as _execute_bridge_write
from lib import tool_api_write_adapter as _write_adapter
from lib.schema_aliases import coalesce_stored_at_value

from . import plan_executor_layout as _layout
from . import plan_executor_reports as _reports


def _executor_hook(name: str, default):
    from app_gui import plan_executor as _executor

    return getattr(_executor, name, default)


def _run_preflight_tool(
    bridge: object,
    yaml_path: str,
    tool_name: str,
    **payload: object,
) -> Dict[str, object]:
    """Invoke a write tool in execute-shaped preflight mode."""
    return _write_adapter.call_preflight_tool(
        tool_name,
        yaml_path=yaml_path,
        actor_context=getattr(bridge, "_ctx", lambda: None)() or None,
        source="plan_executor.preflight",
        **payload,
    )


def _preflight_add_entry(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate add_entry with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="add_entry",
        box=payload.get("box"),
        positions=payload.get("positions"),
        stored_at=coalesce_stored_at_value(
            stored_at=payload.get("stored_at"),
            frozen_at=payload.get("frozen_at"),
        ),
        fields=payload.get("fields"),
    )


def _preflight_takeout(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate takeout with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="takeout",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
    )


def _preflight_move(bridge: object, yaml_path: str, payload: Dict[str, object]) -> Dict[str, object]:
    """Validate move with the same path as execute mode."""
    return _run_preflight_tool(
        bridge=bridge,
        yaml_path=yaml_path,
        tool_name="move",
        entries=payload.get("entries", []),
        date_str=payload.get("date_str"),
    )


def _run_takeout(
    bridge: object,
    yaml_path: str,
    batch_payload: Dict[str, object],
    mode: str,
    request_backup_path: Optional[str] = None,
) -> Dict[str, object]:
    if mode == "preflight":
        return _executor_hook("_preflight_takeout", _preflight_takeout)(bridge, yaml_path, batch_payload)
    return _execute_bridge_write(
        bridge.takeout,
        yaml_path=yaml_path,
        **batch_payload,
        request_backup_path=request_backup_path,
    )


def _run_move(
    bridge: object,
    yaml_path: str,
    batch_payload: Dict[str, object],
    mode: str,
    request_backup_path: Optional[str] = None,
) -> Dict[str, object]:
    if mode == "preflight":
        return _executor_hook("_preflight_move", _preflight_move)(bridge, yaml_path, batch_payload)
    return _execute_bridge_write(
        bridge.move,
        yaml_path=yaml_path,
        **batch_payload,
        request_backup_path=request_backup_path,
    )


def _execute_move(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    date_str: str,
    mode: str,
    request_backup_path: Optional[str] = None,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute move operations using a single tool call."""
    layout = _layout._load_box_layout(yaml_path)
    try:
        batch_payload = _layout._build_takeout_payload(
            items,
            date_str=date_str,
            layout=layout,
            include_target=True,
        )
    except ValueError as exc:
        message = str(exc)
        return False, [_reports._make_error_item(item, "validation_failed", message) for item in items]

    response = _run_move(
        bridge,
        yaml_path,
        batch_payload,
        mode,
        request_backup_path=request_backup_path,
    )

    return _reports._fanout_batch_response(
        items,
        response,
        fallback_error_code="move_batch_failed",
        fallback_message="Move batch failed",
    )


def _execute_takeout(
    yaml_path: str,
    items: List[Dict[str, object]],
    action_name: str,
    bridge: object,
    date_str: str,
    mode: str,
    request_backup_path: Optional[str] = None,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute takeout operations.

    - Preflight: validate each item individually for precise error reporting.
    - Execute: run as a single batch (no fallback).
    """
    del action_name
    reports: List[Dict[str, object]] = []
    layout = _layout._load_box_layout(yaml_path)

    if mode == "preflight":
        if len(items) > 1:
            try:
                batch_payload = _layout._build_takeout_payload(
                    items,
                    date_str=date_str,
                    layout=layout,
                    include_target=False,
                )
            except ValueError:
                batch_payload = None
            if batch_payload:
                response = _run_takeout(
                    bridge,
                    yaml_path,
                    batch_payload,
                    mode="preflight",
                )
                if response.get("ok"):
                    return _reports._batch_ok_reports(items, response)

        all_ok = True
        for item in items:
            payload = item.get("payload") or {}
            try:
                position = _layout._to_tool_position(
                    payload.get("position"),
                    layout,
                    field_name="from_slot.position",
                )
            except ValueError as exc:
                reports.append(_reports._make_error_item(item, "validation_failed", str(exc)))
                all_ok = False
                continue
            single_payload = {
                "entries": [
                    {
                        "record_id": payload.get("record_id"),
                        "from": {
                            "box": item.get("box"),
                            "position": position,
                        },
                    }
                ],
                "date_str": payload.get("date_str", date_str),
            }
            response = _executor_hook("_preflight_takeout", _preflight_takeout)(
                bridge=bridge,
                yaml_path=yaml_path,
                payload=single_payload,
            )
            if not _reports._append_item_report(
                reports,
                item=item,
                response=response,
                fallback_error_code="takeout_failed",
                fallback_message="Operation failed",
            ):
                all_ok = False
        return all_ok, reports

    try:
        batch_payload = _layout._build_takeout_payload(
            items,
            date_str=date_str,
            layout=layout,
            include_target=False,
        )
    except ValueError as exc:
        message = str(exc)
        return False, [_reports._make_error_item(item, "validation_failed", message) for item in items]

    response = _run_takeout(
        bridge,
        yaml_path,
        batch_payload,
        mode="execute",
        request_backup_path=request_backup_path,
    )

    return _reports._fanout_batch_response(
        items,
        response,
        fallback_error_code="takeout_batch_failed",
        fallback_message="Batch operation failed",
    )


def _execute_batch_add(
    yaml_path: str,
    items: List[Dict[str, object]],
    bridge: object,
    mode: str,
    request_backup_path: Optional[str] = None,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Execute add operations as a single batch."""
    if not items:
        return True, []

    layout = _layout._load_box_layout(yaml_path)

    add_claimed: set[tuple[int, int]] = set()
    pre_blocked: Dict[int, str] = {}
    tool_payloads: List[Dict[str, object]] = []

    for item in items:
        payload = item.get("payload") or {}
        box = int(payload.get("box") or item.get("box") or 0)
        positions = payload.get("positions") or []

        conflict = False
        for pos in positions:
            key = (box, int(pos))
            if key in add_claimed:
                pre_blocked[id(item)] = "Position conflict (duplicate target in the same batch)"
                conflict = True
                break
            add_claimed.add(key)
        if conflict:
            tool_payloads.append({})
            continue

        try:
            tool_payload = _layout._build_add_tool_payload(dict(payload), layout)
        except ValueError as exc:
            pre_blocked[id(item)] = str(exc)
            tool_payloads.append({})
            continue
        tool_payloads.append(tool_payload)

    if len(pre_blocked) == len(items):
        reports = []
        for item in items:
            message = pre_blocked.get(id(item), "Validation failed")
            reports.append(_reports._make_error_item(item, "validation_failed", message))
        return False, reports

    if mode == "preflight":
        return _preflight_batch_add(
            items=items,
            tool_payloads=tool_payloads,
            pre_blocked=pre_blocked,
            bridge=bridge,
            yaml_path=yaml_path,
        )

    batch_entries = []
    valid_items = []
    for item, tool_payload in zip(items, tool_payloads):
        if id(item) in pre_blocked:
            continue
        batch_entries.append(
            {
                "box": tool_payload.get("box"),
                "positions": tool_payload.get("positions"),
                "stored_at": coalesce_stored_at_value(
                    stored_at=tool_payload.get("stored_at"),
                    frozen_at=tool_payload.get("frozen_at"),
                ),
                "fields": tool_payload.get("fields"),
            }
        )
        valid_items.append(item)

    actor_context = getattr(bridge, "_ctx", lambda: None)() or {}
    response = _write_adapter.batch_add_entries(
        yaml_path=yaml_path,
        entries=batch_entries,
        execution_mode="execute",
        actor_context=actor_context,
        source="plan_executor.execute",
        request_backup_path=request_backup_path,
        backup_event_source="plan_executor.execute",
    )

    reports: List[Dict[str, object]] = []
    if isinstance(response, dict) and response.get("ok"):
        return _reports._fanout_with_preblocked_items(items, pre_blocked, response)

    _, batch_reports = _reports._fanout_batch_response(
        valid_items,
        response,
        fallback_error_code="add_batch_failed",
        fallback_message="Batch add failed",
    )

    batch_iter = iter(batch_reports)
    for item in items:
        if id(item) in pre_blocked:
            reports.append(_reports._make_preblocked_item_report(item, pre_blocked[id(item)]))
        else:
            reports.append(next(batch_iter))

    return False, reports


def _preflight_batch_add(
    items: List[Dict[str, object]],
    tool_payloads: List[Dict[str, object]],
    pre_blocked: Dict[int, str],
    bridge: object,
    yaml_path: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    """Preflight add operations with a batch fast path plus per-item fallback."""
    valid_entries: List[Dict[str, object]] = []
    valid_items: List[Dict[str, object]] = []
    for item, tool_payload in zip(items, tool_payloads):
        if id(item) in pre_blocked:
            continue
        valid_entries.append(
            {
                "box": tool_payload.get("box"),
                "positions": tool_payload.get("positions"),
                "stored_at": coalesce_stored_at_value(
                    stored_at=tool_payload.get("stored_at"),
                    frozen_at=tool_payload.get("frozen_at"),
                ),
                "fields": tool_payload.get("fields"),
            }
        )
        valid_items.append(item)

    if len(valid_items) > 1:
        actor_context = getattr(bridge, "_ctx", lambda: None)() or None
        batch_response = _write_adapter.batch_add_entries(
            yaml_path=yaml_path,
            entries=valid_entries,
            execution_mode="execute",
            actor_context=actor_context,
            source="plan_executor.preflight",
            auto_backup=False,
        )
        if batch_response.get("ok"):
            return _reports._fanout_with_preblocked_items(items, pre_blocked, batch_response)

    reports: List[Dict[str, object]] = []
    all_ok = True

    for item, tool_payload in zip(items, tool_payloads):
        if id(item) in pre_blocked:
            reports.append(_reports._make_preblocked_item_report(item, pre_blocked[id(item)]))
            all_ok = False
            continue

        response = _executor_hook("_preflight_add_entry", _preflight_add_entry)(bridge, yaml_path, tool_payload)
        if not _reports._append_item_report(
            reports,
            item=item,
            response=response,
            fallback_error_code="add_failed",
            fallback_message="Add failed",
        ):
            all_ok = False

    return all_ok, reports
