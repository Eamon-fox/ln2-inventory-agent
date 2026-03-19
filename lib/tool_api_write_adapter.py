"""Shared caller-side adapter for write-tool invocation.

This module centralizes the protocol details that caller layers must agree on:

- execute/preflight kwarg preparation
- request-level backup resolution
- successful response backup echoing
- internal-position -> tool/display-position conversion
- lazy resolution of concrete ``lib.tool_api`` write entrypoints
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .position_fmt import pos_to_display
from .tool_api_write_validation import resolve_request_backup_path


_TOOL_ATTRS: Dict[str, str] = {
    "add_entry": "tool_add_entry",
    "edit_entry": "tool_edit_entry",
    "takeout": "tool_takeout",
    "move": "tool_move",
    "rollback": "tool_rollback",
    "manage_boxes": "tool_manage_boxes",
    "set_box_tag": "tool_set_box_tag",
    "batch_add_entries": "tool_batch_add_entries",
}


def prepare_write_tool_kwargs(
    *,
    yaml_path: str,
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Return caller-side tool kwargs plus the resolved request backup path."""

    dry_run_flag = bool(dry_run)
    normalized_mode = str(execution_mode or "").strip() or None
    if normalized_mode is None:
        if dry_run_flag:
            normalized_mode = "preflight"
        elif default_execute:
            normalized_mode = "execute"

    tool_kwargs: Dict[str, Any] = {"dry_run": dry_run_flag}
    if normalized_mode is not None:
        tool_kwargs["execution_mode"] = normalized_mode

    resolved_backup = resolve_request_backup_path(
        yaml_path=yaml_path,
        execution_mode=normalized_mode,
        dry_run=dry_run_flag,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source,
    )
    if resolved_backup:
        tool_kwargs["request_backup_path"] = resolved_backup
        tool_kwargs["auto_backup"] = False
    return tool_kwargs, resolved_backup


def attach_request_backup(
    response: Dict[str, Any],
    request_backup_path: Optional[str],
) -> Dict[str, Any]:
    if not request_backup_path or not isinstance(response, dict):
        return response
    if not response.get("ok"):
        return response
    patched = dict(response)
    patched["backup_path"] = request_backup_path
    return patched


def to_tool_position(value: object, layout: Dict[str, object], *, field_name: str = "position") -> str:
    """Convert one internal position into the tool-facing display value."""

    if value in (None, "") or isinstance(value, bool):
        raise ValueError(f"{field_name} is required")
    try:
        return pos_to_display(int(value), layout)
    except Exception as exc:
        raise ValueError(f"{field_name} is invalid: {value}") from exc


def to_tool_positions(
    values: object,
    layout: Dict[str, object],
    *,
    field_name: str = "positions",
) -> List[str]:
    """Convert one-or-many internal positions into tool-facing display values."""

    if values in (None, ""):
        raise ValueError(f"{field_name} is required")
    if isinstance(values, bool):
        raise ValueError(f"{field_name} is invalid: {values}")
    if isinstance(values, (list, tuple, set)):
        converted: List[str] = []
        for idx, value in enumerate(values):
            converted.append(to_tool_position(value, layout, field_name=f"{field_name}[{idx}]"))
        return converted
    return [to_tool_position(values, layout, field_name=field_name)]


def _load_tool_api():
    from . import tool_api

    return tool_api


def _resolve_tool(tool_name: str) -> Callable[..., Dict[str, Any]]:
    attr_name = _TOOL_ATTRS.get(str(tool_name or "").strip())
    if not attr_name:
        raise ValueError(f"Unknown write tool: {tool_name}")
    tool_api = _load_tool_api()
    tool_fn = getattr(tool_api, attr_name, None)
    if not callable(tool_fn):
        raise RuntimeError(f"Failed to resolve {attr_name}")
    return tool_fn


