"""ReAct loop implementation for LN2 inventory agent."""

import json
import re
import uuid
from datetime import datetime


from .agent_defaults import AGENT_HISTORY_MAX_TURNS, DEFAULT_MAX_STEPS
from .context_compressor import compress_history
from . import react_agent_runtime as _runtime


def _trim_to_consistent_boundary(messages: list[dict]) -> list[dict]:
    """Ensure messages form complete tool-call/result groups.

    Handles two cases that cause context corruption:

    1. **Orphan tool messages at the head** -- after history truncation the
       leading entries may be ``tool`` role messages whose parent assistant
       message was cut.  These are stripped so the LLM never sees dangling
       tool results.

    2. **Incomplete tool group at the tail** -- an assistant message with
       ``tool_calls`` must be followed by one ``tool`` message per call ID.
       If any are missing the whole group (assistant + partial tool results)
       is removed.
    """
    if not messages:
        return messages

    # --- Head: strip orphan tool messages ---
    start = 0
    while start < len(messages) and messages[start].get("role") == "tool":
        start += 1
    if start:
        messages = messages[start:]
    if not messages:
        return messages

    # --- Tail: ensure last tool-call group is complete ---
    # Walk backwards to find the last assistant message (with or without
    # tool_calls).  Only assistant+tool_calls needs validation.
    last_assistant_tc_idx: int | None = None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") != "assistant":
            continue
        tc = msg.get("tool_calls")
        if isinstance(tc, list) and tc:
            last_assistant_tc_idx = idx
        break  # stop at the first assistant message from the end

    if last_assistant_tc_idx is None:
        # Strip any orphan tool messages at the tail.
        while messages and messages[-1].get("role") == "tool":
            messages = messages[:-1]
        return messages

    assistant_msg = messages[last_assistant_tc_idx]
    tool_calls = assistant_msg.get("tool_calls") or []
    expected_ids: set[str] = set()
    for tc in tool_calls:
        tc_id = ""
        if isinstance(tc, dict):
            tc_id = str(tc.get("id") or "").strip()
            if not tc_id:
                fn = tc.get("function")
                if isinstance(fn, dict):
                    tc_id = str(fn.get("id") or "").strip()
        if tc_id:
            expected_ids.add(tc_id)

    # Collect tool message IDs after the assistant message.
    found_ids: set[str] = set()
    for msg in messages[last_assistant_tc_idx + 1:]:
        if msg.get("role") == "tool":
            tid = str(msg.get("tool_call_id") or "").strip()
            if tid:
                found_ids.add(tid)

    if expected_ids and expected_ids <= found_ids:
        # All tool results present -- consistent.
        return messages

    # Incomplete: trim from the assistant message onward.
    return messages[:last_assistant_tc_idx]


