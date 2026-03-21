"""Shared helpers for executing GUI bridge write calls."""

from typing import Callable, Dict, Optional

from lib import tool_api_write_adapter as _write_adapter


def execute_bridge_write(
    write_fn: Callable[..., Dict[str, object]],
    *,
    yaml_path: str,
    request_backup_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    **payload: object,
) -> Dict[str, object]:
    effective_execution_mode = str(execution_mode or "execute")
    call_kwargs = dict(payload)
    call_kwargs["execution_mode"] = effective_execution_mode
    if request_backup_path is not None:
        call_kwargs["request_backup_path"] = request_backup_path
    response = write_fn(
        yaml_path=yaml_path,
        **call_kwargs,
    )
    return _write_adapter.attach_request_backup(
        response,
        request_backup_path,
    )


def execute_bridge_rollback(
    bridge: object,
    *,
    yaml_path: str,
    backup_path=None,
    request_backup_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
    source_event: Optional[dict] = None,
) -> Dict[str, object]:
    rollback_fn = getattr(bridge, "rollback", None)
    if not callable(rollback_fn):
        return {
            "ok": False,
            "error_code": "bridge_no_rollback",
            "message": "Bridge does not provide rollback().",
        }

    rollback_kwargs = {
        "yaml_path": yaml_path,
        "backup_path": backup_path,
        "execution_mode": str(execution_mode or "execute"),
    }
    if request_backup_path is not None:
        rollback_kwargs["request_backup_path"] = request_backup_path
    if isinstance(source_event, dict) and source_event:
        rollback_kwargs["source_event"] = dict(source_event)

    try:
        return execute_bridge_write(
            rollback_fn,
            **rollback_kwargs,
        )
    except TypeError:
        fallback_kwargs = dict(rollback_kwargs)
        fallback_kwargs.pop("request_backup_path", None)
        response = rollback_fn(**fallback_kwargs)
        return _write_adapter.attach_request_backup(
            response,
            request_backup_path,
        )

