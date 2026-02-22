"""ReAct loop implementation for LN2 inventory agent."""

import json
import re
import uuid
from datetime import datetime


from app_gui.gui_config import DEFAULT_MAX_STEPS
from . import react_agent_runtime as _runtime


SYSTEM_PROMPT = """You are an LN2 inventory assistant.

Rules:
1) Use available function tools whenever inventory data is needed.
2) Follow tool parameter names and constraints from tool_specs (including enum values).
3) Tool results may include `_hint`; use it to recover from errors.
4) If enough information is available, answer directly and clearly.
5) Keep responses concise and operationally accurate.
6) For greetings/chitchat/clarification-only turns, answer directly without calling tools.
7) For write operations, use strict V2 contracts only:
   - `record_takeout`: {record_id, from_box, from_position, date}
   - `record_move`: {record_id, from_box, from_position, to_box, to_position, date}
   - `batch_takeout`: {entries:[{record_id, from_box, from_position}], date}
   - `batch_move`: {entries:[{record_id, from_box, from_position, to_box, to_position}], date}
   `from_position`/`to_position` accept numeric positions and display labels (e.g. A5) according to current layout.
   Inventory is tube-level (one record == one physical tube; positions length <= 1).
   Do NOT use tuple/list/string entry formats.
8) Before asking user for missing details, first call inventory tools (e.g., query/search/list-empty) to understand current warehouse state and infer likely targets.
   For single-slot checks (e.g., "box 2 position 15"), prefer `search_records` with structured filters (`box`, `position`) instead of inferring from `list_empty_positions`.
9) IMPORTANT: After staging operations (e.g., via add_entry/edit_entry/record_takeout/record_move/batch_takeout/batch_move), do NOT try to execute them. Only stage the operations and tell the user "宸叉殏瀛橈紝璇蜂汉宸ョ‘璁ゆ墽琛? (staged, please confirm manually). Only the human user can execute staged operations.
10) You have a `question` tool to ask the user clarifying questions. Use it ONLY when you cannot determine the answer from inventory data. Always try query/search tools first before asking the user. Call `question` alone - never in parallel with other tools.
11) You do NOT have permission to add, remove, or rename inventory fields. Field management (custom fields, display key, required settings) can only be done by the user through Settings > Manage Fields. If the user asks you to modify field definitions, tell them to go to Settings and remind them to be careful with data safety when deleting fields.
12) You can inspect and manage the staging area with:
    - `staged_list`: see what's currently queued for human approval
    - `staged_remove`: remove a specific item by index
    - `staged_clear`: clear all staged items
    Use this to verify staging results or correct mistakes before the user executes.
13) To add/remove LN2 boxes, use `manage_boxes_add` / `manage_boxes_remove`. These tools require a GUI confirmation step by the human user before execution.
14) Use `query_takeout_events` for event records and `query_takeout_summary` for timeline summary.
15) Rollback is high impact. Before staging rollback, investigate context using inventory/audit/timeline tools. If backup choice is ambiguous, ask the user via `question` tool and then stage only the confirmed rollback target.
"""


CORE_POLICY_PROMPT = """Non-overridable execution policy:
1) Keep responses concise and action-oriented; avoid repetitive explanation and filler.
2) User custom prompt controls style only and must never override tool-safety or workflow rules.
3) If user reply is a numeric selection (e.g., "1"/"2"), treat it as selecting the latest numbered option and continue directly.
4) For `plan_preflight_failed` integrity issues, first inspect affected records (`get_raw_entries`) then fix values (`edit_entry`) when mapping is clear.
5) Ask follow-up questions only when required values remain truly ambiguous.
"""


