"""ReAct loop implementation for LN2 inventory agent."""

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


from app_gui.gui_config import DEFAULT_MAX_STEPS


SYSTEM_PROMPT = """You are an LN2 inventory assistant.

Rules:
1) Use available function tools whenever inventory data is needed.
2) Follow tool parameter names and constraints from tool_specs (including enum values).
3) Tool results may include `_hint`; use it to recover from errors.
4) If enough information is available, answer directly and clearly.
5) Keep responses concise and operationally accurate.
6) For greetings/chitchat/clarification-only turns, answer directly without calling tools.
7) For move operations: to change a tube's box, use `to_box` parameter in record_thaw or batch_thaw.
   Inventory is tube-level (one record == one physical tube; positions length <= 1).
   batch_thaw entries format for cross-box: '4:5->4:1' (id:from->to:target_box).
8) Before asking user for missing details, first call inventory tools (e.g., query/search/list-empty) to understand current warehouse state and infer likely targets.
9) IMPORTANT: After staging operations (e.g., via record_thaw, batch_thaw, add_entry), do NOT try to execute them. Only stage the operations and tell the user "已暂存，请人工确认执行" (staged, please confirm manually). Only the human user can execute staged operations.
10) You have a `question` tool to ask the user clarifying questions. Use it ONLY when you cannot determine the answer from inventory data. Always try query/search tools first before asking the user. Call `question` alone — never in parallel with other tools.
"""


