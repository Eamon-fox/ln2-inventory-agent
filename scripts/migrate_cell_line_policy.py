"""CLI helper: normalize cell_line required/options policy and legacy values."""

from __future__ import annotations

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lib.migrate_cell_line_policy import migrate_cell_line_policy  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize cell_line policy in LN2 YAML: "
            "set cell_line_required default, add Unknown option, and migrate empty legacy values."
        ),
    )
    parser.add_argument(
        "yaml_path",
        help="Path to ln2_inventory.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing file.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable write backup (not recommended).",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = migrate_cell_line_policy(
        yaml_path=args.yaml_path,
        dry_run=bool(args.dry_run),
        auto_backup=not bool(args.no_backup),
        audit_source="cli.migrate_cell_line_policy",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