def _resolve_actor_context(actor_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if actor_context:
        return actor_context
    tool_api = _load_tool_api()
    build_actor_context = getattr(tool_api, "build_actor_context", None)
    if not callable(build_actor_context):
        raise RuntimeError("Failed to resolve build_actor_context")
    return build_actor_context()


def _invoke_with_backup(
    tool_name: str,
    *,
    yaml_path: str,
    actor_context: Optional[Dict[str, Any]],
    source: str,
    request_backup_path: Optional[str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    tool_fn = _resolve_tool(tool_name)
    response = tool_fn(
        yaml_path=yaml_path,
        actor_context=_resolve_actor_context(actor_context),
        source=source,
        **payload,
    )
    return attach_request_backup(response, request_backup_path)


def call_preflight_tool(
    tool_name: str,
    *,
    yaml_path: str,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "plan_executor.preflight",
    **payload: Any,
) -> Dict[str, Any]:
    """Invoke a write tool in execute-shaped preflight mode."""

    merged_payload = {
        "dry_run": False,
        "execution_mode": "execute",
        "auto_backup": False,
    }
    merged_payload.update(payload)
    return _invoke_with_backup(
        tool_name,
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=None,
        payload=merged_payload,
    )


def add_entry(
    *,
    yaml_path: str,
    box: Any,
    positions: Any,
    stored_at: Optional[str] = None,
    frozen_at: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "box": box,
        "positions": positions,
        "fields": fields,
    }
    if stored_at is not None:
        payload["stored_at"] = stored_at
    if frozen_at is not None:
        payload["frozen_at"] = frozen_at
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "add_entry",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def edit_entry(
    *,
    yaml_path: str,
    record_id: Any,
    fields: Dict[str, Any],
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "record_id": record_id,
        "fields": fields,
    }
    if "auto_backup" not in tool_kwargs:
        payload["auto_backup"] = auto_backup
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "edit_entry",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def takeout(
    *,
    yaml_path: str,
    entries: Iterable[Dict[str, Any]],
    date_str: Optional[str],
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "entries": entries,
        "date_str": date_str,
    }
    if "auto_backup" not in tool_kwargs:
        payload["auto_backup"] = auto_backup
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "takeout",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def move(
    *,
    yaml_path: str,
    entries: Iterable[Dict[str, Any]],
    date_str: Optional[str],
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "entries": entries,
        "date_str": date_str,
    }
    if "auto_backup" not in tool_kwargs:
        payload["auto_backup"] = auto_backup
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "move",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def rollback(
    *,
    yaml_path: str,
    backup_path: Optional[str] = None,
    source_event: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "backup_path": backup_path,
        "source_event": source_event,
    }
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "rollback",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def manage_boxes(
    *,
    yaml_path: str,
    operation: str,
    count: int = 1,
    box: Optional[int] = None,
    renumber_mode: Optional[str] = None,
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "operation": operation,
        "count": count,
        "box": box,
        "renumber_mode": renumber_mode,
    }
    if "auto_backup" not in tool_kwargs:
        payload["auto_backup"] = auto_backup
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "manage_boxes",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def set_box_tag(
    *,
    yaml_path: str,
    box: int,
    tag: str = "",
    dry_run: bool = False,
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    tool_kwargs, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=dry_run,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "box": box,
        "tag": tag,
    }
    if "auto_backup" not in tool_kwargs:
        payload["auto_backup"] = auto_backup
    payload.update(tool_kwargs)
    return _invoke_with_backup(
        "set_box_tag",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )


def batch_add_entries(
    *,
    yaml_path: str,
    entries: List[Dict[str, Any]],
    execution_mode: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
    source: str = "tool_api",
    auto_backup: bool = True,
    request_backup_path: Optional[str] = None,
    backup_event_source: Optional[str] = None,
    default_execute: bool = False,
) -> Dict[str, Any]:
    _, resolved_backup = prepare_write_tool_kwargs(
        yaml_path=yaml_path,
        dry_run=False,
        execution_mode=execution_mode,
        request_backup_path=request_backup_path,
        backup_event_source=backup_event_source or source,
        default_execute=default_execute,
    )
    payload: Dict[str, Any] = {
        "entries": entries,
        "auto_backup": False if resolved_backup else auto_backup,
    }
    if execution_mode is not None:
        payload["execution_mode"] = execution_mode
    elif default_execute:
        payload["execution_mode"] = "execute"
    if resolved_backup:
        payload["request_backup_path"] = resolved_backup
    elif request_backup_path:
        payload["request_backup_path"] = request_backup_path
    return _invoke_with_backup(
        "batch_add_entries",
        yaml_path=yaml_path,
        actor_context=actor_context,
        source=source,
        request_backup_path=resolved_backup or request_backup_path,
        payload=payload,
    )
