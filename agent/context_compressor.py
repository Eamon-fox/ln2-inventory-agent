"""Context compression for long conversation histories.

Implements a sliding-window + summary strategy: recent messages are kept
verbatim while older tool-result messages are compressed into concise
summaries that preserve key fields (id, box, position, cell_line, etc.).
"""

import json
from typing import Any

# Tool actions whose results carry critical fields worth preserving.
_WRITE_ACTIONS = frozenset({
    "add_entry", "edit_entry", "takeout", "move", "rollback",
})

# Keys to extract from successful tool results for the summary line.
_SUMMARY_KEYS = ("id", "box", "position", "cell_line", "short_name", "action")


def _parse_tool_content(content: str) -> dict | None:
    """Try to parse a tool message's content as JSON dict."""
    if not content:
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _summarize_tool_result(content: str) -> str:
    """Compress a tool result into a one-line summary preserving key fields.

    For successful write operations, extracts critical fields.
    For failures, keeps the error_code and message.
    For large result sets (queries), keeps counts and truncates.
    """
    parsed = _parse_tool_content(content)
    if parsed is None:
        # Not JSON — truncate raw text.
        if len(content) > 200:
            return content[:200] + "...(truncated)"
        return content

    ok = parsed.get("ok")

    if not ok:
        # Keep error info compact.
        parts = {"ok": False}
        for key in ("error_code", "message"):
            if key in parsed:
                parts[key] = parsed[key]
        return json.dumps(parts, ensure_ascii=False)

    # Successful result — extract key fields from nested result/items.
    result = parsed.get("result")
    summary: dict[str, Any] = {"ok": True}

    if isinstance(result, dict):
        # Extract staged items summary (add_entry staging returns items list).
        items = result.get("items") or result.get("staged_items")
        if isinstance(items, list) and items:
            compact_items = []
            for item in items:
                if isinstance(item, dict):
                    compact = {k: item[k] for k in _SUMMARY_KEYS if k in item}
                    if compact:
                        compact_items.append(compact)
                    elif len(str(item)) <= 120:
                        compact_items.append(item)
            if compact_items:
                summary["items"] = compact_items
                summary["count"] = len(compact_items)
                return json.dumps(summary, ensure_ascii=False)

        # Extract key fields directly from result dict.
        compact = {k: result[k] for k in _SUMMARY_KEYS if k in result}
        if compact:
            summary.update(compact)
            return json.dumps(summary, ensure_ascii=False)

        # For query results with records list.
        records = result.get("records") or result.get("entries")
        if isinstance(records, list):
            summary["count"] = len(records)
            if len(records) <= 3:
                summary["records"] = records
            else:
                summary["records"] = records[:2]
                summary["truncated"] = True
            return json.dumps(summary, ensure_ascii=False)

    # Fallback: keep the message field if present.
    if "message" in parsed:
        summary["message"] = parsed["message"]
        return json.dumps(summary, ensure_ascii=False)

    # Last resort: truncate the whole JSON.
    raw = json.dumps(parsed, ensure_ascii=False)
    if len(raw) > 300:
        return raw[:300] + "...(truncated)"
    return raw


def _get_tool_name_from_assistant(assistant_msg: dict) -> str | None:
    """Extract the tool name from an assistant message's tool_calls."""
    tool_calls = assistant_msg.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    first = tool_calls[0]
    if isinstance(first, dict):
        # Check nested function.name format.
        func = first.get("function")
        if isinstance(func, dict):
            return str(func.get("name") or "").strip() or None
        return str(first.get("name") or "").strip() or None
    return None


def _is_tool_call_id_linked(tool_call_id: str, assistant_msg: dict) -> bool:
    """Check if a tool message's call_id matches any call in the assistant message."""
    tool_calls = assistant_msg.get("tool_calls")
    if not isinstance(tool_calls, list):
        return False
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        if call.get("id") == tool_call_id:
            return True
    return False


def compress_history(messages: list[dict], recent_window: int) -> list[dict]:
    """Compress conversation history, keeping recent messages verbatim.

    Args:
        messages: Full cleaned message list (no system messages).
        recent_window: Number of recent messages to keep uncompressed.

    Returns:
        Compressed message list with a summary preamble for old messages
        followed by the recent window of verbatim messages.
    """
    if not messages or len(messages) <= recent_window:
        return list(messages)

    older = messages[:-recent_window]
    recent = messages[-recent_window:]

    # Build a summary of older tool results.
    compressed: list[dict] = []
    # Track which assistant messages precede tool messages for context.
    last_assistant: dict | None = None

    for msg in older:
        role = msg.get("role")

        if role == "user":
            # Keep user messages but truncate very long ones.
            content = str(msg.get("content") or "")
            if len(content) > 500:
                compressed.append({**msg, "content": content[:500] + "...(truncated)"})
            else:
                compressed.append(msg)
            last_assistant = None
            continue

        if role == "assistant":
            last_assistant = msg
            tool_calls = msg.get("tool_calls")
            has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0

            if has_tool_calls:
                # Keep the assistant tool-call message but strip reasoning.
                entry = dict(msg)
                entry.pop("reasoning_content", None)
                compressed.append(entry)
            else:
                # Plain assistant text — truncate if long.
                content = str(msg.get("content") or "")
                if len(content) > 300:
                    compressed.append({**msg, "content": content[:300] + "...(truncated)"})
                else:
                    compressed.append(msg)
                last_assistant = None
            continue

        if role == "tool":
            content = str(msg.get("content") or "")
            summarized = _summarize_tool_result(content)
            compressed.append({**msg, "content": summarized})
            continue

        # Unknown role — keep as-is.
        compressed.append(msg)

    return compressed + recent
