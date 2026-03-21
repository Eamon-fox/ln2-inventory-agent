"""Centralized formatter for tool progress status text."""

MAX_STATUS_TEXT_LENGTH = 80


def _clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # Normalize whitespace so UI lines stay stable.
    return " ".join(text.split())


def _running_fallback(tool_name):
    name = _clean_text(tool_name) or "tool"
    return f"Running {name}..."


def _truncate_status(text, max_length=MAX_STATUS_TEXT_LENGTH):
    clean = _clean_text(text)
    try:
        limit = int(max_length)
    except Exception:
        limit = MAX_STATUS_TEXT_LENGTH
    if limit <= 0:
        limit = MAX_STATUS_TEXT_LENGTH
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return clean[:limit]
    return clean[: limit - 3].rstrip() + "..."


def _format_bash(tool_name, args):
    desc = _clean_text(args.get("description"))
    if desc:
        return desc
    return _running_fallback(tool_name)


def _format_powershell(tool_name, args):
    desc = _clean_text(args.get("description"))
    if desc:
        return desc
    return _running_fallback(tool_name)


def _format_fs_list(_tool_name, args):
    path = _clean_text(args.get("path"))
    if path and path != ".":
        return f"List files in {path}"
    return "List files in repository"


def _format_fs_read(_tool_name, args):
    path = _clean_text(args.get("path"))
    if path:
        return f"Read file {path}"
    return "Read file"


def _format_fs_write(_tool_name, args):
    path = _clean_text(args.get("path"))
    if path:
        return f"Write file {path}"
    return "Write file"


def _format_fs_copy(_tool_name, args):
    src = _clean_text(args.get("src"))
    dst = _clean_text(args.get("dst"))
    if src and dst:
        return f"Copy file {src} to {dst}"
    if dst:
        return f"Copy file to {dst}"
    return "Copy file"


def _format_fs_edit(_tool_name, args):
    file_path = _clean_text(args.get("filePath"))
    if file_path:
        return f"Edit text in {file_path}"
    return "Edit text in file"


def _format_search_records(_tool_name, args):
    query = _clean_text(args.get("query"))
    if query:
        return f"Search inventory: {query}"
    return "Search inventory"


def _format_filter_records(_tool_name, args):
    keyword = _clean_text(args.get("keyword"))
    if keyword:
        return f"Filter table: {keyword}"
    return "Filter inventory table"


def _format_generate_stats(_tool_name, _args):
    return "Generate inventory stats"


def _format_add_entry(_tool_name, args):
    box = _clean_text(args.get("box"))
    if box:
        return f"Stage add entries in box {box}"
    return "Stage add entries"


def _format_takeout(_tool_name, _args):
    return "Stage takeout entries"


def _format_move(_tool_name, _args):
    return "Stage move entries"


def _format_edit_entry(_tool_name, args):
    record_id = _clean_text(args.get("record_id"))
    if record_id:
        return f"Stage edit record {record_id}"
    return "Stage edit record"


def format_tool_status(tool_name, args, *, runtime_spec=None, formatter=None, max_length=MAX_STATUS_TEXT_LENGTH):
    """Return concise, UI-friendly status text for one tool call."""
    name = _clean_text(tool_name) or "tool"
    payload = args if isinstance(args, dict) else {}
    resolved_formatter = formatter
    if resolved_formatter is None and runtime_spec is not None:
        resolved_formatter = getattr(runtime_spec, "status_formatter", None)
    status = ""
    if callable(resolved_formatter):
        try:
            status = _clean_text(resolved_formatter(name, payload))
        except Exception:
            status = ""
    if not status:
        status = _running_fallback(name)
    return _truncate_status(status, max_length=max_length)
