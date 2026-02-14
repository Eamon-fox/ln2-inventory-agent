"""GUI-facing bridge to the unified Tool API."""

import os

from agent.llm_client import DeepSeekLLMClient
from agent.react_agent import ReactAgent
from agent.tool_runner import AgentToolRunner
from app_gui.gui_config import DEFAULT_CONFIG_FILE, DEFAULT_MAX_STEPS
from app_gui.i18n import tr
from lib.tool_api import (
    build_actor_context,
    parse_batch_entries,
    tool_add_entry,
    tool_batch_thaw,
    tool_collect_timeline,
    tool_edit_entry,
    tool_generate_stats,
    tool_list_empty_positions,
    tool_list_backups,
    tool_query_inventory,
    tool_record_thaw,
    tool_rollback,
)


def _api_key_setup_hint():
    return tr("ai.apiKeyMissing", config_file=DEFAULT_CONFIG_FILE)


class GuiToolBridge:
    """Thin adapter that stamps GUI actor metadata on tool calls."""

    def __init__(self, session_id=None):
        self._session_id = session_id

    def _ctx(self):
        return build_actor_context(
            actor_type="human",
            channel="gui",
            session_id=self._session_id,
        )

    def query_inventory(self, yaml_path, **filters):
        aliases = {
            "parent_cell_line": "cell",
            "short_name": "short",
            "plasmid_name": "plasmid",
        }
        allowed = {"cell", "short", "plasmid", "plasmid_id", "box", "position"}

        normalized = {}
        for key, value in filters.items():
            mapped_key = aliases.get(key, key)
            if mapped_key in allowed:
                normalized[mapped_key] = value

        return tool_query_inventory(yaml_path=yaml_path, **normalized)

    def list_empty_positions(self, yaml_path, box=None):
        return tool_list_empty_positions(yaml_path=yaml_path, box=box)

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

    def rollback(self, yaml_path, backup_path=None):
        return tool_rollback(
            yaml_path=yaml_path,
            backup_path=backup_path,
            actor_context=self._ctx(),
            source="app_gui",
        )

    def run_agent_query(
        self,
        yaml_path,
        query,
        model=None,
        max_steps=DEFAULT_MAX_STEPS,
        history=None,
        on_event=None,
        plan_sink=None,
        thinking_enabled=True,
        custom_prompt="",
        _expose_runner=None,
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

        chosen_model = (model or "").strip() or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
        use_thinking = bool(thinking_enabled)

        try:
            llm = DeepSeekLLMClient(model=chosen_model, thinking_enabled=use_thinking)
            runner = AgentToolRunner(
                yaml_path=yaml_path,
                session_id=self._session_id,
                plan_sink=plan_sink,
            )
            if callable(_expose_runner):
                _expose_runner(runner)
            agent = ReactAgent(llm_client=llm, tool_runner=runner, max_steps=steps, custom_prompt=str(custom_prompt or ""))
            result = agent.run(prompt, conversation_history=history, on_event=on_event)
        except RuntimeError as exc:
            message = str(exc)
            if "DEEPSEEK_API_KEY is required" in message:
                return {
                    "ok": False,
                    "error_code": "api_key_required",
                    "message": _api_key_setup_hint(),
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
            "mode": "deepseek",
            "model": chosen_model,
        }
