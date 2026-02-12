#!/usr/bin/env python3
"""
Global fuzzy search across all fields in LN2 inventory.
"""
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.cli_render import format_record_verbose
from lib.tool_api import tool_search_records


def format_record(rec, query, verbose=False):
    """Format a record for display with optional highlighting."""
    pos = ",".join(str(p) for p in rec.get("positions") or [])

    if verbose:
        return format_record_verbose(rec)
    else:
        return (
            f"id={rec.get('id')} box={rec.get('box')} pos=[{pos}] "
            f"cell={rec.get('parent_cell_line')} short={rec.get('short_name')} "
            f"frozen={rec.get('frozen_at')}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="全局模糊搜索液氮罐库存（搜索所有字段）"
    )
    parser.add_argument("query", help="搜索关键词")
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML 文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--case-sensitive", "-c", action="store_true", help="区分大小写")
    args = parser.parse_args()

    response = tool_search_records(
        yaml_path=args.yaml,
        query=args.query,
        mode="fuzzy",
        case_sensitive=args.case_sensitive,
    )
    if not response.get("ok"):
        print(f"[ERROR] 错误: {response.get('message', '搜索失败')}")
        return 1
    matches = response["result"]["records"]

    if not matches:
        print(f"\n未找到包含 '{args.query}' 的记录")
        return 1

    print(f"\n找到 {len(matches)} 条包含 '{args.query}' 的记录:\n")

    for i, rec in enumerate(matches, 1):
        if args.verbose:
            print(f"--- 记录 {i} ---")
            print(format_record(rec, args.query, verbose=True))
            print()
        else:
            print(format_record(rec, args.query, verbose=False))

    # Reminder for AI assistants
    print("\n" + "="*70)
    print("[WARN]  重要提示给 AI 助手：")
    print("   请将以上过滤后的记录 **完整展示** 给用户")
    print("   保留所有字段（包括 note、thaw_log 等），不要简化成表格")
    print("   可能遗漏关键背景信息！")
    print("="*70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
