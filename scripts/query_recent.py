#!/usr/bin/env python3
"""
查询最近冻存或取出的记录
支持按天数或条数查询，按日期排序显示
"""

import argparse
import sys
import os
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.tool_api import tool_get_raw_entries, tool_recent_frozen
from lib.validators import format_chinese_date
from lib.thaw_parser import format_positions


def get_thaw_summary(rec):
    """获取取出/复苏记录的摘要"""
    thaw_log = rec.get("thaw_log")
    if not thaw_log or thaw_log == "null":
        return None

    # 简化显示：只取第一条记录
    lines = str(thaw_log).strip().split('\n')
    if lines:
        return lines[0][:50]  # 限制长度
    return None


def main():
    parser = argparse.ArgumentParser(
        description="查询最近冻存或取出的记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 查询最近30天冻存的细胞
  query_recent.py --frozen --days 30

  # 查询最近10条冻存记录
  query_recent.py --frozen --count 10

  # 查询所有记录（默认显示最近10条）
  query_recent.py --frozen

  # 显示详细信息（包括取出记录）
  query_recent.py --frozen --days 30 --verbose
        """
    )

    parser.add_argument(
        "--yaml",
        default=YAML_PATH,
        help="YAML 文件路径"
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help="查询冻存记录（默认）"
    )
    parser.add_argument(
        "--days",
        type=int,
        help="查询最近N天的记录"
    )
    parser.add_argument(
        "--count",
        type=int,
        help="查询最近N条记录（默认10条）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细信息（包括质粒、取出记录等）"
    )
    parser.add_argument(
        "--raw", "-r",
        action="store_true",
        help="显示原始 YAML 数据"
    )

    args = parser.parse_args()

    # 默认查询冻存记录
    if not args.frozen:
        args.frozen = True

    # 查询冻存记录
    if args.frozen:
        response = tool_recent_frozen(args.yaml, days=args.days, count=args.count)
        if not response.get("ok"):
            print(f"[ERROR] 错误: {response.get('message', '查询失败')}")
            return 1
        results = response["result"]["records"]

        if not results:
            print("[ERROR] 未找到符合条件的冻存记录")
            return 1

        # 显示标题
        if args.days:
            print(f"[BOX] 最近 {args.days} 天冻存的记录")
        elif args.count:
            print(f"[BOX] 最近 {args.count} 条冻存记录")
        else:
            print("[BOX] 最近 10 条冻存记录")

        print(f"[OK] 找到 {len(results)} 条记录\n")

        # 按日期分组显示
        current_date = None
        for rec in results:
            frozen_at = rec.get("frozen_at")

            # 日期分隔
            if frozen_at != current_date:
                current_date = frozen_at
                print(f"\n{'='*60}")
                print(f"[DATE] {frozen_at} ({format_chinese_date(frozen_at)})")
                print('='*60)

            # 基本信息
            print(f"\n[RECORD] ID {rec.get('id'):3d} | {rec.get('parent_cell_line')} | {rec.get('short_name')}")
            print(f"   盒 {rec.get('box')} | 位置: {format_positions(rec.get('positions'))}")

            # 详细信息
            if args.verbose:
                plasmid = rec.get('plasmid_name')
                if plasmid:
                    print(f"   质粒: {plasmid}")

                plasmid_id = rec.get('plasmid_id')
                if plasmid_id:
                    print(f"   质粒ID: {plasmid_id}")

                note = rec.get('note')
                if note:
                    print(f"   备注: {note}")

                thaw_summary = get_thaw_summary(rec)
                if thaw_summary:
                    print(f"   [TAKEOUT] {thaw_summary}")

        print("\n")

        # 显示原始数据
        if args.raw:
            print("="*60)
            print("[PREVIEW] 原始 YAML 数据:")
            print("="*60 + "\n")

            ids = [rec['id'] for rec in results]
            raw_response = tool_get_raw_entries(args.yaml, ids)
            if not raw_response.get("ok"):
                print(f"[ERROR] {raw_response.get('message', '获取原始数据失败')}")
                return 1

            for i, entry in enumerate(raw_response["result"]["entries"]):
                if i > 0:
                    print()
                print(f"# === ID {entry['id']} ===")
                yaml_str = yaml.dump([entry], allow_unicode=True, default_flow_style=False, sort_keys=False)
                lines = yaml_str.split('\n')
                if lines and lines[0].startswith('- '):
                    lines[0] = lines[0][2:]
                for line in lines:
                    if line:
                        if line.startswith('  '):
                            print(line[2:])
                        else:
                            print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
