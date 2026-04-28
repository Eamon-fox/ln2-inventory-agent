"""GUI-facing bridge to the unified Tool API."""

from copy import deepcopy

from app_gui.i18n import tr
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib import tool_api_write_adapter as _write_adapter
from lib.yaml_ops import clear_read_snapshot, current_read_snapshot_id, read_snapshot_context
from lib.tool_registry import (
    GUI_BRIDGE_READ,
    GUI_BRIDGE_WRITE,
    iter_gui_bridge_descriptors,
    resolve_tool_api_callable,
)
from lib.tool_api import build_actor_context

class GuiToolBridge:
    """Thin adapter that stamps GUI audit context on tool calls."""

    def __init__(self, session_id=None):
        self._session_id = session_id

    def _ctx(self):
        return build_actor_context(
            session_id=self._session_id,
        )

    @staticmethod
    def _path_validation_failed(exc):
        return {
            "ok": False,
            "error_code": "inventory_path_not_allowed",
            "message": str(exc),
        }

    @staticmethod
    def _guard_yaml_path(yaml_path, *, must_exist=True):
        return assert_allowed_inventory_yaml_path(yaml_path, must_exist=must_exist)

    @staticmethod
    def _backup_create_failed(exc):
        error_code = str(getattr(exc, "code", "") or "backup_create_failed")
        message = str(getattr(exc, "message", "") or f"Failed to create request backup: {exc}")
        payload = {
            "ok": False,
            "error_code": error_code,
            "message": message,
        }
        resolved_path = str(getattr(exc, "resolved_path", "") or "").strip()
        if resolved_path:
            payload["resolved_path"] = resolved_path
        return payload

    @staticmethod
    def _bind_registry_bridge_payload(bridge_spec, args, kwargs):
        method_name = str(bridge_spec.method_name or "tool")
        payload = {}
        extra_args = tuple(args or ())
        positional_payload_args = tuple(bridge_spec.positional_payload_args or ())
        if len(extra_args) > len(positional_payload_args):
            raise TypeError(f"{method_name}() received too many positional arguments")

        for field_name, value in zip(positional_payload_args, extra_args):
            payload[field_name] = value

        for field_name, value in dict(kwargs or {}).items():
            if field_name in payload:
                raise TypeError(
                    f"{method_name}() got multiple values for argument '{field_name}'"
                )
            payload[field_name] = value

        for field_name, default_value in dict(bridge_spec.defaults or {}).items():
            payload.setdefault(field_name, deepcopy(default_value))

        missing = [
            field_name
            for field_name in tuple(bridge_spec.required_payload_args or ())
            if field_name not in payload
        ]
        if missing:
            if len(missing) == 1:
                raise TypeError(
                    f"{method_name}() missing 1 required argument: '{missing[0]}'"
                )
            joined = ", ".join(repr(name) for name in missing)
            raise TypeError(
                f"{method_name}() missing {len(missing)} required arguments: {joined}"
            )

        return payload

    @staticmethod
    def _registry_tool_callable(tool_api_attr):
        return resolve_tool_api_callable(str(tool_api_attr or ""))

    def _call_registry_read_tool(self, *, yaml_path, bridge_spec, payload):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)

        tool_fn = self._registry_tool_callable(bridge_spec.tool_api_attr)
        call_kwargs = dict(payload or {})
        call_kwargs.update(deepcopy(dict(bridge_spec.fixed_kwargs or {})))
        if current_read_snapshot_id():
            return tool_fn(
                yaml_path=yaml_path,
                **call_kwargs,
            )

        snapshot_id = f"gui-read-{id(self)}"
        try:
            with read_snapshot_context(snapshot_id):
                return tool_fn(
                    yaml_path=yaml_path,
                    **call_kwargs,
                )
        finally:
            clear_read_snapshot(snapshot_id)

    def _call_registry_write_tool(self, *, yaml_path, descriptor, bridge_spec, payload):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)

        call_kwargs = dict(payload or {})
        dry_run = bool(call_kwargs.pop("dry_run", False))
        execution_mode = call_kwargs.pop("execution_mode", None)
        request_backup_path = call_kwargs.pop("request_backup_path", None)
        call_kwargs.update(deepcopy(dict(bridge_spec.fixed_kwargs or {})))
        try:
            return _write_adapter.invoke_write_tool(
                descriptor.name,
                yaml_path=yaml_path,
                actor_context=self._ctx(),
                source="app_gui",
                dry_run=dry_run,
                execution_mode=execution_mode,
                request_backup_path=request_backup_path,
                backup_event_source="app_gui",
                payload=call_kwargs,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)


def _install_registry_bridge_methods():
    for descriptor in iter_gui_bridge_descriptors():
        bridge_spec = descriptor.gui_bridge
        if bridge_spec is None:
            continue

        def _bridge_method(
            self,
            yaml_path,
            *args,
            _descriptor=descriptor,
            _bridge_spec=bridge_spec,
            **kwargs,
        ):
            # Keep yaml_path in the generated Python signature. Payload binding
            # only handles tool-specific arguments so keyword yaml_path calls from
            # plan_executor and direct GUI actions share one contract.
            payload = self._bind_registry_bridge_payload(
                _bridge_spec,
                args,
                kwargs,
            )
            if _bridge_spec.strategy == GUI_BRIDGE_READ:
                return self._call_registry_read_tool(
                    yaml_path=yaml_path,
                    bridge_spec=_bridge_spec,
                    payload=payload,
                )
            if _bridge_spec.strategy == GUI_BRIDGE_WRITE:
                return self._call_registry_write_tool(
                    yaml_path=yaml_path,
                    descriptor=_descriptor,
                    bridge_spec=_bridge_spec,
                    payload=payload,
                )
            raise ValueError(
                f"Unsupported GUI bridge strategy: {_bridge_spec.strategy}"
            )

        _bridge_method.__name__ = bridge_spec.method_name
        _bridge_method.__qualname__ = f"GuiToolBridge.{bridge_spec.method_name}"
        _bridge_method.__doc__ = (
            f"Registry-backed GUI bridge method for `{descriptor.name}`."
        )
        setattr(GuiToolBridge, bridge_spec.method_name, _bridge_method)


_install_registry_bridge_methods()

