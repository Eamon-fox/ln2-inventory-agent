"""Isolated file-operation service entrypoint."""

from __future__ import annotations

import json
import shutil
import sys

from .file_ops_policy import (
    FileOpsPolicyError,
    normalize_roots,
    resolve_shell_workdir,
    resolve_read_path,
    resolve_write_path,
)
from .terminal_tool import DEFAULT_TERMINAL_TIMEOUT_SECONDS, run_terminal_command
from .tool_runtime_paths import build_migration_path_env


def _as_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(default)


def _error_payload(error_code, message, *, repo_root=None, resolved_path=None, extra=None):
    payload = {
        "ok": False,
        "error_code": str(error_code),
        "message": str(message),
    }
    if repo_root not in (None, ""):
        payload["effective_root"] = str(repo_root)
    if resolved_path not in (None, ""):
        payload["resolved_path"] = str(resolved_path)
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


def _ok_base(repo_root, resolved_path=None):
    payload = {
        "ok": True,
        "effective_root": str(repo_root),
    }
    if resolved_path is not None:
        payload["resolved_path"] = str(resolved_path)
    return payload


def _parse_positive_int(value, *, field_name, default):
    if value in (None, ""):
        return int(default)
    try:
        parsed = int(value)
    except Exception as exc:
        raise FileOpsPolicyError("invalid_tool_input", f"{field_name} must be an integer.") from exc
    if parsed <= 0:
        raise FileOpsPolicyError("invalid_tool_input", f"{field_name} must be > 0.")
    return parsed


def _list_dir_entries(target_path, max_entries):
    entries = []
    for idx, item in enumerate(sorted(target_path.iterdir(), key=lambda p: p.name.lower())):
        if idx >= max_entries:
            break
        stat = item.stat()
        entries.append(
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            }
        )
    return entries


def _handle_fs_list(args, *, repo_root, migrate_root):
    del migrate_root
    max_entries = _parse_positive_int(args.get("max_entries"), field_name="max_entries", default=200)
    resolved = resolve_read_path(repo_root, args.get("path"), default_rel=".")
    if not resolved.exists():
        return _error_payload("path_not_found", f"Path not found: {resolved}", repo_root=repo_root, resolved_path=resolved)
    if not resolved.is_dir():
        return _error_payload(
            "path_not_directory",
            f"Path is not a directory: {resolved}",
            repo_root=repo_root,
            resolved_path=resolved,
        )

    payload = _ok_base(repo_root, resolved)
    entries = _list_dir_entries(resolved, max_entries)
    payload["count"] = len(entries)
    payload["entries"] = entries
    return payload


def _handle_fs_read(args, *, repo_root, migrate_root):
    del migrate_root
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    resolved = resolve_read_path(repo_root, args.get("path"), default_rel=".")
    if not resolved.exists():
        return _error_payload("path_not_found", f"Path not found: {resolved}", repo_root=repo_root, resolved_path=resolved)
    if resolved.is_dir():
        return _error_payload(
            "path_is_directory",
            f"Path is a directory: {resolved}",
            repo_root=repo_root,
            resolved_path=resolved,
        )
    try:
        content = resolved.read_text(encoding=encoding)
    except Exception as exc:
        return _error_payload("file_read_failed", str(exc), repo_root=repo_root, resolved_path=resolved)

    payload = _ok_base(repo_root, resolved)
    payload["encoding"] = encoding
    payload["content"] = content
    return payload


def _handle_fs_write(args, *, repo_root, migrate_root):
    resolved = resolve_write_path(repo_root, migrate_root, args.get("path"), default_rel="migrate")
    overwrite = _as_bool(args.get("overwrite"), default=False)
    content = args.get("content")
    if not isinstance(content, str):
        return _error_payload("invalid_tool_input", "content must be a string.", repo_root=repo_root, resolved_path=resolved)

    if resolved.exists():
        if resolved.is_dir():
            return _error_payload(
                "path_is_directory",
                f"Path is a directory: {resolved}",
                repo_root=repo_root,
                resolved_path=resolved,
            )
        if not overwrite:
            return _error_payload(
                "file_exists_and_overwrite_false",
                f"File already exists: {resolved}",
                repo_root=repo_root,
                resolved_path=resolved,
            )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")

    payload = _ok_base(repo_root, resolved)
    payload["bytes_written"] = len(content.encode("utf-8"))
    return payload


