#!/usr/bin/env python3
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml, compute_occupancy
from lib.config import YAML_PATH


def str_contains(value, query):
    if value is None:
        return False
    return query.lower() in str(value).lower()


def format_record(rec, verbose=False):
    """Format a record for display."""
    pos = ",".join(str(p) for p in rec.get("positions") or [])

    if verbose:
        # Verbose table format
        lines = []
        lines.append(f"{'ID':<15} {rec.get('id')}")
        lines.append(f"{'细胞系':<15} {rec.get('parent_cell_line')}")
        lines.append(f"{'简称':<15} {rec.get('short_name')}")
        lines.append(f"{'质粒':<15} {rec.get('plasmid_name', 'N/A')}")
        lines.append(f"{'质粒ID':<15} {rec.get('plasmid_id')}")
        lines.append(f"{'盒子':<15} {rec.get('box')}")
        lines.append(f"{'位置':<15} [{pos}]")
        lines.append(f"{'冻存日期':<15} {rec.get('frozen_at')}")
        if rec.get('thaw_log'):
            lines.append(f"{'取出记录':<15} {rec.get('thaw_log')}")
        if rec.get('note'):
            lines.append(f"{'备注':<15} {rec.get('note')}")
        return "\n".join(lines)
    else:
        # Compact format
        return (
            f"id={rec.get('id')} box={rec.get('box')} pos=[{pos}] "
            f"parent={rec.get('parent_cell_line')} short={rec.get('short_name')} "
            f"plasmid_id={rec.get('plasmid_id')} frozen_at={rec.get('frozen_at')}"
        )


def filter_records(records, args):
    out = []
    for rec in records:
        if args.cell and not str_contains(rec.get("parent_cell_line"), args.cell):
            continue
        if args.short and not str_contains(rec.get("short_name"), args.short):
            continue
        if args.plasmid and not str_contains(rec.get("plasmid_name"), args.plasmid):
            continue
        if args.plasmid_id and not str_contains(rec.get("plasmid_id"), args.plasmid_id):
            continue
        if args.box is not None and rec.get("box") != args.box:
            continue
        if args.position is not None:
            positions = rec.get("positions") or []
            if args.position not in positions:
                continue
        out.append(rec)
    return out


def list_empty(records, args):
    """List empty positions with better formatting."""
    layout = load_yaml(args.yaml).get("meta", {}).get("box_layout", {})
    total = int(layout.get("rows", 9)) * int(layout.get("cols", 9))
    all_positions = set(range(1, total + 1))
    occupied = compute_occupancy(records)

    if args.box is not None:
        boxes = [str(args.box)]
    else:
        boxes = list(occupied.keys())
        if not boxes:
            boxes = [str(i) for i in range(1, 6)]

    print(f"\n{'盒子':<6} {'空闲位置数':<12} {'空闲位置列表'}")
    print("-" * 60)

    for box in boxes:
        used = set(occupied.get(str(box), []))
        empty = sorted(all_positions - used)
        empty_str = ','.join(str(p) for p in empty)
        if len(empty_str) > 40:
            empty_str = empty_str[:37] + "..."
        print(f"{box:<6} {len(empty):>4}/{total:<7} {empty_str}")


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

    data = load_yaml(args.yaml)
    records = data.get("inventory", [])

    if args.empty:
        list_empty(records, args)
        return 0

    matches = filter_records(records, args)
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

    # Reminder for AI assistants
    print("\n" + "="*70)
    print("⚠️  重要提示给 AI 助手：")
    print("   请将以上过滤后的记录 **完整展示** 给用户")
    print("   保留所有字段（包括 note、thaw_log 等），不要简化成表格")
    print("   可能遗漏关键背景信息！")
    print("="*70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
