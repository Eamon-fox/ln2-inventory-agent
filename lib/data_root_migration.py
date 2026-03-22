"""Inventory-core helpers for post-copy data-root migration rewrites.

This module owns the content-level rewrite rules required after a managed
data-root migration. The storage layer may copy directory trees, but the
inventory-core layer defines which persisted fields must be remapped so the
copied datasets keep working under strict path validation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml


AUDIT_RUNTIME_PATH_FIELDS = ("yaml_path", "backup_path")


def _normalize_root(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    return os.path.abspath(os.path.expanduser(raw))


def remap_path_between_data_roots(path: str, *, source_root: str, target_root: str) -> str:
    """Map one absolute path from source_root to target_root when possible."""
    current = os.path.abspath(str(path or "").strip())
    source = _normalize_root(source_root)
    target = _normalize_root(target_root)
    if not current or not source or not target:
        return str(path or "")
    try:
        rel = Path(current).relative_to(Path(source))
    except Exception:
        return str(path or "")
    return os.path.abspath(os.path.join(target, os.fspath(rel)))


def _write_text_atomic(path: Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, target)


def _rewrite_migrated_inventory_yaml(yaml_path: Path, *, source_root: str, target_root: str) -> None:
    if not yaml_path.is_file():
        return
    try:
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"failed to rewrite migrated inventory YAML: {yaml_path}") from exc
    if not isinstance(payload, dict):
        payload = {}
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        payload["meta"] = meta
    meta["instance_origin_path"] = remap_path_between_data_roots(
        str(meta.get("instance_origin_path") or yaml_path),
        source_root=source_root,
        target_root=target_root,
    )
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
    _write_text_atomic(yaml_path, content)


def _rewrite_migrated_audit_log(audit_path: Path, *, source_root: str, target_root: str) -> None:
    if not audit_path.is_file():
        return
    try:
        original = audit_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise ValueError(f"failed to read migrated audit log: {audit_path}") from exc
    rewritten_lines = []
    for raw_line in original.splitlines(keepends=True):
        stripped = raw_line.strip()
        if not stripped:
            rewritten_lines.append(raw_line)
            continue
        try:
            payload = json.loads(stripped)
        except Exception:
            rewritten_lines.append(raw_line)
            continue
        if not isinstance(payload, dict):
            rewritten_lines.append(raw_line)
            continue
        for field_name in AUDIT_RUNTIME_PATH_FIELDS:
            field_value = payload.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                payload[field_name] = remap_path_between_data_roots(
                    field_value,
                    source_root=source_root,
                    target_root=target_root,
                )
        line_ending = ""
        if raw_line.endswith("\r\n"):
            line_ending = "\r\n"
        elif raw_line.endswith("\n"):
            line_ending = "\n"
        rewritten_lines.append(json.dumps(payload, ensure_ascii=False) + line_ending)
    _write_text_atomic(audit_path, "".join(rewritten_lines))


def rewrite_migrated_inventory_tree(*, source_root: str, target_root: str, inventories_root: str) -> None:
    """Rewrite copied managed inventory content after a data-root migration.

    The rewrite scope is intentionally narrow:
    - inventory YAML: ``meta.instance_origin_path``
    - audit JSONL: top-level fields listed in ``AUDIT_RUNTIME_PATH_FIELDS``

    Historical detail payloads are left untouched because they are explanatory
    context, not runtime path references used by strict validation or rollback.
    """
    inventories_dir = Path(inventories_root)
    if not inventories_dir.is_dir():
        return
    for yaml_path in inventories_dir.glob("*/inventory.yaml"):
        _rewrite_migrated_inventory_yaml(yaml_path, source_root=source_root, target_root=target_root)
        _rewrite_migrated_audit_log(
            yaml_path.parent / "audit" / "events.jsonl",
            source_root=source_root,
            target_root=target_root,
        )
