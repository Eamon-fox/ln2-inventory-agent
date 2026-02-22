"""Build an import task bundle directory for external coding agents.

The bundle is designed for workflows where users hand raw files to an
external assistant (e.g. Codex/Claude Code), then bring back a generated
``ln2_inventory.yaml`` for strict local validation.
"""

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


_BUNDLE_VERSION = "1.1"
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
- To pass strict import mode in this app, include non-empty `cell_line` for every record. If source value is unknown, use `"Unknown"`.

## Position rules

- `position` may be integer or null.
- If `position` is null, record must include valid takeout history in `thaw_events`.
- Active records must not conflict on `(box, position)`. Any active-position conflict is a blocking failure.
- If one source row contains multiple positions (for example `1,2,3`), split it into multiple tube-level records (one inventory item per position).

## Metadata rules

- `meta.custom_fields` is optional.
- If present, each item should be a structured object with `key` (identifier-style) and `type` (for example `str`, `int`, `float`, `date`).
- Optional keys such as `label`, `required`, and `default` are allowed.

## Date rules

- `frozen_at` and thaw-event dates must be `YYYY-MM-DD`.
- If a source date is an Excel serial number (for example `45072`), convert it to `YYYY-MM-DD` before writing output.
- Future dates are invalid.

## Ambiguity rules

- Do not invent missing records, dates, positions, or metadata.
- If source material is ambiguous for required fields, ask clarifying questions before finalizing output.

## Recommended workflow for external agent

1. Read `manifest.json` and parse files listed in `source_files`.
2. Follow `templates/runbook_en.md` in order.
3. Run checks from `templates/acceptance_checklist_en.md`.
4. Produce final YAML at `output/ln2_inventory.yaml` only after blocking checks pass.

## Example outputs

- Minimal reference: `examples/valid_inventory_min.yaml`
- Full reference: `examples/valid_inventory_full.yaml`
"""


def _build_prompt_en() -> str:
    return """# Task: Convert source materials to LN2 inventory YAML

You are given raw source files under `inputs/`.

Authoritative context:
- Treat `manifest.json` as the source of truth.
- Enumerate input files from `manifest.json` -> `source_files`.
- Final output path is exactly `output/ln2_inventory.yaml`.

Hard requirements:
- Keep one inventory item per physical tube (tube-level model).
- Do not invent records, fields, dates, or positions.
- Use `null` only when allowed by `schema/validation_rules.md`.
- Keep active tubes unique on `(box, position)`.
- Ensure every inventory record has non-empty `cell_line`; use `"Unknown"` only when the source truly cannot provide it.
- If required fields are ambiguous, ask clarifying questions before final output.
- If clarification is unavailable, write blockers in `output/conversion_report.md` and avoid fake completion.

Execution discipline:
1. Follow `templates/runbook_en.md` step by step.
2. Complete all blocking checks in `templates/acceptance_checklist_en.md`.
3. Deliver final YAML only after all blocking checks pass.
"""


def _build_runbook_en() -> str:
    return """# LN2 Import Runbook (English)

Follow every phase in order. Do not skip validation.

## Phase 1 - Read task context

1. Open `manifest.json`.
2. Build the exact source file list from `source_files`.
3. Confirm required output path: `output/ln2_inventory.yaml`.

## Phase 2 - Inspect source structure

1. Inspect each listed source file.
2. Identify how required fields map to YAML fields (`id`, `box`, `position`, `frozen_at`).
3. Run quick prechecks before transformation:
   - required-field coverage (`box`, `position`, `frozen_at`, `cell_line`)
   - duplicate active locations on `(box, position)`
   - date parseability and future-date risks
   - custom-field metadata shape (`meta.custom_fields` entries use `key` + `type`)
4. Record unresolved ambiguities before transformation.

## Phase 3 - Design field mapping

1. Define deterministic mapping rules for required fields.
2. Define mapping for optional/custom fields without inventing values.
3. Note assumptions explicitly.

## Phase 4 - Transform data

1. Convert source records into tube-level `inventory[]` records.
2. Normalize dates to `YYYY-MM-DD`.
3. Keep source traceability for uncertain conversions.

## Phase 5 - Validate draft output

1. Run all checks in `templates/acceptance_checklist_en.md`.
2. Fix blocking issues before final delivery.
3. If a blocker cannot be resolved from source data, stop and request clarification.

## Phase 6 - Finalize delivery

1. Write final YAML to `output/ln2_inventory.yaml`.
2. Optionally write `output/conversion_report.md` with assumptions and unresolved blockers.
"""


def _build_acceptance_checklist_en() -> str:
    return """# LN2 Import Acceptance Checklist (English)

Use this checklist before final delivery. Any failed blocking check means output is not ready.

## Blocking checks