def _handle_fs_copy(args, *, repo_root, migrate_root):
    source = resolve_read_path(repo_root, args.get("src"), default_rel=".")
    if not source.exists():
        return _error_payload("path_not_found", f"Path not found: {source}", repo_root=repo_root, resolved_path=source)
    if source.is_dir():
        return _error_payload(
            "path_is_directory",
            f"Path is a directory: {source}",
            repo_root=repo_root,
            resolved_path=source,
        )

    destination = resolve_write_path(repo_root, migrate_root, args.get("dst"), default_rel="migrate")
    overwrite = _as_bool(args.get("overwrite"), default=False)
    if destination.exists():
        if destination.is_dir():
            return _error_payload(
                "path_is_directory",
                f"Path is a directory: {destination}",
                repo_root=repo_root,
                resolved_path=destination,
            )
        if not overwrite:
            return _error_payload(
                "file_exists_and_overwrite_false",
                f"File already exists: {destination}",
                repo_root=repo_root,
                resolved_path=destination,
            )

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
    except Exception as exc:
        return _error_payload("file_copy_failed", str(exc), repo_root=repo_root, resolved_path=destination)

    payload = _ok_base(repo_root, destination)
    payload["source_path"] = str(source)
    try:
        payload["bytes_copied"] = int(destination.stat().st_size)
    except Exception:
        pass
    return payload


def _handle_fs_edit(args, *, repo_root, migrate_root):
    file_path = str(args.get("filePath") or "").strip()
    if not file_path:
        return _error_payload("invalid_tool_input", "filePath must be a non-empty repository-relative path.", repo_root=repo_root)

    old_text = args.get("oldString")
    new_text = args.get("newString")
    replace_all = _as_bool(args.get("replaceAll"), default=False)

    if not isinstance(old_text, str) or not old_text:
        return _error_payload("invalid_tool_input", "oldString must be a non-empty string.", repo_root=repo_root)
    if not isinstance(new_text, str):
        return _error_payload("invalid_tool_input", "newString must be a string.", repo_root=repo_root)
    if new_text == old_text:
        return _error_payload("invalid_tool_input", "newString must differ from oldString.", repo_root=repo_root)

    resolved = resolve_write_path(repo_root, migrate_root, file_path, default_rel="migrate")
    if not resolved.exists():
        return _error_payload("path_not_found", f"Path not found: {resolved}", repo_root=repo_root, resolved_path=resolved)
    if resolved.is_dir():
        return _error_payload(
            "path_is_directory",
            f"Path is a directory: {resolved}",
            repo_root=repo_root,
            resolved_path=resolved,
        )

    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        return _error_payload("file_read_failed", str(exc), repo_root=repo_root, resolved_path=resolved)

    match_count = int(content.count(old_text))
    if match_count <= 0:
        return _error_payload(
            "old_string_not_found",
            "oldString not found in target file.",
            repo_root=repo_root,
            resolved_path=resolved,
            extra={"replace_all": bool(replace_all), "match_count": match_count},
        )
    if not replace_all and match_count > 1:
        return _error_payload(
            "ambiguous_match",
            "Multiple matches found while replaceAll=false; set replaceAll=true or narrow oldString.",
            repo_root=repo_root,
            resolved_path=resolved,
            extra={"replace_all": False, "match_count": match_count},
        )

    updated = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
    try:
        resolved.write_text(updated, encoding="utf-8")
    except Exception as exc:
        return _error_payload("file_write_failed", str(exc), repo_root=repo_root, resolved_path=resolved)

    payload = _ok_base(repo_root, resolved)
    payload["match_count"] = match_count
    payload["replace_all"] = bool(replace_all)
    payload["bytes_written"] = len(updated.encode("utf-8"))
    return payload


