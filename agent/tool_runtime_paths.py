"""Shared path derivation for tool runtime and hooks."""

from __future__ import annotations

from pathlib import Path


def derive_repo_root_from_yaml(yaml_path):
    inventory_path = Path(str(yaml_path or "")).resolve(strict=False)
    if inventory_path.name.lower() != "inventory.yaml":
        raise ValueError("yaml_path must end with inventory.yaml")
    try:
        return inventory_path.parents[2]
    except IndexError as exc:
        raise ValueError("yaml_path does not follow managed inventories layout.") from exc


def derive_migrate_root(repo_root):
    return (Path(repo_root) / "migrate").resolve(strict=False)


def build_tool_hook_context(yaml_path, *, trace_id=None):
    yaml_text = str(yaml_path or "").strip()
    repo_root = ""
    migrate_root = ""
    if yaml_text:
        try:
            repo_root = str(derive_repo_root_from_yaml(yaml_text))
            migrate_root = str(derive_migrate_root(repo_root))
        except Exception:
            repo_root = ""
            migrate_root = ""
    return {
        "yaml_path": yaml_text,
        "repo_root": repo_root,
        "migrate_root": migrate_root,
        "trace_id": str(trace_id or ""),
    }
