"""Client helpers for calling isolated file-operation service."""

from __future__ import annotations

from pathlib import Path

def _derive_repo_root_from_yaml(yaml_path):
    inventory_path = Path(str(yaml_path or "")).resolve(strict=False)
    if inventory_path.name.lower() != "inventory.yaml":
        raise ValueError("yaml_path must end with inventory.yaml")
    try:
        return inventory_path.parents[2]
    except IndexError as exc:
        raise ValueError("yaml_path does not follow managed inventories layout.") from exc


def _derive_migrate_root(repo_root):
    return (Path(repo_root) / "migrate").resolve(strict=False)


def run_file_tool(tool_name, args, *, yaml_path):
    """Execute a file tool via in-process file-operation service."""
    repo_root = _derive_repo_root_from_yaml(yaml_path)
    migrate_root = _derive_migrate_root(repo_root)
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
