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

    def run(self, user_query, conversation_history=None):
        trace_id = f"trace-{uuid.uuid4().hex}"
        tool_names = self._tools.list_tools()
        memory = self._normalize_history(conversation_history)

        scratch = []
        for step in range(1, self._max_steps + 1):
            prompt = {
                "step": step,
                "trace_id": trace_id,
                "available_tools": tool_names,
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
                return {
                    "ok": True,
                    "trace_id": trace_id,
                    "steps": step,
                    "final": action_obj.get("final", ""),
                    "conversation_history_used": len(memory),
                    "scratchpad": scratch,
                }

            if action not in tool_names:
                scratch.append(
                    {
                        "step": step,
                        "thought": action_obj.get("thought"),
                        "action": action,
                        "action_input": action_input,
                        "observation": {
                            "ok": False,
                            "error_code": "unknown_tool",
                            "message": f"Unknown tool: {action}",
                        },
                    }
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

        return {
            "ok": False,
            "trace_id": trace_id,
            "steps": self._max_steps,
            "final": "Max steps reached without finish action.",
            "conversation_history_used": len(memory),
            "scratchpad": scratch,
        }
