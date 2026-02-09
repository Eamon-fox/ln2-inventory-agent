#!/usr/bin/env python3
"""
显示液氮罐操作时间线
包括冻存和取出操作的历史记录
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH
from lib.validators import format_chinese_date
from lib.thaw_parser import extract_events


def extract_thaw_events(rec):
    """从记录中提取取出/复苏事件，附带 record 引用"""
    raw_events = extract_events(rec)
    # Attach record reference for display
    return [
        {**ev, "record": rec}
        for ev in raw_events
    ]


def collect_timeline_events(records, days=None):
    """
    收集所有冻存和取出事件

    Returns:
        dict: {date: {"frozen": [...], "thaw": [...], "takeout": [...], "discard": [...]}}
    """
    timeline = defaultdict(lambda: {
        "frozen": [],
        "thaw": [],
        "takeout": [],
        "discard": []
    })

    # 设置日期过滤
    if days:
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    else:
        cutoff_str = None

    # 收集冻存事件
    for rec in records:
        frozen_at = rec.get("frozen_at")
        if not frozen_at:
            continue
        if cutoff_str and frozen_at < cutoff_str:
            continue

        timeline[frozen_at]["frozen"].append(rec)

    # 收集取出事件
    for rec in records:
        thaw_events = extract_thaw_events(rec)
        for event in thaw_events:
            date = event["date"]
            if not date:
                continue
            if cutoff_str and date < cutoff_str:
                continue

            action = event["action"]
            timeline[date][action].append(event)

    return timeline


def display_timeline(timeline, verbose=False):
    """显示时间线"""
    if not timeline:
        print("❌ 未找到任何操作记录")
        return

    # 按日期降序排序
    sorted_dates = sorted(timeline.keys(), reverse=True)

    print(f"\n{'='*70}")
    print(f"📅 操作时间线")
    print(f"{'='*70}\n")

    for date in sorted_dates:
        events = timeline[date]
        date_cn = format_chinese_date(date, weekday=True)

        # 统计操作数量
        frozen_count = len(events["frozen"])
        thaw_count = len(events["thaw"])
        takeout_count = len(events["takeout"])
        discard_count = len(events["discard"])

        # 跳过没有操作的日期
        if frozen_count + thaw_count + takeout_count + discard_count == 0:
            continue

        print(f"\n{date} ({date_cn})")
        print("-" * 70)

        # 显示冻存操作
        if frozen_count > 0:
            print(f"  ❄️  冻存: {frozen_count} 管")
            if verbose:
                for rec in events["frozen"][:5]:  # 最多显示5条
                    print(f"      • {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if frozen_count > 5:
                    print(f"      ... 还有 {frozen_count - 5} 条")

        # 显示复苏操作
        if thaw_count > 0:
            print(f"  🧪 复苏: {thaw_count} 管")
            if verbose:
                for event in events["thaw"][:5]:
                    rec = event["record"]
                    print(f"      • {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if thaw_count > 5:
                    print(f"      ... 还有 {thaw_count - 5} 条")

        # 显示取出操作
        if takeout_count > 0:
            print(f"  📤 取出: {takeout_count} 管")
            if verbose:
                for event in events["takeout"][:5]:
                    rec = event["record"]
                    print(f"      • {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if takeout_count > 5:
                    print(f"      ... 还有 {takeout_count - 5} 条")

        # 显示扔掉操作
        if discard_count > 0:
            print(f"  🗑️  扔掉: {discard_count} 管")
            if verbose:
                for event in events["discard"][:5]:
                    rec = event["record"]
                    print(f"      • {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if discard_count > 5:
                    print(f"      ... 还有 {discard_count - 5} 条")

    print("\n")


def display_summary(timeline):
    """显示统计摘要"""
    total_frozen = 0
    total_thaw = 0
    total_takeout = 0
    total_discard = 0

    for date, events in timeline.items():
        total_frozen += len(events["frozen"])
        total_thaw += len(events["thaw"])
        total_takeout += len(events["takeout"])
        total_discard += len(events["discard"])

    total_ops = total_frozen + total_thaw + total_takeout + total_discard
    active_days = len([d for d, e in timeline.items()
                       if len(e["frozen"]) + len(e["thaw"]) + len(e["takeout"]) + len(e["discard"]) > 0])

    print(f"{'='*70}")
    print(f"📊 统计摘要")
    print(f"{'='*70}")
    print(f"  总操作天数: {active_days} 天")
    print(f"  总操作次数: {total_ops} 次")
    print(f"    ❄️  冻存: {total_frozen} 管")
    print(f"    🧪 复苏: {total_thaw} 管")
    print(f"    📤 取出: {total_takeout} 管")
    print(f"    🗑️  扔掉: {total_discard} 管")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="显示液氮罐操作时间线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 显示最近30天的操作
  timeline.py --days 30

  # 显示最近7天的详细操作
  timeline.py --days 7 --verbose

  # 显示所有历史操作
  timeline.py --all

  # 显示统计摘要
  timeline.py --days 30 --summary
        """
    )

    parser.add_argument(
        "--yaml",
        default=YAML_PATH,
        help="YAML 文件路径"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="显示最近N天的操作（默认30天）"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="显示所有历史操作（忽略 --days）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细信息（细胞名称）"
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="显示统计摘要"
    )

    args = parser.parse_args()

    # 加载数据
    data = load_yaml(args.yaml)
    records = data.get("inventory", [])

    # 收集时间线事件
    if args.all:
        timeline = collect_timeline_events(records, days=None)
    else:
        timeline = collect_timeline_events(records, days=args.days)

    # 显示时间线
    display_timeline(timeline, verbose=args.verbose)

    # 显示统计摘要
    if args.summary:
        display_summary(timeline)

    return 0


if __name__ == "__main__":
    sys.exit(main())
