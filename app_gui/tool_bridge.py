"""GUI-facing bridge to the unified Tool API."""

from copy import deepcopy
import os

from agent.llm_client import DEFAULT_PROVIDER, DeepSeekLLMClient, ZhipuLLMClient, MiniMaxLLMClient, PROVIDER_DEFAULTS
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from app_gui.gui_config import DEFAULT_MAX_STEPS, MAX_AGENT_STEPS
from app_gui.i18n import tr
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib import tool_api_write_adapter as _write_adapter
from lib.tool_registry import GUI_BRIDGE_READ, GUI_BRIDGE_WRITE, iter_gui_bridge_descriptors
from lib.tool_api import (
    build_actor_context,
    tool_collect_timeline,
    tool_export_inventory_csv,
    tool_generate_stats,
    tool_list_audit_timeline,
    tool_list_empty_positions,
)


def _api_key_setup_hint(provider=None):
    provider_cfg = provider or DEFAULT_PROVIDER
    cfg = PROVIDER_DEFAULTS.get(provider_cfg, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
    return tr(
        "settings.apiKeyMissing",
        provider=cfg["display_name"],
        help_url=cfg.get("help_url", ""),
    )


class GuiToolBridge:
    """Thin adapter that stamps GUI audit context on tool calls."""

    def __init__(self, session_id=None):
        self._session_id = session_id
        self._api_keys = {}

    def set_api_keys(self, api_keys):
        """Set per-provider API keys for LLM clients."""
        self._api_keys = api_keys if isinstance(api_keys, dict) else {}

    def _get_api_key(self, provider):
        """Get API key for the given provider."""
        return self._api_keys.get(provider)

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
        tool_fn = globals().get(str(tool_api_attr or ""))
        if callable(tool_fn):
            return tool_fn
        raise AttributeError(f"Unknown tool bridge target: {tool_api_attr}")

    def _call_registry_read_tool(self, *, yaml_path, bridge_spec, payload):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)

        tool_fn = self._registry_tool_callable(bridge_spec.tool_api_attr)
        call_kwargs = dict(payload or {})
        call_kwargs.update(deepcopy(dict(bridge_spec.fixed_kwargs or {})))
        return tool_fn(
            yaml_path=yaml_path,
            **call_kwargs,
        )

    def _call_registry_write_tool(self, *, yaml_path, bridge_spec, payload):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)

        call_kwargs = dict(payload or {})
        call_kwargs.update(deepcopy(dict(bridge_spec.fixed_kwargs or {})))
        tool_fn = getattr(_write_adapter, bridge_spec.method_name, None)
        if callable(tool_fn):
            try:
                return tool_fn(
                    yaml_path=yaml_path,
                    actor_context=self._ctx(),
                    source="app_gui",
                    backup_event_source="app_gui",
                    **call_kwargs,
                )
            except Exception as exc:
                return self._backup_create_failed(exc)
        tool_fn = self._registry_tool_callable(bridge_spec.tool_api_attr)
        return tool_fn(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **call_kwargs,
        )

    def export_inventory_csv(self, yaml_path, output_path):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)
        return tool_export_inventory_csv(
            yaml_path=yaml_path,
            output_path=output_path,
        )

    def collect_timeline(self, yaml_path, days=7, all_history=False):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)
        return tool_collect_timeline(yaml_path=yaml_path, days=days, all_history=all_history)

    def adjust_box_count(self, yaml_path, **payload):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)
        try:
            return _write_adapter.adjust_box_count(
                yaml_path=yaml_path,
                actor_context=self._ctx(),
                source="app_gui",
                backup_event_source="app_gui",
                **payload,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)

    def set_box_tag(
        self,
        yaml_path,
        box,
        tag="",
        execution_mode=None,
        dry_run=False,
        auto_backup=True,
        request_backup_path=None,
    ):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)
        try:
            return _write_adapter.set_box_tag(
                yaml_path=yaml_path,
                box=box,
                tag=tag,
                execution_mode=execution_mode,
                dry_run=bool(dry_run),
                auto_backup=auto_backup,
                request_backup_path=request_backup_path,
                actor_context=self._ctx(),
                source="app_gui",
                backup_event_source="app_gui",
            )
        except Exception as exc:
            return self._backup_create_failed(exc)

    def run_agent_query(
        self,
        yaml_path,
        query,
        model=None,
        max_steps=DEFAULT_MAX_STEPS,
        history=None,
        on_event=None,
        plan_store=None,
        thinking_enabled=True,
        custom_prompt="",
        _expose_runner=None,
        _expose_llm=None,
        provider=None,
        stop_event=None,
    ):
        try:
            yaml_path = self._guard_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return self._path_validation_failed(exc)
        prompt = str(query or "").strip()
        if not prompt:
            return {
                "ok": False,
                "error_code": "empty_query",
                "message": "Please input a natural-language request.",
                "result": None,
            }

        try:
            steps = int(max_steps)
        except Exception:
            return {
                "ok": False,
                "error_code": "invalid_max_steps",
                "message": f"max_steps must be an integer: {max_steps}",
                "result": None,
            }
        if steps < 1 or steps > MAX_AGENT_STEPS:
            return {
                "ok": False,
                "error_code": "invalid_max_steps",
                "message": f"max_steps must be between 1 and {MAX_AGENT_STEPS}",
                "result": None,
            }

        provider = (provider or "").strip().lower() or DEFAULT_PROVIDER
        if provider not in PROVIDER_DEFAULTS:
            provider = DEFAULT_PROVIDER
        provider_cfg = PROVIDER_DEFAULTS[provider]
        use_thinking = bool(thinking_enabled)
        chosen_model = (model or "").strip() or os.environ.get(f"{provider.upper()}_MODEL") or provider_cfg["model"]
        api_key = self._get_api_key(provider)

        try:
            if provider == "zhipu":
                llm = ZhipuLLMClient(model=chosen_model, api_key=api_key, thinking_enabled=use_thinking)
            elif provider == "minimax":
                llm = MiniMaxLLMClient(model=chosen_model, api_key=api_key, thinking_enabled=use_thinking)
            else:
                llm = DeepSeekLLMClient(model=chosen_model, api_key=api_key, thinking_enabled=use_thinking)
            if callable(_expose_llm):
                _expose_llm(llm)
            runner = AgentToolRunner(
                yaml_path=yaml_path,
                session_id=self._session_id,
                plan_store=plan_store,
            )
            if callable(_expose_runner):
                _expose_runner(runner)
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=steps, custom_prompt=str(custom_prompt or ""))
            result = agent.run(
                prompt,
                conversation_history=history,
                on_event=on_event,
                stop_event=stop_event,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "API_KEY is required" in message:
                return {
                    "ok": False,
                    "error_code": "api_key_required",
                    "message": _api_key_setup_hint(provider),
                    "result": None,
                }
            return {
                "ok": False,
                "error_code": "agent_runtime_failed",
                "message": message,
                "result": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "agent_runtime_failed",
                "message": str(exc),
                "result": None,
            }

        if not isinstance(result, dict):
            return {
                "ok": False,
                "error_code": "invalid_agent_result",
                "message": "Agent returned non-dict result payload.",
                "result": None,
            }

        if "final" not in result:
            return {
                "ok": False,
                "error_code": "invalid_agent_result",
                "message": "Agent result is missing `final`.",
                "result": None,
            }

        return {
            "ok": bool(result.get("ok")),
            "result": result,
            "mode": provider,
            "model": chosen_model,
        }


def _install_registry_bridge_methods():
    for descriptor in iter_gui_bridge_descriptors():
        bridge_spec = descriptor.gui_bridge
        if bridge_spec is None:
            continue

        def _bridge_method(self, yaml_path, *args, _bridge_spec=bridge_spec, **kwargs):
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