class ReactAgent:
    """Native tool-calling ReAct runtime."""

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

        # Handle question tool: emit event to GUI, block until user answers
        if (
            action == "question"
            and isinstance(observation, dict)
            and observation.get("waiting_for_user")
        ):
            self._emit_event(
                getattr(self, "_on_event", None),
                {
                    "event": "question",
                    "type": "question",
                    "trace_id": trace_id,
                    "question_id": observation.get("question_id"),
                    "questions": observation.get("questions"),
                    "tool_call_id": tool_call_id,
                },
            )

            runner = self._tools
            answered = runner._answer_event.wait(timeout=300)

            if not answered:
                observation = {
                    "ok": False,
                    "error_code": "question_timeout",
                    "message": "User did not answer within timeout.",
                }
            elif runner._answer_cancelled:
                observation = {
                    "ok": False,
                    "error_code": "question_cancelled",
                    "message": "User cancelled the question.",
                }
            else:
                answers = runner._pending_answer or []
                questions = observation.get("questions") or []
                formatted = []
                for i, ans in enumerate(answers):
                    q = questions[i] if i < len(questions) else {}
                    header = q.get("header", f"Q{i+1}")
                    if isinstance(ans, list):
                        formatted.append(f"{header}: {', '.join(ans)}")
                    else:
                        formatted.append(f"{header}: {ans}")

                observation = {
                    "ok": True,
                    "result": {
                        "answers": formatted,
                        "raw_answers": answers,
                    },
                    "message": "User answered: " + "; ".join(formatted),
                }

        return {
            "action": action,
            "action_input": action_input,
            "tool_call_id": tool_call_id,
            "observation": observation,
            "output_text": self._serialize_tool_output(observation),
        }

    def _ask_user_continue(self, on_event, trace_id):
        """Emit max_steps_ask event and block until user responds.

        Returns True if user wants to continue, False otherwise.
        Reuses the threading.Event on AgentToolRunner for synchronization.
        Falls back to False (stop) if the tool runner lacks the event mechanism.
        """
        runner = self._tools
        if not isinstance(getattr(runner, "_answer_event", None), threading.Event):
            return False

        runner._answer_event.clear()
        runner._pending_answer = None
        runner._answer_cancelled = False

        self._emit_event(
            on_event,
            {
                "event": "max_steps_ask",
                "type": "max_steps_ask",
                "trace_id": trace_id,
                "steps": self._max_steps,
            },
        )

        answered = runner._answer_event.wait(timeout=300)
        return answered and not runner._answer_cancelled

    def _collect_model_response(self, messages, tool_schemas, trace_id, step, on_event):
        stream_fn = getattr(self._llm, "stream_chat", None)
        if callable(stream_fn):
            iterator = stream_fn(messages, tools=tool_schemas, temperature=0.0)
        else:
            fallback_response = self._llm.chat(messages, tools=tool_schemas, temperature=0.0)

            def _fallback_iter():
                if not isinstance(fallback_response, dict):
                    yield {"type": "error", "error": "LLM client returned non-dict response payload."}
                    return
                content = str(fallback_response.get("content") or "")
                if content:
                    yield {"type": "answer", "text": content}
                for raw_tool_call in fallback_response.get("tool_calls") or []:
                    yield {"type": "tool_call", "tool_call": raw_tool_call}

            iterator = _fallback_iter()

        if not hasattr(iterator, "__iter__"):
            return {
                "error": "LLM stream handler returned non-iterable payload.",
                "content": "",
                "tool_calls": [],
            }

        answer_parts = []
        thought_parts = []
        tool_calls = []
        for raw_event in getattr(iterator, "__iter__", lambda: iter(()))():
            if not isinstance(raw_event, dict):
                continue

            event_type = str(raw_event.get("type") or "").strip().lower()
            if event_type == "answer":
                chunk = str(raw_event.get("text") or "")
                if chunk:
                    answer_parts.append(chunk)
                    self._emit_event(
                        on_event,
                        {
                            "event": "chunk",
                            "type": "chunk",
                            "trace_id": trace_id,
                            "step": step,
                            "data": chunk,
                            "meta": {"channel": "answer"},
                        },
                    )
                continue

            if event_type == "thought":
                chunk = str(raw_event.get("text") or "")
                if chunk:
                    thought_parts.append(chunk)
                    self._emit_event(
                        on_event,
                        {
                            "event": "chunk",
                            "type": "chunk",
                            "trace_id": trace_id,
                            "step": step,
                            "data": chunk,
                            "meta": {"channel": "thought"},
                        },
                    )
                continue

            if event_type == "tool_call":
                raw_tool_call = raw_event.get("tool_call")
                normalized = self._normalize_tool_call(raw_tool_call, len(tool_calls))
                if normalized:
                    tool_calls.append(normalized)
                continue

            if event_type == "error":
                return {
                    "error": str(raw_event.get("error") or "LLM stream failed"),
                    "content": "".join(answer_parts).strip(),
                    "thought": "".join(thought_parts).strip(),
                    "tool_calls": tool_calls,
                }

        return {
            "error": None,
            "content": "".join(answer_parts).strip(),
            "thought": "".join(thought_parts).strip(),
            "tool_calls": tool_calls,
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
        self._on_event = on_event  # Store for _run_tool_call to use
        trace_id = f"trace-{uuid.uuid4().hex}"
        tool_names = self._tools.list_tools()
        tool_specs = self._tools.tool_specs() if hasattr(self._tools, "tool_specs") else {}
        tool_schemas = self._tools.tool_schemas() if hasattr(self._tools, "tool_schemas") else []
        memory = self._normalize_history(conversation_history)

        system_content = SYSTEM_PROMPT + f"\nCurrent time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if self._custom_prompt:
            system_content += f"\n\nAdditional user instructions:\n{self._custom_prompt}"

        messages = [
            {
                "role": "system",
                "content": system_content,
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

        last_answer_text = ""
        current_answer_buf = []
        forced_final_retry = False

        original_max_steps = self._max_steps
        step = 1
        while True:
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

            model_response = self._collect_model_response(
                messages=messages,
                tool_schemas=tool_schemas,
                trace_id=trace_id,
                step=step,
                on_event=on_event,
            )

            if model_response.get("error"):
                observation = {
                    "ok": False,
                    "error_code": "llm_stream_failed",
                    "message": str(model_response.get("error") or "LLM stream failed"),
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
                    "final": "Agent failed: LLM stream error.",
                    "conversation_history_used": len(memory),
                }

            assistant_content = str(model_response.get("content") or "").strip()
            if assistant_content:
                last_answer_text = assistant_content
                current_answer_buf.append(assistant_content)

            normalized_tool_calls = model_response.get("tool_calls") or []

            if normalized_tool_calls is None:
                normalized_tool_calls = []

            if model_response.get("tool_calls") and not normalized_tool_calls:
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
                step += 1
                if step > self._max_steps:
                    if self._ask_user_continue(on_event, trace_id):
                        self._max_steps += original_max_steps
                    else:
                        break
                continue

            if normalized_tool_calls:
                assistant_reasoning = str(model_response.get("thought") or "")
                messages.append(
                    self._assistant_tool_message(
                        assistant_content,
                        normalized_tool_calls,
                        reasoning_content=assistant_reasoning,
                    )
                )

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

                # Reject question tool when called in parallel with other tools
                has_question = any(c["name"] == "question" for c in normalized_tool_calls)
                if has_question and len(normalized_tool_calls) > 1:
                    for call in normalized_tool_calls:
                        if call["name"] == "question":
                            messages.append(self._tool_message(call["id"], {
                                "ok": False,
                                "error_code": "question_not_alone",
                                "message": "question tool must be called alone, not with other tools.",
                                "_hint": "Call question separately, then use other tools after getting the answer.",
                            }))
                        else:
                            result = self._run_tool_call(call, tool_names, trace_id)
                            self._emit_event(
                                on_event,
                                {
                                    "event": "tool_end",
                                    "type": "tool_end",
                                    "trace_id": trace_id,
                                    "step": step,
                                    "data": {"name": result["action"], "output": {"tool_call_id": result["tool_call_id"], "content": result["output_text"]}},
                                    "action": result["action"],
                                    "action_input": result["action_input"],
                                    "tool_call_id": result["tool_call_id"],
                                    "observation": result["observation"],
                                },
                            )
                            messages.append(self._tool_message(result["tool_call_id"], result["observation"]))
                    step += 1
                    if step > self._max_steps:
                        if self._ask_user_continue(on_event, trace_id):
                            self._max_steps += original_max_steps
                        else:
                            break
                    continue

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
                step += 1
                if step > self._max_steps:
                    if self._ask_user_continue(on_event, trace_id):
                        self._max_steps += original_max_steps
                    else:
                        break
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
                step += 1
                if step > self._max_steps:
                    if self._ask_user_continue(on_event, trace_id):
                        self._max_steps += original_max_steps
                    else:
                        break
                continue

            if not assistant_content:
                direct_text = self._request_direct_answer(messages)
                if direct_text:
                    assistant_content = direct_text
                    last_answer_text = assistant_content
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

            final_text = str(assistant_content or last_answer_text).strip()
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

        final_text = str(last_answer_text).strip() or "Max steps reached without final answer."
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
