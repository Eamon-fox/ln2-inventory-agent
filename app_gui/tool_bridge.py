"""GUI-facing bridge to the unified Tool API."""

import os

from agent.llm_client import DEFAULT_PROVIDER, DeepSeekLLMClient, ZhipuLLMClient, PROVIDER_DEFAULTS
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from app_gui.gui_config import DEFAULT_MAX_STEPS
from app_gui.i18n import tr
from lib.tool_api import (
    build_actor_context,
    tool_add_entry,
    tool_adjust_box_count,
    tool_collect_timeline,
    tool_edit_entry,
    tool_export_inventory_csv,
    tool_generate_stats,
    tool_list_audit_timeline,
    tool_list_empty_positions,
    tool_move,
    tool_rollback,
    tool_set_box_tag,
    tool_takeout,
)
from lib.tool_api_write_validation import resolve_request_backup_path


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

    def _resolve_request_backup_path(
        self,
        *,
        yaml_path,
        execution_mode=None,
        dry_run=False,
        request_backup_path=None,
        backup_event_source="app_gui",
    ):
        return resolve_request_backup_path(
            yaml_path=yaml_path,
            execution_mode=execution_mode,
            dry_run=dry_run,
            request_backup_path=request_backup_path,
            backup_event_source=backup_event_source,
        )

    @staticmethod
    def _backup_create_failed(exc):
        return {
            "ok": False,
            "error_code": "backup_create_failed",
            "message": f"Failed to create request backup: {exc}",
        }

    def list_empty_positions(self, yaml_path, box=None):
        return tool_list_empty_positions(yaml_path=yaml_path, box=box)

    def export_inventory_csv(self, yaml_path, output_path):
        return tool_export_inventory_csv(
            yaml_path=yaml_path,
            output_path=output_path,
        )

    def generate_stats(self, yaml_path, box=None, include_inactive=False):
        return tool_generate_stats(
            yaml_path=yaml_path,
            box=box,
            include_inactive=include_inactive,
        )

    def collect_timeline(self, yaml_path, days=7, all_history=False):
        return tool_collect_timeline(yaml_path=yaml_path, days=days, all_history=all_history)

    def list_audit_timeline(
        self,
        yaml_path,
        limit=50,
        offset=0,
        action_filter=None,
        status_filter=None,
        start_date=None,
        end_date=None,
    ):
        return tool_list_audit_timeline(
            yaml_path=yaml_path,
            limit=limit,
            offset=offset,
            action_filter=action_filter,
            status_filter=status_filter,
            start_date=start_date,
            end_date=end_date,
        )

    def add_entry(self, yaml_path, **payload):
        execution_mode = payload.get("execution_mode")
        dry_run = bool(payload.get("dry_run", False))
        request_backup_path = payload.pop("request_backup_path", None)
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=dry_run,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            payload["request_backup_path"] = resolved_backup
            payload["auto_backup"] = False
        return tool_add_entry(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def edit_entry(
        self,
        yaml_path,
        record_id,
        fields,
        execution_mode=None,
        auto_backup=True,
        request_backup_path=None,
    ):
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=False,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            request_backup_path = resolved_backup
            auto_backup = False
        return tool_edit_entry(
            yaml_path=yaml_path,
            record_id=record_id,
            fields=fields,
            execution_mode=execution_mode,
            actor_context=self._ctx(),
            source="app_gui",
            auto_backup=auto_backup,
            request_backup_path=request_backup_path,
        )

    def takeout(self, yaml_path, **payload):
        execution_mode = payload.get("execution_mode")
        dry_run = bool(payload.get("dry_run", False))
        request_backup_path = payload.pop("request_backup_path", None)
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=dry_run,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            payload["request_backup_path"] = resolved_backup
            payload["auto_backup"] = False
        return tool_takeout(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def move(self, yaml_path, **payload):
        execution_mode = payload.get("execution_mode")
        dry_run = bool(payload.get("dry_run", False))
        request_backup_path = payload.pop("request_backup_path", None)
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=dry_run,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            payload["request_backup_path"] = resolved_backup
            payload["auto_backup"] = False
        return tool_move(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def rollback(
        self,
        yaml_path,
        backup_path=None,
        source_event=None,
        execution_mode=None,
        request_backup_path=None,
    ):
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=False,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        return tool_rollback(
            yaml_path=yaml_path,
            backup_path=backup_path,
            source_event=source_event,
            execution_mode=execution_mode,
            actor_context=self._ctx(),
            source="app_gui",
            auto_backup=False if resolved_backup else True,
            request_backup_path=resolved_backup,
        )

    def adjust_box_count(self, yaml_path, **payload):
        execution_mode = payload.get("execution_mode")
        dry_run = bool(payload.get("dry_run", False))
        request_backup_path = payload.pop("request_backup_path", None)
        try:
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=dry_run,
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            payload["request_backup_path"] = resolved_backup
            payload["auto_backup"] = False
        return tool_adjust_box_count(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

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
            resolved_backup = self._resolve_request_backup_path(
                yaml_path=yaml_path,
                execution_mode=execution_mode,
                dry_run=bool(dry_run),
                request_backup_path=request_backup_path,
            )
        except Exception as exc:
            return self._backup_create_failed(exc)
        if resolved_backup:
            request_backup_path = resolved_backup
            auto_backup = False
        return tool_set_box_tag(
            yaml_path=yaml_path,
            box=box,
            tag=tag,
            dry_run=bool(dry_run),
            execution_mode=execution_mode,
            actor_context=self._ctx(),
            source="app_gui",
            auto_backup=auto_backup,
            request_backup_path=request_backup_path,
        )

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
        if steps < 1 or steps > 20:
            return {
                "ok": False,
                "error_code": "invalid_max_steps",
                "message": "max_steps must be between 1 and 20",
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

