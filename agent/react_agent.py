"""ReAct loop implementation for LN2 inventory agent."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


SYSTEM_PROMPT = """You are an LN2 inventory assistant.

Rules:
1) Use available function tools whenever inventory data is needed.
2) Follow tool parameter names and constraints from tool_specs (including enum values).
3) Tool results may include `_hint`; use it to recover from errors.
4) If enough information is available, answer directly and clearly.
5) Keep responses concise and operationally accurate.
"""


class ReactAgent:
    """Native tool-calling ReAct runtime."""

    def __init__(self, llm_client, tool_runner, max_steps=8):
        self._llm = llm_client
        self._tools = tool_runner
        self._max_steps = max_steps

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
        return "\"agent_runtime\"" in content

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
    def _normalize_tool_call(raw_call, index):
        if not isinstance(raw_call, dict):
            return None

        call_id = str(raw_call.get("id") or f"call_{uuid.uuid4().hex[:12]}_{index}").strip()
        name = str(raw_call.get("name") or raw_call.get("tool") or "").strip()
        if not name:
            return None

        arguments = raw_call.get("arguments")
        if not isinstance(arguments, dict):
            return None

        return {
            "id": call_id,
            "name": name,
            "arguments": arguments,
        }

    @staticmethod
    def _assistant_tool_message(content, tool_calls):
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

    def _run_tool_call(self, call, tool_names, trace_id):
        action = call["name"]
        action_input = call["arguments"]
        tool_call_id = call["id"]

        if action not in tool_names:
            observation = {
                "ok": False,
                "error_code": "unknown_tool",
                "message": f"Unknown tool: {action}",
                "_hint": "Choose action from available tools.",
            }
        else:
            observation = self._tools.run(action, action_input, trace_id=trace_id)

        return {
            "action": action,
            "action_input": action_input,
            "tool_call_id": tool_call_id,
            "observation": observation,
            "output_text": self._serialize_tool_output(observation),
        }

    def _request_direct_answer(self, messages):
        """Ask model for a plain final answer without tool schemas."""
        try:
            response = self._llm.chat(messages, tools=None, temperature=0.0)
        except Exception:
            return ""

        if not isinstance(response, dict):
            return ""

        text = str(response.get("content") or "").strip()
        if text:
            return text

        final_fallback = response.get("final")
        if isinstance(final_fallback, str):
            return final_fallback.strip()
        return ""

    def run(self, user_query, conversation_history=None, on_event=None):
        trace_id = f"trace-{uuid.uuid4().hex}"
        tool_names = self._tools.list_tools()
        tool_specs = self._tools.tool_specs() if hasattr(self._tools, "tool_specs") else {}
        tool_schemas = self._tools.tool_schemas() if hasattr(self._tools, "tool_schemas") else []
        memory = self._normalize_history(conversation_history)

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
                "timestamp": datetime.now().timestamp(),
            },
            self._build_runtime_context_message(tool_specs),
        ]
        messages.extend(memory)
        messages.append(
            {
                "role": "user",
                "content": str(user_query or ""),
                "timestamp": datetime.now().timestamp(),
            }
        )

        self._emit_event(
            on_event,
            {
                "type": "run_start",
                "event": "run_start",
                "trace_id": trace_id,
                "max_steps": self._max_steps,
                "tool_count": len(tool_schemas),
            },
        )

        answer_buf = []
        current_answer_buf = []
        forced_final_retry = False

        for step in range(1, self._max_steps + 1):
            current_answer_buf = []
            self._emit_event(
                on_event,
                {
                    "type": "step_start",
                    "event": "step_start",
                    "trace_id": trace_id,
                    "step": step,
                },
            )

            model_response = self._llm.chat(messages, tools=tool_schemas, temperature=0.0)
            if not isinstance(model_response, dict):
                observation = {
                    "ok": False,
                    "error_code": "invalid_model_response",
                    "message": "LLM client returned non-dict response payload.",
                }
                self._emit_event(
                    on_event,
                    {
                        "event": "error",
                        "type": "error",
                        "trace_id": trace_id,
                        "step": step,
                        "action": "llm_response",
                        "action_input": {},
                        "observation": observation,
                        "data": observation.get("message"),
                    },
                )
                self._emit_event(on_event, {**self._yield_stream_end(messages, status="error"), "trace_id": trace_id})
                return {
                    "ok": False,
                    "trace_id": trace_id,
                    "steps": step,
                    "final": "Agent failed: invalid LLM response payload.",
                    "conversation_history_used": len(memory),
                }

            assistant_content = str(model_response.get("content") or "").strip()
            final_fallback = model_response.get("final")
            if not assistant_content and isinstance(final_fallback, str):
                assistant_content = final_fallback.strip()

            if assistant_content:
                answer_buf.append(assistant_content)
                current_answer_buf.append(assistant_content)
                self._emit_event(
                    on_event,
                    {
                        "event": "chunk",
                        "type": "chunk",
                        "trace_id": trace_id,
                        "step": step,
                        "data": assistant_content,
                        "meta": {"channel": "answer"},
                    },
                )

            raw_tool_calls = model_response.get("tool_calls") or []
            normalized_tool_calls = []
            for index, raw_call in enumerate(raw_tool_calls):
                normalized = self._normalize_tool_call(raw_call, index)
                if normalized:
                    normalized_tool_calls.append(normalized)

            if raw_tool_calls and not normalized_tool_calls:
                observation = {
                    "ok": False,
                    "error_code": "invalid_tool_call",
                    "message": "Model returned malformed tool call payload.",
                    "_hint": "Provide tool name and JSON-object arguments in tool call.",
                }
                self._emit_event(
                    on_event,
                    {
                        "event": "error",
                        "type": "error",
                        "trace_id": trace_id,
                        "step": step,
                        "action": "tool_call_parse",
                        "action_input": {},
                        "observation": observation,
                        "data": observation.get("message"),
                    },
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Previous tool call format was invalid. Retry with valid function name and JSON-object arguments.",
                        "timestamp": datetime.now().timestamp(),
                    }
                )
                continue

            if normalized_tool_calls:
                messages.append(self._assistant_tool_message(assistant_content, normalized_tool_calls))

                for call in normalized_tool_calls:
                    self._emit_event(
                        on_event,
                        {
                            "event": "tool_start",
                            "type": "tool_start",
                            "trace_id": trace_id,
                            "step": step,
                            "data": {
                                "name": call["name"],
                                "input": {
                                    "tool_call_id": call["id"],
                                    "args": call["arguments"],
                                },
                            },
                            "action": call["name"],
                            "action_input": call["arguments"],
                            "tool_call_id": call["id"],
                        },
                    )

                max_workers = max(1, len(normalized_tool_calls))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(self._run_tool_call, call, tool_names, trace_id)
                        for call in normalized_tool_calls
                    ]
                    results = [future.result() for future in futures]

                for result in results:
                    action = result["action"]
                    action_input = result["action_input"]
                    tool_call_id = result["tool_call_id"]
                    observation = result["observation"]
                    output_text = result["output_text"]

                    self._emit_event(
                        on_event,
                        {
                            "event": "tool_end",
                            "type": "tool_end",
                            "trace_id": trace_id,
                            "step": step,
                            "data": {
                                "name": action,
                                "output": {
                                    "tool_call_id": tool_call_id,
                                    "content": output_text,
                                },
                            },
                            "action": action,
                            "action_input": action_input,
                            "tool_call_id": tool_call_id,
                            "observation": observation,
                        },
                    )
                    messages.append(self._tool_message(tool_call_id, observation))
                continue

            if not assistant_content and not forced_final_retry and step < self._max_steps:
                forced_final_retry = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Please provide a concise final answer to the user now.",
                        "timestamp": datetime.now().timestamp(),
                    }
                )
                continue

            if not assistant_content:
                direct_text = self._request_direct_answer(messages)
                if direct_text:
                    assistant_content = direct_text
                    answer_buf.append(assistant_content)
                    current_answer_buf.append(assistant_content)
                    self._emit_event(
                        on_event,
                        {
                            "event": "chunk",
                            "type": "chunk",
                            "trace_id": trace_id,
                            "step": step,
                            "data": assistant_content,
                            "meta": {"channel": "answer"},
                        },
                    )

            final_text = "".join(answer_buf).strip()
            if not final_text:
                final_text = "I could not generate a complete answer. Please retry."

            if current_answer_buf:
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(current_answer_buf),
                        "timestamp": datetime.now().timestamp(),
                    }
                )

            self._emit_event(
                on_event,
                {
                    "event": "final",
                    "type": "final",
                    "trace_id": trace_id,
                    "step": step,
                    "data": final_text,
                },
            )
            self._emit_event(
                on_event,
                {
                    "type": "finish",
                    "event": "finish",
                    "trace_id": trace_id,
                    "step": step,
                    "final": final_text,
                },
            )
            self._emit_event(on_event, {**self._yield_stream_end(messages, status="complete"), "trace_id": trace_id})
            return {
                "ok": True,
                "trace_id": trace_id,
                "steps": step,
                "final": final_text,
                "conversation_history_used": len(memory),
            }

        self._emit_event(
            on_event,
            {
                "type": "max_steps",
                "event": "max_steps",
                "trace_id": trace_id,
                "steps": self._max_steps,
            },
        )

        final_text = "".join(answer_buf).strip() or "Max steps reached without final answer."
        self._emit_event(
            on_event,
            {
                "event": "final",
                "type": "final",
                "trace_id": trace_id,
                "step": self._max_steps,
                "data": final_text,
            },
        )
        self._emit_event(on_event, {**self._yield_stream_end(messages, status="max_steps"), "trace_id": trace_id})

        return {
            "ok": False,
            "trace_id": trace_id,
            "steps": self._max_steps,
            "final": final_text,
            "conversation_history_used": len(memory),
        }
