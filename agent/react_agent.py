"""ReAct loop implementation for LN2 inventory agent."""

import json
import uuid


SYSTEM_PROMPT = """You are an LN2 inventory ReAct agent.

Rules:
1) You can only act by calling one available tool at a time.
2) Respond ONLY in JSON with keys: thought, action, action_input, final.
3) action must be one of the provided tool names or 'finish'.
4) If action == 'finish', provide final answer in 'final'.
5) If action != 'finish', set final to empty string.
6) Keep thought short.
7) Use conversation_history to keep continuity across turns.
8) If user asks about previous responses, answer from conversation_history directly.
9) Strictly follow tool_specs for parameter names and required fields.
10) For write tools (add_entry/record_thaw/batch_thaw/rollback), prefer dry_run=true first, then execute.
"""


class ReactAgent:
    """Small JSON-based ReAct runtime."""

    def __init__(self, llm_client, tool_runner, max_steps=8):
        self._llm = llm_client
        self._tools = tool_runner
        self._max_steps = max_steps

    @staticmethod
    def _parse_json(text):
        raw = (text or "").strip()
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    return None
            return None

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
            cleaned.append({"role": role, "content": content})

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

    def run(self, user_query, conversation_history=None, on_event=None):
        trace_id = f"trace-{uuid.uuid4().hex}"
        tool_names = self._tools.list_tools()
        if hasattr(self._tools, "tool_specs"):
            tool_specs = self._tools.tool_specs()
        else:
            tool_specs = {}
        memory = self._normalize_history(conversation_history)

        self._emit_event(
            on_event,
            {
                "type": "run_start",
                "trace_id": trace_id,
                "max_steps": self._max_steps,
            },
        )

        scratch = []
        for step in range(1, self._max_steps + 1):
            self._emit_event(
                on_event,
                {
                    "type": "step_start",
                    "trace_id": trace_id,
                    "step": step,
                },
            )
            prompt = {
                "step": step,
                "trace_id": trace_id,
                "available_tools": tool_names,
                "tool_specs": tool_specs,
                "user_query": user_query,
                "conversation_history": memory,
                "scratchpad": scratch,
                "required_json_schema": {
                    "thought": "string",
                    "action": "tool name or finish",
                    "action_input": "object",
                    "final": "string",
                },
            }

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ]
            model_text = self._llm.complete(messages, temperature=0.0)
            action_obj = self._parse_json(model_text)

            if not isinstance(action_obj, dict):
                invalid_event = {
                    "type": "step_invalid_json",
                    "trace_id": trace_id,
                    "step": step,
                    "raw": model_text,
                }
                self._emit_event(on_event, invalid_event)
                scratch.append(
                    {
                        "step": step,
                        "error": "invalid_json_response",
                        "raw": model_text,
                    }
                )
                continue

            action = action_obj.get("action")
            action_input = action_obj.get("action_input") or {}

            if action == "finish":
                self._emit_event(
                    on_event,
                    {
                        "type": "finish",
                        "trace_id": trace_id,
                        "step": step,
                        "final": action_obj.get("final", ""),
                    },
                )
                return {
                    "ok": True,
                    "trace_id": trace_id,
                    "steps": step,
                    "final": action_obj.get("final", ""),
                    "conversation_history_used": len(memory),
                    "scratchpad": scratch,
                }

            if action not in tool_names:
                unknown_obs = {
                    "ok": False,
                    "error_code": "unknown_tool",
                    "message": f"Unknown tool: {action}",
                }
                scratch.append(
                    {
                        "step": step,
                        "thought": action_obj.get("thought"),
                        "action": action,
                        "action_input": action_input,
                        "observation": unknown_obs,
                    }
                )
                self._emit_event(
                    on_event,
                    {
                        "type": "step_end",
                        "trace_id": trace_id,
                        "step": step,
                        "action": action,
                        "action_input": action_input,
                        "observation": unknown_obs,
                    },
                )
                continue

            observation = self._tools.run(action, action_input, trace_id=trace_id)
            scratch.append(
                {
                    "step": step,
                    "thought": action_obj.get("thought"),
                    "action": action,
                    "action_input": action_input,
                    "observation": observation,
                }
            )
            self._emit_event(
                on_event,
                {
                    "type": "step_end",
                    "trace_id": trace_id,
                    "step": step,
                    "action": action,
                    "action_input": action_input,
                    "observation": observation,
                },
            )

        self._emit_event(
            on_event,
            {
                "type": "max_steps",
                "trace_id": trace_id,
                "steps": self._max_steps,
            },
        )
        return {
            "ok": False,
            "trace_id": trace_id,
            "steps": self._max_steps,
            "final": "Max steps reached without finish action.",
            "conversation_history_used": len(memory),
            "scratchpad": scratch,
        }