def _parse_timeout_ms(timeout_value):
    timeout_ms = (
        float(timeout_value)
        if timeout_value not in (None, "")
        else DEFAULT_TERMINAL_TIMEOUT_SECONDS * 1000.0
    )
    if timeout_ms <= 0:
        raise FileOpsPolicyError("invalid_tool_input", "timeout must be greater than 0 milliseconds.")
    return timeout_ms


def _handle_shell(args, *, repo_root, migrate_root, engine):
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return _error_payload("invalid_tool_input", "command must be a non-empty string.", repo_root=repo_root)

    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        return _error_payload("invalid_tool_input", "description must be a non-empty string.", repo_root=repo_root)

    try:
        timeout_ms = _parse_timeout_ms(args.get("timeout"))
    except FileOpsPolicyError as exc:
        return _error_payload(exc.code, exc.message, repo_root=repo_root)

    workdir = resolve_shell_workdir(repo_root, migrate_root, args.get("workdir"))
    workdir.mkdir(parents=True, exist_ok=True)

    response = run_terminal_command(
        command,
        timeout_seconds=(timeout_ms / 1000.0),
        cwd=str(workdir),
        engine=engine,
        extra_env=build_migration_path_env(repo_root, migrate_root),
    )
    if not isinstance(response, dict):
        return _error_payload("terminal_exec_failed", "Terminal execution returned invalid payload.", repo_root=repo_root)

    enriched = dict(response)
    enriched["effective_root"] = str(repo_root)
    enriched["resolved_path"] = str(workdir)
    return enriched


def _handle_bash(args, *, repo_root, migrate_root):
    return _handle_shell(args, repo_root=repo_root, migrate_root=migrate_root, engine="bash")


def _handle_powershell(args, *, repo_root, migrate_root):
    return _handle_shell(args, repo_root=repo_root, migrate_root=migrate_root, engine="powershell")


def handle_request(request):
    if not isinstance(request, dict):
        return _error_payload("invalid_request", "Request payload must be a JSON object.")

    tool_name = str(request.get("tool") or "").strip()
    args = request.get("args")
    if not isinstance(args, dict):
        return _error_payload("invalid_request", "args must be an object.")

    try:
        repo_root, migrate_root = normalize_roots(
            request.get("repo_root"),
            request.get("migrate_root"),
        )
    except FileOpsPolicyError as exc:
        return _error_payload(
            exc.code,
            exc.message,
            repo_root=request.get("repo_root"),
            resolved_path=exc.resolved_path,
        )

    handlers = {
        "fs_list": _handle_fs_list,
        "fs_read": _handle_fs_read,
        "fs_write": _handle_fs_write,
        "fs_copy": _handle_fs_copy,
        "fs_edit": _handle_fs_edit,
        "bash": _handle_bash,
        "powershell": _handle_powershell,
    }
    handler = handlers.get(tool_name)
    if not callable(handler):
        return _error_payload("unknown_tool", f"Unknown file tool: {tool_name}", repo_root=repo_root)

    try:
        return handler(args, repo_root=repo_root, migrate_root=migrate_root)
    except FileOpsPolicyError as exc:
        return _error_payload(exc.code, exc.message, repo_root=repo_root, resolved_path=exc.resolved_path)
    except Exception as exc:  # pragma: no cover - last-resort crash shield for subprocess boundary
        return _error_payload("service_internal_error", str(exc), repo_root=repo_root)


def _configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                continue


def _main():
    _configure_stdio()
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {}
    response = handle_request(payload)
    sys.stdout.write(json.dumps(response, ensure_ascii=True))
    sys.stdout.flush()


if __name__ == "__main__":
    _main()
