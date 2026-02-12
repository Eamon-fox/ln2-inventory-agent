#!/usr/bin/env python3
import argparse
import sys

import _bootstrap

from lib.config import YAML_PATH
from lib.cli_render import format_record_verbose, print_ai_record_disclaimer
from lib.tool_api import tool_list_empty_positions, tool_query_inventory


def format_record(rec, verbose=False):
    """Format a record for display."""
    pos = ",".join(str(p) for p in rec.get("positions") or [])

    if verbose:
        return format_record_verbose(rec)
    else:
        # Compact format
        return (
            f"id={rec.get('id')} box={rec.get('box')} pos=[{pos}] "
            f"parent={rec.get('parent_cell_line')} short={rec.get('short_name')} "
            f"plasmid_id={rec.get('plasmid_id')} frozen_at={rec.get('frozen_at')}"
        )


def list_empty(args):
    """List empty positions with better formatting."""
    response = tool_list_empty_positions(args.yaml, box=args.box)
    if not response.get("ok"):
        print(f"[ERROR] 错误: {response.get('message', '查询空位失败')}")
        return 1

    payload = response["result"]
    boxes = payload.get("boxes", [])
    total = payload.get("total_slots", 0)

    print(f"\n{'盒子':<6} {'空闲位置数':<12} {'空闲位置列表'}")
    print("-" * 60)

    for item in boxes:
        box = item["box"]
        empty = item["empty_positions"]
        empty_str = ','.join(str(p) for p in empty)
        if len(empty_str) > 40:
            empty_str = empty_str[:37] + "..."
        print(f"{box:<6} {len(empty):>4}/{total:<7} {empty_str}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Query LN2 inventory YAML")
    parser.add_argument("--yaml", default=YAML_PATH)
    parser.add_argument("--cell", help="substring of parent cell line")
    parser.add_argument("--short", help="substring of short name")
    parser.add_argument("--plasmid", help="substring of plasmid name")
    parser.add_argument("--plasmid-id", help="substring of plasmid id")
    parser.add_argument("--box", type=int, help="box number")
    parser.add_argument("--position", type=int, help="position number")
    parser.add_argument("--empty", action="store_true", help="list empty positions")
    parser.add_argument("--verbose", "-v", action="store_true", help="verbose output format")
    args = parser.parse_args()

    if args.empty:
        return list_empty(args)

    response = tool_query_inventory(
        yaml_path=args.yaml,
        cell=args.cell,
        short=args.short,
        plasmid=args.plasmid,
        plasmid_id=args.plasmid_id,
        box=args.box,
        position=args.position,
    )
    if not response.get("ok"):
        print(f"[ERROR] 错误: {response.get('message', '查询失败')}")
        return 1

    matches = response["result"]["records"]
    if not matches:
        print("未找到匹配记录")
        return 1

    print(f"\n找到 {len(matches)} 条记录:\n")
    for i, rec in enumerate(matches, 1):
        if args.verbose:
            print(f"--- 记录 {i} ---")
            print(format_record(rec, verbose=True))
            print()
        else:
            print(format_record(rec, verbose=False))

    print_ai_record_disclaimer()

    return 0


if __name__ == "__main__":
    sys.exit(main())