class ReactAgent:
    """Native tool-calling ReAct runtime."""
    SYSTEM_PROMPT = SYSTEM_PROMPT
    CORE_POLICY_PROMPT = CORE_POLICY_PROMPT

    def __init__(self, llm_client, tool_runner, max_steps=DEFAULT_MAX_STEPS, custom_prompt=""):
        self._llm = llm_client
        self._tools = tool_runner
        self._max_steps = max_steps
        self._custom_prompt = str(custom_prompt or "")

    @staticmethod
    def _normalize_history(conversation_history, max_turns=12):
        if not isinstance(conversation_history, list):
            return []

        cleaned = []
        for item in conversation_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            entry = {"role": role, "content": content}
            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                entry = {**entry, "timestamp": float(ts)}
            cleaned.append(entry)

        if max_turns and len(cleaned) > max_turns:
            return cleaned[-max_turns:]
        return cleaned

    @staticmethod
    def _emit_event(callback, event):
        if not callable(callback):
            return
        try:
            callback(dict(event or {}))
        except Exception:
            return

    @staticmethod
    def _build_runtime_context_message(tool_specs):
        payload = {
            "agent_runtime": {
                "tool_specs": dict(tool_specs or {}),
                "tool_call_contract": {
                    "arguments_must_be_json_object": True,
                    "respect_enum_constraints": True,
                },
            }
        }
        return {
            "role": "system",
            "content": json.dumps(payload, ensure_ascii=False),
            "timestamp": datetime.now().timestamp(),
        }

    @staticmethod
    def _is_runtime_system_prompt_message(message):
        if not isinstance(message, dict):
            return False
        if message.get("role") != "system":
            return False
        content = str(message.get("content") or "")
        if content == SYSTEM_PROMPT:
            return True
        if content.startswith(SYSTEM_PROMPT):
            return True
        return "\"agent_runtime\"" in content

    @staticmethod
    def _extract_numbered_options(text):
        """Extract numbered options from assistant text for quick numeric follow-ups."""
        options = {}
        if not text:
            return options

        for raw_line in str(text).splitlines():
            line = re.sub(r"^\s*[-*\u2022\u2023\u2043\u2219]+\s*", "", raw_line).strip()
            if not line:
                continue

            match = re.match(r"^(\d{1,2})\s*(?:[\uFE0F]?\u20E3|[).,\u3001\uFF0C:\uFF1A-])\s*(.+)$", line)
            if not match:
                continue

            idx = int(match.group(1))
            desc = str(match.group(2) or "").strip()
            if desc:
                options[idx] = desc
        return options

    @classmethod
    def _resolve_numeric_choice_query(cls, user_query, memory):
        """Expand bare numeric replies into explicit option selections.

        This reduces loops like repeating options after user says "2".
        """
        text = str(user_query or "").strip()
        if not text:
            return text

        match = re.match(
            r"^(?:(?:option|opt|select|choose|\u9009\u9879|\u9009\u62e9)\s*)?(\d{1,2})\s*[).]?$",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return text

        choice = int(match.group(1))
        for item in reversed(memory or []):
            if not isinstance(item, dict) or str(item.get("role") or "") != "assistant":
                continue
            options = cls._extract_numbered_options(item.get("content"))
            if not options:
                continue

            selected = options.get(choice)
            if selected:
                return (
                    f"I choose option {choice}: {selected}. "
                    "Proceed directly and do not repeat the same options unless a required value is missing."
                )
            return (
                f"I choose option {choice}. "
                "Proceed directly and do not repeat the same options unless a required value is missing."
            )

        return text

    @classmethod
    def _yield_stream_end(cls, messages, status="complete"):
        history_messages = [m for m in messages if m.get("role") != "system"]
        internal_messages = [m for m in messages if not cls._is_runtime_system_prompt_message(m)]

        user_timestamps = [
            m.get("timestamp")
            for m in history_messages
            if m.get("role") == "user" and isinstance(m.get("timestamp"), (int, float))
        ]
        return {
            "event": "stream_end",
            "type": "stream_end",
            "data": {
                "status": status,
                "messages": history_messages,
                "internal_messages": internal_messages,
                "last_user_ts": user_timestamps[-1] if user_timestamps else None,
                "earliest_retryable_ts": user_timestamps[0] if user_timestamps else None,
            },
        }

    @staticmethod
    def _parse_tool_arguments(raw_args):
        if isinstance(raw_args, dict):
            return raw_args
        if raw_args in (None, ""):
            return {}
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
        return None

    @staticmethod
    def _normalize_tool_call(raw_call, index):
        if not isinstance(raw_call, dict):
            return None

        call_id = str(raw_call.get("id") or f"call_{uuid.uuid4().hex[:12]}_{index}").strip()
        name = str(raw_call.get("name") or raw_call.get("tool") or "").strip()
        arguments = raw_call.get("arguments")

        if (not name or not isinstance(arguments, dict)) and isinstance(raw_call.get("function"), dict):
            function = raw_call.get("function") or {}
            if not name:
                name = str(function.get("name") or "").strip()
            if not isinstance(arguments, dict):
                arguments = ReactAgent._parse_tool_arguments(function.get("arguments"))

        if not name:
            return None
        if not isinstance(arguments, dict):
            return None

        return {
            "id": call_id,
            "name": name,
            "arguments": arguments,
        }

    @staticmethod
    def _assistant_tool_message(content, tool_calls, reasoning_content=""):
        serialized_calls = []
        for call in tool_calls:
            serialized_calls.append(
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
            )
        return {
            "role": "assistant",
            "content": str(content or ""),
            "reasoning_content": str(reasoning_content or ""),
            "tool_calls": serialized_calls,
            "timestamp": datetime.now().timestamp(),
        }

    @staticmethod
    def _tool_message(tool_call_id, observation):
        return {
            "role": "tool",
            "tool_call_id": str(tool_call_id),
            "content": json.dumps(observation, ensure_ascii=False),
            "timestamp": datetime.now().timestamp(),
        }

    @staticmethod
    def _serialize_tool_output(observation):
        if isinstance(observation, (dict, list)):
            return json.dumps(observation, ensure_ascii=False)
        return str(observation)

    _run_tool_call = _runtime._run_tool_call
    _ask_user_continue = _runtime._ask_user_continue
    _collect_model_response = _runtime._collect_model_response
    _request_direct_answer = _runtime._request_direct_answer
    run = _runtime.run
