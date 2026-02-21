"""Build a portable import task bundle for external coding agents.

The bundle is designed for workflows where users hand raw files to an
external assistant (e.g. Codex/Claude Code), then bring back a generated
``ln2_inventory.yaml`` for strict local validation.
"""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


_BUNDLE_VERSION = "1.0"
_REQUIRED_OUTPUT_PATH = "output/ln2_inventory.yaml"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _collect_source_files(source_paths: Iterable[str]) -> Tuple[List[str], List[str]]:
    files: List[str] = []
    warnings: List[str] = []
    seen: set = set()

    for raw in source_paths or []:
        if raw is None:
            continue
        src = os.path.abspath(os.fspath(raw))
        if src in seen:
            continue
        seen.add(src)

        if os.path.isfile(src):
            files.append(src)
            continue

        if os.path.isdir(src):
            for root, _dirs, names in os.walk(src):
                for name in sorted(names):
                    path = os.path.join(root, name)
                    if os.path.isfile(path):
                        files.append(path)
            continue

        warnings.append(f"Skipped missing path: {src}")

    # Stable ordering keeps bundle reproducible.
    files.sort()
    return files, warnings


def _dedupe_name(name: str, used_lower_names: set) -> str:
    base, ext = os.path.splitext(name)
    candidate = name
    index = 2
    while candidate.lower() in used_lower_names:
        candidate = f"{base}_{index}{ext}"
        index += 1
    used_lower_names.add(candidate.lower())
    return candidate


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _build_schema_payload() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LN2 Inventory Import Schema",
        "type": "object",
        "required": ["meta", "inventory"],
        "additionalProperties": False,
        "properties": {
            "meta": {
                "type": "object",
                "required": ["box_layout"],
                "properties": {
                    "box_layout": {
                        "type": "object",
                        "required": ["rows", "cols"],
                        "properties": {
                            "rows": {"type": "integer", "minimum": 1},
                            "cols": {"type": "integer", "minimum": 1},
                            "box_count": {"type": "integer", "minimum": 1},
                            "indexing": {"type": "string", "enum": ["numeric", "alphanumeric"]},
                        },
                        "additionalProperties": True,
                    },
                    "custom_fields": {"type": "array"},
                },
                "additionalProperties": True,
            },
            "inventory": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "box", "frozen_at"],
                    "properties": {
                        "id": {"type": "integer", "minimum": 1},
                        "box": {"type": "integer", "minimum": 1},
                        "position": {"type": ["integer", "null"], "minimum": 1},
                        "frozen_at": {
                            "type": "string",
                            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        },
                        "thaw_events": {"type": ["array", "null"]},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }


def _build_rules_markdown() -> str:
    return """# LN2 Import Validation Rules

The generated file **must** be `output/ln2_inventory.yaml`.

## Required structure

- Top-level keys must be exactly: `meta`, `inventory`.
- Data model is tube-level: each `inventory[]` item is one physical tube.

## Required record fields

- `id`: unique positive integer.
- `box`: positive integer within configured box layout.
- `frozen_at`: date in `YYYY-MM-DD`.

## Position rules

- `position` may be integer or null.
- If `position` is null, record must include valid takeout history in `thaw_events`.
- Active records must not conflict on `(box, position)`.

## Date rules

- `frozen_at` and thaw-event dates must be `YYYY-MM-DD`.
- Future dates are invalid.

## Recommended workflow for external agent

1. Parse source files from `inputs/`.
2. Ask clarifying questions when source content is ambiguous.
3. Produce final YAML at `output/ln2_inventory.yaml`.
4. (Optional) Write transformation notes in `output/conversion_report.md`.
"""


def _build_prompt_en() -> str:
    return """# Task: Convert source materials to LN2 inventory YAML

You are given source files under `inputs/`.

Goal:
- Produce a valid `output/ln2_inventory.yaml` file that satisfies:
  - `schema/ln2_import_schema.json`
  - `schema/validation_rules.md`

Requirements:
- Ask clarification questions when source records are ambiguous.
- Do not invent tube records.
- Keep one inventory item per physical tube.
- Use `null` only when it is allowed by validation rules.
- Return only final YAML file in the required path.
"""


def _build_prompt_zh() -> str:
    return """# 任务：将源材料转换为 LN2 库存 YAML

你将收到 `inputs/` 目录中的原始文件。

目标：
- 生成 `output/ln2_inventory.yaml`，并满足：
  - `schema/ln2_import_schema.json`
  - `schema/validation_rules.md`

要求：
- 源数据有歧义时，先提问再生成结果。
- 不要凭空编造记录。
- 数据模型是 tube-level：每条 inventory 代表一支物理冻存管。
- 仅在规则允许时使用 `null`。
- 最终交付必须放在指定路径。
"""