- [ ] Output file path is exactly `output/ln2_inventory.yaml`.
- [ ] Top-level keys are exactly `meta` and `inventory`.
- [ ] `meta.box_layout.rows` and `meta.box_layout.cols` are positive integers.
- [ ] Every inventory record has required fields: `id`, `box`, `frozen_at`.
- [ ] Every inventory record has non-empty `cell_line` (`"Unknown"` is acceptable only when source value is truly unavailable).
- [ ] `id` values are unique positive integers.
- [ ] Active tubes do not conflict on `(box, position)`.
- [ ] `frozen_at` and thaw-event dates use `YYYY-MM-DD` and are not future dates.
- [ ] `position` is integer or `null`; `null` is only used when rules allow it.
- [ ] `meta.custom_fields`, if present, uses structured objects with `key` + `type` (optional `label` / `required` / `default`).
- [ ] No invented records or fabricated values were introduced.
- [ ] No unresolved ambiguity remains for required fields.

## Recommended report content (optional)

- Mapping summary from source fields to output fields.
- Assumptions made during conversion.
- Any non-blocking caveats for downstream review.
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
    frozen_at: "2024-01-01"
    cell_line: K562
    note: null
    thaw_events: null
"""


def _build_example_full_yaml() -> str:
    return """meta:
  box_layout:
    rows: 9
    cols: 9
    box_count: 2
    indexing: numeric
  custom_fields:
    - key: batch
      label: Batch
      type: str
      required: false
    - key: operator
      label: Operator
      type: str
      required: false

inventory:
  - id: 1
    box: 1
    position: 1
    frozen_at: "2024-01-10"
    cell_line: K562
    note: "active tube"
    batch: "BATCH-001"
    operator: "alice"
    thaw_events: null

  - id: 2
    box: 1
    position: null
    frozen_at: "2023-11-08"
    cell_line: HeLa
    note: "taken out"
    batch: "BATCH-002"
    operator: "bob"
    thaw_events:
      - action: takeout
        date: "2024-06-17"
        positions: [14]

  - id: 3
    box: 2
    position: 20
    frozen_at: "2024-03-02"
    cell_line: U2OS
    note: null
    batch: "BATCH-003"
    operator: "alice"
    thaw_events:
      - action: move
        date: "2024-04-01"
        positions: [11]
"""


def _bundle_error(error_code: str, message: str, warnings: List[str] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "error_code": str(error_code or "unknown_error"),
        "message": str(message or ""),
        "warnings": list(warnings or []),
    }


def export_import_task_bundle(
    source_paths: Iterable[str],
    output_dir: str,
    options: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Export an import task bundle directory for external conversion agents.

    Args:
        source_paths: Files/directories to include under ``inputs/``.
        output_dir: Destination folder path.
        options: Optional metadata map recorded in ``manifest.json``.

    Returns:
        dict:
            - ok: bool
            - bundle_dir: absolute bundle directory (on success)
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

    bundle_dir = str(output_dir or "").strip()
    if not bundle_dir:
        return _bundle_error("invalid_output_path", "Output directory is required.", warnings=warnings)
    bundle_dir = os.path.abspath(bundle_dir)

    if os.path.exists(bundle_dir) and not os.path.isdir(bundle_dir):
        return _bundle_error(
            "invalid_output_path",
            f"Output path is not a directory: {bundle_dir}",
            warnings=warnings,
        )

    try:
        os.makedirs(bundle_dir, exist_ok=True)
        for rel in ("inputs", "schema", "templates", "examples", "output"):
            os.makedirs(os.path.join(bundle_dir, rel), exist_ok=True)

        used_names: set = set()
        manifest_sources: List[Dict[str, Any]] = []
        for src in files:
            source_name = os.path.basename(src) or "source.bin"
            bundle_name = _dedupe_name(source_name, used_names)
            rel_path = f"inputs/{bundle_name}"
            target = os.path.join(bundle_dir, rel_path.replace("/", os.sep))
            shutil.copy2(src, target)
            manifest_sources.append(
                {
                    "source_path": src,
                    "bundle_path": rel_path,
                    "size_bytes": os.path.getsize(src),
                    "sha256": _sha256_file(src),
                }
            )

        schema_json_path = os.path.join(bundle_dir, "schema", "ln2_import_schema.json")
        with open(schema_json_path, "w", encoding="utf-8") as handle:
            json.dump(_build_schema_payload(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        _write_text(os.path.join(bundle_dir, "schema", "validation_rules.md"), _build_rules_markdown())
        _write_text(os.path.join(bundle_dir, "templates", "prompt_en.md"), _build_prompt_en())
        _write_text(os.path.join(bundle_dir, "templates", "runbook_en.md"), _build_runbook_en())
        _write_text(
            os.path.join(bundle_dir, "templates", "acceptance_checklist_en.md"),
            _build_acceptance_checklist_en(),
        )
        _write_text(os.path.join(bundle_dir, "examples", "valid_inventory_min.yaml"), _build_example_yaml())
        _write_text(os.path.join(bundle_dir, "examples", "valid_inventory_full.yaml"), _build_example_full_yaml())
        _write_text(
            os.path.join(bundle_dir, "output", "README.md"),
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
        manifest_path = os.path.join(bundle_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        return {
            "ok": True,
            "bundle_dir": bundle_dir,
            "manifest": manifest,
            "warnings": list(warnings),
        }
    except Exception as exc:
        return _bundle_error(
            "bundle_export_failed",
            f"Failed to build import task bundle: {exc}",
            warnings=warnings,
        )
