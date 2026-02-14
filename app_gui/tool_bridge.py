"""GUI-facing bridge to the unified Tool API."""

import os

from agent.llm_client import (
    DEFAULT_PROVIDER,
    PROVIDER_DEFAULTS,
    DeepSeekLLMClient,
    ZhipuLLMClient,
)
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from app_gui.gui_config import DEFAULT_MAX_STEPS
from lib.tool_api import (
    build_actor_context,
    parse_batch_entries,
    tool_add_entry,
    tool_adjust_box_count,
    tool_batch_thaw,
    tool_collect_timeline,
    tool_edit_entry,
    tool_export_inventory_csv,
    tool_generate_stats,
    tool_list_empty_positions,
    tool_list_backups,
    tool_query_inventory,
    tool_record_thaw,
    tool_rollback,
)


def _api_key_setup_hint(provider=None):
    provider = provider or DEFAULT_PROVIDER
    cfg = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
    return (
        f"{cfg['display_name']} API key is missing.\n"
        f"Set environment variable: {cfg['env_key']}\n\n"
        "Windows: System Properties > Environment Variables\n"
        "macOS/Linux: Add to ~/.bashrc or ~/.zshrc"
    )


class GuiToolBridge:
    """Thin adapter that stamps GUI actor metadata on tool calls."""

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
            actor_type="human",
            channel="gui",
            session_id=self._session_id,
        )

    def query_inventory(self, yaml_path, **filters):
        # Separate structural filters from user field filters
        structural = {}
        field_filters = {}
        for key, value in filters.items():
            if key in ("box", "position"):
                structural[key] = value
            elif value:
                field_filters[key] = value

        return tool_query_inventory(yaml_path=yaml_path, **structural, **field_filters)

    def list_empty_positions(self, yaml_path, box=None):
        return tool_list_empty_positions(yaml_path=yaml_path, box=box)

    def export_inventory_csv(self, yaml_path, output_path):
        return tool_export_inventory_csv(
            yaml_path=yaml_path,
            output_path=output_path,
        )

    def generate_stats(self, yaml_path):
        return tool_generate_stats(yaml_path=yaml_path)

    def collect_timeline(self, yaml_path, days=7, all_history=False):
        return tool_collect_timeline(yaml_path=yaml_path, days=days, all_history=all_history)

    def list_backups(self, yaml_path):
        backups = tool_list_backups(yaml_path)
        return {
            "ok": True,
            "result": {
                "count": len(backups),
                "backups": backups,
            },
        }

    def add_entry(self, yaml_path, **payload):
        return tool_add_entry(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def edit_entry(self, yaml_path, record_id, fields):
        return tool_edit_entry(
            yaml_path=yaml_path,
            record_id=record_id,
            fields=fields,
            actor_context=self._ctx(),
            source="app_gui",
        )

    def record_thaw(self, yaml_path, **payload):
        return tool_record_thaw(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def batch_thaw(self, yaml_path, **payload):
        return tool_batch_thaw(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
        )

    def batch_thaw_from_text(self, yaml_path, entries_text, **payload):
        entries = parse_batch_entries(entries_text)
        return self.batch_thaw(yaml_path=yaml_path, entries=entries, **payload)

    def rollback(self, yaml_path, backup_path=None, source_event=None):
        return tool_rollback(
            yaml_path=yaml_path,
            backup_path=backup_path,
            source_event=source_event,
            actor_context=self._ctx(),
            source="app_gui",
        )

    def adjust_box_count(self, yaml_path, **payload):
        return tool_adjust_box_count(
            yaml_path=yaml_path,
            actor_context=self._ctx(),
            source="app_gui",
            **payload,
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
        provider=None,
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
            runner = AgentToolRunner(
                yaml_path=yaml_path,
                session_id=self._session_id,
                plan_store=plan_store,
            )
            if callable(_expose_runner):
                _expose_runner(runner)
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=steps, custom_prompt=str(custom_prompt or ""))
            result = agent.run(prompt, conversation_history=history, on_event=on_event)
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
