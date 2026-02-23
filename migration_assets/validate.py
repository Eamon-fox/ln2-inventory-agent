#!/usr/bin/env python3
"""Validate LN2 inventory YAML generated in this workspace.

Default input:
  ../migrate/output/ln2_inventory.yaml

Default report:
  ../migrate/output/validation_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import yaml
except Exception as exc:  # pragma: no cover - handled at runtime in workspace
    yaml = None
    YAML_IMPORT_ERROR = str(exc)
else:
    YAML_IMPORT_ERROR = ""


def _load_validation_core():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from lib.import_validation_core import utc_iso, validate_inventory_document

        return utc_iso, validate_inventory_document
    except Exception as lib_exc:
        raise ImportError(
            "Cannot import validation core from lib.import_validation_core. "
            "Run this script from the repository where 'lib/' is available. "
            f"Original error: {lib_exc}"
        )


def _read_yaml(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_report(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate migrate/output/ln2_inventory.yaml")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(script_dir, "..", "migrate", "output", "ln2_inventory.yaml")
    default_report = os.path.join(script_dir, "..", "migrate", "output", "validation_report.json")
    parser.add_argument(
        "--input",
        default=default_input,
        help="Path to candidate YAML (default: ../migrate/output/ln2_inventory.yaml)",
    )
    parser.add_argument(
        "--report",
        default=default_report,
        help="Path to JSON report (default: ../migrate/output/validation_report.json)",
    )
    parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Do not fail exit code on warnings.",
    )
    args = parser.parse_args(argv)

    input_path = os.path.abspath(args.input)
    report_path = os.path.abspath(args.report)
    fail_on_warnings = not bool(args.allow_warnings)

    errors = []
    warnings = []
    if yaml is None:
        errors.append(f"PyYAML is required but unavailable: {YAML_IMPORT_ERROR}")
    elif not os.path.isfile(input_path):
        errors.append(f"Candidate YAML not found: {input_path}")
    else:
        try:
            utc_iso, validate_inventory_document = _load_validation_core()
            data = _read_yaml(input_path)
            errors, warnings = validate_inventory_document(data)
        except Exception as exc:
            errors.append(f"Failed to load/parse YAML: {exc}")
            utc_iso = None

    if "utc_iso" not in locals() or utc_iso is None:
        from datetime import datetime, timezone

        def utc_iso():
            return (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )

    blocked = list(errors)
    if fail_on_warnings and warnings:
        blocked.extend([f"Warning treated as error: {w}" for w in warnings])

    ok = len(blocked) == 0
    report = {
        "ok": ok,
        "validated_at_utc": utc_iso(),
        "input_path": input_path,
        "report_path": report_path,
        "strict": {
            "fail_on_warnings": fail_on_warnings,
        },
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }

    try:
        _write_report(report_path, report)
    except Exception as exc:
        # Report writing failure itself should be visible and fail fast.
        print(f"[validate] Failed to write report: {exc}", file=sys.stderr)
        return 1

    status = "PASS" if ok else "FAIL"
    print(
        f"[validate] {status} | errors={len(errors)} warnings={len(warnings)} "
        f"fail_on_warnings={str(fail_on_warnings).lower()}"
    )
    print(f"[validate] input: {input_path}")
    print(f"[validate] report: {report_path}")

    preview_limit = 8
    if errors:
        print("[validate] top errors:")
        for msg in errors[:preview_limit]:
            print(f"  - {msg}")
        if len(errors) > preview_limit:
            print(f"  - ... and {len(errors) - preview_limit} more")
    if warnings:
        print("[validate] top warnings:")
        for msg in warnings[:preview_limit]:
            print(f"  - {msg}")
        if len(warnings) > preview_limit:
            print(f"  - ... and {len(warnings) - preview_limit} more")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

