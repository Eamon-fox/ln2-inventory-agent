"""Agent runtime assembly: LLM provider selection, client creation, agent orchestration."""

import os

from agent.llm_client import (
    DEFAULT_PROVIDER,
    DeepSeekLLMClient,
    ZhipuLLMClient,
    MiniMaxLLMClient,
    PROVIDER_DEFAULTS,
)
from agent.react_agent import ReactAgent
from agent.shell_session import ShellSessionState
from agent.tool_runner import AgentToolRunner
from app_gui.gui_config import DEFAULT_MAX_STEPS, MAX_AGENT_STEPS
from app_gui.i18n import tr
from lib.inventory_paths import assert_allowed_inventory_yaml_path
from lib.tool_api import build_actor_context


def _api_key_setup_hint(provider=None):
    provider_cfg = provider or DEFAULT_PROVIDER
    cfg = PROVIDER_DEFAULTS.get(provider_cfg, PROVIDER_DEFAULTS[DEFAULT_PROVIDER])
    return tr(
        "settings.apiKeyMissing",
        provider=cfg["display_name"],
        help_url=cfg.get("help_url", ""),
    )


class AgentSessionService:
    """Assembles and runs the ReAct agent runtime for one GUI session."""

    def __init__(self, session_id=None):
        self._session_id = session_id
        self._api_keys = {}
        self._shell_state = ShellSessionState()

    def reset_shell_state(self):
        self._shell_state.reset()

    def set_api_keys(self, api_keys):
        """Set per-provider API keys for LLM clients."""
        self._api_keys = api_keys if isinstance(api_keys, dict) else {}

    def _get_api_key(self, provider):
        """Get API key for the given provider."""
        return self._api_keys.get(provider)

    def run_agent_query(
        self,
        yaml_path,
        query,
        model=None,
        max_steps=DEFAULT_MAX_STEPS,
        history=None,
        summary_state=None,
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
            yaml_path = assert_allowed_inventory_yaml_path(yaml_path, must_exist=True)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "inventory_path_not_allowed",
                "message": str(exc),
            }
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
            from app_gui.plan_executor import preflight_plan

            runner = AgentToolRunner(
                yaml_path=yaml_path,
                session_id=self._session_id,
                plan_store=plan_store,
                preflight_fn=preflight_plan,
                tr_func=tr,
                shell_state=self._shell_state,
            )
            if callable(_expose_runner):
                _expose_runner(runner)
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=steps, custom_prompt=str(custom_prompt or ""))
            result = agent.run(
                prompt,
                conversation_history=history,
                on_event=on_event,
                stop_event=stop_event,
                summary_state=summary_state,
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