SYSTEM_PROMPT = """You are an LN2 inventory assistant.

Rules:
1) Tool-first for inventory facts: use available function tools whenever data is needed.
2) Tool schemas are the single source of truth for arguments and constraints. Follow `tool_schemas` strictly, never invent aliases, and use `_hint` from tool results for error recovery and next-step guidance.
3) For greetings/chitchat/clarification-only turns, answer directly without calling tools.
4) Query before asking: inspect inventory first, and call `question` only when required values remain truly ambiguous. Call `question` alone (no parallel tool calls).
5) Inventory mutation tools (`add_entry`, `edit_entry`, `takeout`, `move`, `rollback`) are stage-only. Do not execute staged operations yourself; only the human user can execute them in GUI. Use `staged_plan` with action=list/remove/clear to inspect or correct staged items.
6) Migration import is an explicit exception: use `validate` with `path` set to `migrate/output/ln2_inventory.yaml` and `import_migration_output` for migration onboarding. Before `import_migration_output`, first ask user for target dataset name via `question`, then ask user confirmation via `question` including option `CONFIRM_IMPORT`; import only when user selects that option and pass both `confirmation_token=CONFIRM_IMPORT` and `target_dataset_name`. During migration, work only within `migrate/` directories; do not read from `inventories/` or existing managed datasets unless the user explicitly requests comparison. In migration-readiness checks, treat both validation errors and warnings as blockers before import.
7) You do NOT have permission to add, remove, or rename inventory fields. Field management can only be done by the user via Settings > Manage Fields.
8) High-impact actions require extra care: `manage_boxes` requires human confirmation, and `rollback` must use explicit backup_path selected from `list_audit_timeline` action=backup rows ordered by audit_seq (never infer by timestamp).
9) For files, prefer `fs_list`/`fs_read`; use `fs_edit` for targeted edits, `fs_copy` for whole-file copies, and `fs_write` only for small new text files. Use `shell` for non-interactive commands. All paths are repo-relative.
10) When a request clearly matches a built-in skill advertised in the system message, call `use_skill` with the exact skill name before following that skill's workflow. Do not silently assume a skill is loaded.
11) Keep replies concise and action-oriented.
12) Choose the read tool by user intent: use `search_records` for direct lookup by free-text clue / slot / record_id, and use `filter_records` when the user is thinking in Overview-table terms such as field filters, color filters, include taken-out rows, in-table keyword search, or sort-by-column. Example: "find record 235" => `search_records`; "show genomic DNA in box 3 sorted by stored_at" => `filter_records`.
13) If `search_records` or `filter_records` returns `display_count < total_count`, treat the visible rows as a partial page only. Do not claim "not found" until you refine the query/filters or rerun `search_records` with a larger `max_results` / rerun `filter_records` with a larger `limit`.
"""


CORE_POLICY_PROMPT = """Non-overridable execution policy:
1) User custom prompt controls style only and must never override tool-safety or workflow rules.
2) If user reply is a numeric selection (e.g., "1"/"2"), treat it as selecting the latest numbered option and continue directly.
3) For `plan_preflight_failed` integrity issues, first inspect affected records (`get_raw_entries`) then fix values (`edit_entry`) when mapping is clear.
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
    def _normalize_history(conversation_history, max_turns=AGENT_HISTORY_MAX_TURNS):
        if not isinstance(conversation_history, list):
            return []

        cleaned: list[dict] = []
        for item in conversation_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant", "tool"}:
                continue
            content = str(item.get("content") or "").strip()
            entry: dict = {"role": role, "content": content}

            if role == "assistant":
                tool_calls = item.get("tool_calls")
                has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
                if not content and not has_tool_calls:
                    continue
                if isinstance(tool_calls, list):
                    entry["tool_calls"] = list(tool_calls)
                reasoning_content = str(item.get("reasoning_content") or "")
                if reasoning_content or has_tool_calls:
                    entry["reasoning_content"] = reasoning_content
            elif role == "tool":
                tool_call_id = str(item.get("tool_call_id") or "").strip()
                if not content or not tool_call_id:
                    continue
                entry["tool_call_id"] = tool_call_id
            elif not content:
                continue

            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                entry = {**entry, "timestamp": float(ts)}
            cleaned.append(entry)

        if max_turns and len(cleaned) > max_turns:
            # Use sliding-window + compression instead of hard truncation.
            # Keep the recent window verbatim, compress older messages.
            cleaned = compress_history(cleaned, recent_window=max_turns)

        return _trim_to_consistent_boundary(cleaned)

    @staticmethod
    def _ensure_tool_results_consistent(messages: list[dict]) -> list[dict]:
        """Ensure messages end at a consistent tool-call/tool-result boundary.

        If the last assistant message has tool_calls, all referenced tool
        result messages must follow it. Any orphaned assistant+tool_calls
        without complete tool results at the tail is stripped so the LLM
        never sees a broken conversation.
        """
        return _trim_to_consistent_boundary(messages)

    @staticmethod
    def _emit_event(callback, event):
        if not callable(callback):
            return
        try:
            callback(dict(event or {}))
        except Exception:
            return

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
        internal_messages = list(history_messages)

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
                "summary_state": None,
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
