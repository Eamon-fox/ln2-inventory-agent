#!/usr/bin/env python3
"""
显示液氮罐操作时间线
包括冻存和各类出入库操作的历史记录
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.tool_api import tool_collect_timeline
from lib.validators import format_chinese_date


def display_timeline(timeline, verbose=False):
    """显示时间线"""
    if not timeline:
        print("[ERROR] No operation records found")
        return

    # 按日期降序排序
    sorted_dates = sorted(timeline.keys(), reverse=True)

    print(f"\n{'='*70}")
    print(f"[TIMELINE] Operation Timeline")
    print(f"{'='*70}\n")

    for date in sorted_dates:
        events = timeline[date]
        date_cn = format_chinese_date(date, weekday=True)

        # 统计操作数量
        frozen_count = len(events["frozen"])
        thaw_count = len(events["thaw"])
        takeout_count = len(events["takeout"])
        discard_count = len(events["discard"])
        move_count = len(events.get("move", []))

        # 跳过没有操作的日期
        if frozen_count + thaw_count + takeout_count + discard_count + move_count == 0:
            continue

        print(f"\n{date} ({date_cn})")
        print("-" * 70)

        # 显示冻存操作
        if frozen_count > 0:
            print(f"  [FREEZE] Frozen: {frozen_count} tubes")
            if verbose:
                for rec in events["frozen"][:5]:  # 最多显示5条
                    print(f"      - {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if frozen_count > 5:
                    print(f"      ... 还有 {frozen_count - 5} 条")

        # 显示复苏操作
        if thaw_count > 0:
            print(f"  [THAW] Thawed: {thaw_count} tubes")
            if verbose:
                for event in events["thaw"][:5]:
                    rec = event["record"]
                    print(f"      - {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if thaw_count > 5:
                    print(f"      ... 还有 {thaw_count - 5} 条")

        # 显示取出操作
        if takeout_count > 0:
            print(f"  [TAKEOUT] Taken out: {takeout_count} tubes")
            if verbose:
                for event in events["takeout"][:5]:
                    rec = event["record"]
                    print(f"      - {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if takeout_count > 5:
                    print(f"      ... 还有 {takeout_count - 5} 条")

        # 显示扔掉操作
        if discard_count > 0:
            print(f"  [DISCARD] Discarded: {discard_count} tubes")
            if verbose:
                for event in events["discard"][:5]:
                    rec = event["record"]
                    print(f"      - {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if discard_count > 5:
                    print(f"      ... 还有 {discard_count - 5} 条")

        # 显示移动整理操作
        if move_count > 0:
            print(f"  [MOVE] Moved: {move_count} tubes")
            if verbose:
                for event in events["move"][:5]:
                    rec = event["record"]
                    print(f"      - {rec.get('parent_cell_line')} | {rec.get('short_name')}")
                if move_count > 5:
                    print(f"      ... 还有 {move_count - 5} 条")

    print("\n")


def display_summary(timeline):
    """显示统计摘要"""
    total_frozen = 0
    total_thaw = 0
    total_takeout = 0
    total_discard = 0
    total_move = 0

    for date, events in timeline.items():
        total_frozen += len(events["frozen"])
        total_thaw += len(events["thaw"])
        total_takeout += len(events["takeout"])
        total_discard += len(events["discard"])
        total_move += len(events.get("move", []))

    total_ops = total_frozen + total_thaw + total_takeout + total_discard + total_move
    active_days = len([d for d, e in timeline.items()
                       if len(e["frozen"]) + len(e["thaw"]) + len(e["takeout"]) + len(e["discard"]) + len(e.get("move", [])) > 0])

    print(f"{'='*70}")
    print(f"[SUMMARY] Statistics Summary")
    print(f"{'='*70}")
    print(f"  Total operation days: {active_days}")
    print(f"  Total operations: {total_ops}")
    print(f"    [FREEZE] Frozen: {total_frozen} tubes")
    print(f"    [THAW] Thawed: {total_thaw} tubes")
    print(f"    [TAKEOUT] Taken out: {total_takeout} tubes")
    print(f"    [DISCARD] Discarded: {total_discard} tubes")
    print(f"    [MOVE] Moved: {total_move} tubes")
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

    response = tool_collect_timeline(
        yaml_path=args.yaml,
        days=args.days,
        all_history=args.all,
    )
    if not response.get("ok"):
        print(f"[ERROR] Error: {response.get('message', 'Timeline query failed')}")
        return 1

    timeline = response["result"]["timeline"]

    # 显示时间线
    display_timeline(timeline, verbose=args.verbose)

    # 显示统计摘要
    if args.summary:
        display_summary(timeline)

    return 0


if __name__ == "__main__":
    sys.exit(main())
