#!/usr/bin/env python3
"""
Query thaw/takeout events by date or date range.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.tool_api import tool_query_thaw_events
from lib.validators import format_chinese_date
from lib.thaw_parser import (
    format_positions,
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

    response = tool_query_thaw_events(
        yaml_path=args.yaml,
        date=args.date,
        days=args.days,
        start_date=args.start_date,
        end_date=args.end_date,
        action=args.action,
        max_records=args.max,
    )
    if not response.get("ok"):
        print(f"❌ 错误: {response.get('message', '查询失败')}")
        return 1

    payload = response["result"]
    mode = payload["mode"]
    target_dates = payload.get("target_dates")
    date_range = payload.get("date_range")
    action_filter = payload.get("action_filter")
    matched = payload.get("records", [])
    record_count = payload.get("record_count", len(matched))
    display_count = payload.get("display_count", len(matched))
    total_events = payload.get("event_count", 0)

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
    print(f"✅ 匹配记录: {record_count} | 匹配事件: {total_events}")

    if not matched:
        return 0

    if record_count > display_count:
        print(f"⚠️  仅显示前 {display_count} 条记录（共 {record_count} 条）")

    for item in matched:
        rec = item["record"]
        events = item["events"]
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
