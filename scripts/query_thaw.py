#!/usr/bin/env python3
"""
Query thaw/takeout events by date or date range.
"""
import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH
from lib.validators import format_chinese_date, normalize_date_arg
from lib.thaw_parser import (
    extract_events, normalize_action, format_positions,
    ACTION_LABEL,
)


def main():
    parser = argparse.ArgumentParser(
        description="Query thaw/takeout events by date or date range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 查询今天的复苏记录
  query_thaw.py --action 复苏

  # 查询特定日期的操作
  query_thaw.py --date 2026-01-08 --action 取出

  # 查询最近7天的所有操作
  query_thaw.py --days 7

  # 查询最近30天的复苏记录
  query_thaw.py --days 30 --action 复苏

  # 查询日期范围
  query_thaw.py --start-date 2026-01-01 --end-date 2026-01-08
        """
    )
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML 文件路径")
    parser.add_argument(
        "--date", default=None,
        help="日期 YYYY-MM-DD（默认今天，可用 'today' 或 '今天'）",
    )
    parser.add_argument(
        "--days", type=int,
        help="查询最近N天的操作（优先级高于 --date）",
    )
    parser.add_argument("--start-date", help="起始日期 YYYY-MM-DD（配合 --end-date 使用）")
    parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD（配合 --start-date 使用）")
    parser.add_argument(
        "--action", default=None,
        help="操作类型（取出/复苏/扔掉 或 takeout/thaw/discard）",
    )
    parser.add_argument(
        "--max", type=int, default=0,
        help="最多显示多少条记录（0 表示不限制）",
    )
    args = parser.parse_args()

    # 处理日期参数
    if args.days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
        target_dates = None
        date_range = (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        mode = "days"
    elif args.start_date and args.end_date:
        start = normalize_date_arg(args.start_date)
        end = normalize_date_arg(args.end_date)
        if not start or not end:
            print("❌ 错误: 日期格式无效，请使用 YYYY-MM-DD")
            return 1
        target_dates = None
        date_range = (start, end)
        mode = "range"
    else:
        target_date = normalize_date_arg(args.date)
        if not target_date:
            print("❌ 错误: 日期格式无效，请使用 YYYY-MM-DD")
            return 1
        target_dates = [target_date]
        date_range = None
        mode = "single"

    action_filter = normalize_action(args.action) if args.action else None
    if args.action and not action_filter:
        print("❌ 错误: 操作类型必须是 取出/复苏/扔掉 或 takeout/thaw/discard")
        return 1

    data = load_yaml(args.yaml)
    records = data.get("inventory", [])

    matched = []
    total_events = 0
    for rec in records:
        events = extract_events(rec)
        if not events:
            continue

        if mode == "single":
            filtered = [
                ev for ev in events
                if ev.get("date") in target_dates
                and (not action_filter or ev.get("action") == action_filter)
            ]
        else:
            filtered = [
                ev for ev in events
                if ev.get("date") and date_range[0] <= ev.get("date") <= date_range[1]
                and (not action_filter or ev.get("action") == action_filter)
            ]

        if filtered:
            matched.append((rec, filtered))
            total_events += len(filtered)

    # 显示查询条件
    if mode == "single":
        date_cn = format_chinese_date(target_dates[0])
        print(f"📅 日期: {target_dates[0]} ({date_cn})")
    elif mode == "days":
        print(f"📅 最近 {args.days} 天 ({date_range[0]} 至 {date_range[1]})")
    else:
        print(f"📅 日期范围: {date_range[0]} 至 {date_range[1]}")

    if action_filter:
        print(f"🎯 操作: {ACTION_LABEL.get(action_filter, action_filter)}")
    print(f"✅ 匹配记录: {len(matched)} | 匹配事件: {total_events}")

    if not matched:
        return 0

    limit = args.max if args.max and args.max > 0 else len(matched)
    shown = matched[:limit]
    if len(matched) > limit:
        print(f"⚠️  仅显示前 {limit} 条记录（共 {len(matched)} 条）")

    for rec, events in shown:
        print(
            f"- id {rec.get('id')} | {rec.get('parent_cell_line')} | {rec.get('short_name')} | "
            f"盒{rec.get('box')} | 冻存 {rec.get('frozen_at')}"
        )
        for ev in events:
            action_label = ACTION_LABEL.get(ev.get("action"), ev.get("action"))
            pos_str = format_positions(ev.get("positions"))
            date_str = ev.get("date") or "未知日期"
            print(f"  {date_str} {action_label} 位置[{pos_str}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
