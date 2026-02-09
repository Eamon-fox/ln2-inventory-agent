#!/usr/bin/env python3
"""
查询最近冻存或取出的记录
支持按天数或条数查询，按日期排序显示
"""

import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH
from lib.validators import parse_date, format_chinese_date
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


def query_recent_frozen(records, days=None, count=None):
    """
    查询最近冻存的记录

    Args:
        records: 所有记录
        days: 查询最近N天（优先级高）
        count: 查询最近N条

    Returns:
        按日期降序排列的记录列表
    """
    # 过滤有效记录
    valid_records = []
    for rec in records:
        frozen_at = rec.get("frozen_at")
        if not frozen_at:
            continue
        dt = parse_date(frozen_at)
        if not dt:
            continue
        valid_records.append((dt, rec))

    # 按日期降序排序
    valid_records.sort(key=lambda x: x[0], reverse=True)

    # 按天数过滤
    if days is not None:
        cutoff_date = datetime.now() - timedelta(days=days)
        filtered = [(dt, rec) for dt, rec in valid_records if dt >= cutoff_date]
        return [rec for dt, rec in filtered]

    # 按条数限制
    if count is not None:
        return [rec for dt, rec in valid_records[:count]]

    # 默认返回最近10条
    return [rec for dt, rec in valid_records[:10]]


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

    # 加载数据
    data = load_yaml(args.yaml)
    records = data.get("inventory", [])

    # 默认查询冻存记录
    if not args.frozen:
        args.frozen = True

    # 查询冻存记录
    if args.frozen:
        results = query_recent_frozen(records, days=args.days, count=args.count)

        if not results:
            print("❌ 未找到符合条件的冻存记录")
            return 1

        # 显示标题
        if args.days:
            print(f"📦 最近 {args.days} 天冻存的记录")
        elif args.count:
            print(f"📦 最近 {args.count} 条冻存记录")
        else:
            print("📦 最近 10 条冻存记录")

        print(f"✅ 找到 {len(results)} 条记录\n")

        # 按日期分组显示
        current_date = None
        for rec in results:
            frozen_at = rec.get("frozen_at")

            # 日期分隔
            if frozen_at != current_date:
                current_date = frozen_at
                print(f"\n{'='*60}")
                print(f"📅 {frozen_at} ({format_chinese_date(frozen_at)})")
                print('='*60)

            # 基本信息
            print(f"\n🧬 ID {rec.get('id'):3d} | {rec.get('parent_cell_line')} | {rec.get('short_name')}")
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
                    print(f"   📤 {thaw_summary}")

        print("\n")

        # 显示原始数据
        if args.raw:
            print("="*60)
            print("📋 原始 YAML 数据:")
            print("="*60 + "\n")

            ids = [rec['id'] for rec in results]
            import subprocess
            from lib.config import PYTHON_PATH, SCRIPTS_DIR

            cmd = [
                PYTHON_PATH,
                os.path.join(SCRIPTS_DIR, "show_raw.py")
            ] + [str(i) for i in ids]

            subprocess.run(cmd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