def _build_example_yaml() -> str:
    return """meta:
  box_layout:
    rows: 9
    cols: 9
  custom_fields: []

inventory:
  - id: 1
    box: 1
    position: 1
    frozen_at: "2025-01-01"
    cell_line: K562
    note: null
    thaw_events: null
"""


def _bundle_error(error_code: str, message: str, warnings: List[str] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "error_code": str(error_code or "unknown_error"),
        "message": str(message or ""),
        "warnings": list(warnings or []),
    }


def build_import_task_bundle(
    source_paths: Iterable[str],
    output_zip_path: str,
    options: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Create a portable ZIP task bundle for external conversion agents.

    Args:
        source_paths: Files/directories to include under ``inputs/``.
        output_zip_path: Destination ZIP path (``.zip`` auto-appended if missing).
        options: Optional metadata map recorded in ``manifest.json``.

    Returns:
        dict:
            - ok: bool
            - bundle_path: absolute ZIP path (on success)
            - manifest: manifest payload (on success)
            - warnings: list[str]
            - error_code/message (on failure)
    """
    files, warnings = _collect_source_files(source_paths)
    if not files:
        return _bundle_error(
            "empty_sources",
            "No valid source files were provided for task bundle export.",
            warnings=warnings,
        )

    output_zip = str(output_zip_path or "").strip()
    if not output_zip:
        return _bundle_error("invalid_output_path", "Output ZIP path is required.", warnings=warnings)
    if not output_zip.lower().endswith(".zip"):
        output_zip += ".zip"
    output_zip = os.path.abspath(output_zip)

    out_dir = os.path.dirname(output_zip)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    temp_root = tempfile.mkdtemp(prefix="ln2_import_bundle_")
    bundle_root = os.path.join(temp_root, "bundle")
    try:
        os.makedirs(bundle_root, exist_ok=True)
        for rel in ("inputs", "schema", "templates", "examples", "output"):
            os.makedirs(os.path.join(bundle_root, rel), exist_ok=True)

        used_names: set = set()
        manifest_sources: List[Dict[str, Any]] = []
        for src in files:
            source_name = os.path.basename(src) or "source.bin"
            bundle_name = _dedupe_name(source_name, used_names)
            rel_path = f"inputs/{bundle_name}"
            target = os.path.join(bundle_root, rel_path.replace("/", os.sep))
            shutil.copy2(src, target)
            manifest_sources.append(
                {
                    "source_path": src,
                    "bundle_path": rel_path,
                    "size_bytes": os.path.getsize(src),
                    "sha256": _sha256_file(src),
                }
            )

        schema_json_path = os.path.join(bundle_root, "schema", "ln2_import_schema.json")
        with open(schema_json_path, "w", encoding="utf-8") as handle:
            json.dump(_build_schema_payload(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        _write_text(os.path.join(bundle_root, "schema", "validation_rules.md"), _build_rules_markdown())
        _write_text(os.path.join(bundle_root, "templates", "prompt_en.md"), _build_prompt_en())
        _write_text(os.path.join(bundle_root, "templates", "prompt_cn.md"), _build_prompt_zh())
        _write_text(os.path.join(bundle_root, "examples", "valid_inventory_min.yaml"), _build_example_yaml())
        _write_text(
            os.path.join(bundle_root, "output", "README.md"),
            "Put generated `ln2_inventory.yaml` in this directory.\n",
        )

        manifest = {
            "bundle_version": _BUNDLE_VERSION,
            "created_at_utc": _utc_iso(),
            "required_output_path": _REQUIRED_OUTPUT_PATH,
            "source_count": len(manifest_sources),
            "source_files": manifest_sources,
            "options": dict(options or {}),
            "warnings": list(warnings),
        }
        manifest_path = os.path.join(bundle_root, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, names in os.walk(bundle_root):
                for name in sorted(names):
                    abs_path = os.path.join(root, name)
                    rel_path = os.path.relpath(abs_path, bundle_root).replace("\\", "/")
                    archive.write(abs_path, arcname=rel_path)

        return {
            "ok": True,
            "bundle_path": output_zip,
            "manifest": manifest,
            "warnings": list(warnings),
        }
    except Exception as exc:
        return _bundle_error(
            "bundle_export_failed",
            f"Failed to build import task bundle: {exc}",
            warnings=warnings,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
