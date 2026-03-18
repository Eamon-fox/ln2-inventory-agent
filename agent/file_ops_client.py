"""Client helpers for calling isolated file-operation service."""

from __future__ import annotations

from .tool_runtime_paths import derive_migrate_root, derive_repo_root_from_yaml

def run_file_tool(tool_name, args, *, yaml_path):
    """Execute a file tool via in-process file-operation service."""
    repo_root = derive_repo_root_from_yaml(yaml_path)
    migrate_root = derive_migrate_root(repo_root)
    payload = {
        "tool": str(tool_name or "").strip(),
        "args": dict(args or {}),
        "repo_root": str(repo_root),
        "migrate_root": str(migrate_root),
    }

    try:
        from .file_ops_service import handle_request

        response = handle_request(payload)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "file_ops_service_failed",
            "message": str(exc),
            "effective_root": str(repo_root),
        }

    if not isinstance(response, dict):
        return {
            "ok": False,
            "error_code": "file_ops_invalid_response",
            "message": "File operation service returned non-object response.",
            "effective_root": str(repo_root),
        }
    if "effective_root" not in response:
        response = dict(response)
        response["effective_root"] = str(repo_root)
    return response
