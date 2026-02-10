#!/usr/bin/env python3
"""
批量记录多个冻存管的取出/复苏/扔掉/移动操作
"""
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.tool_api import (
    build_actor_context,
    parse_batch_entries,
    tool_batch_thaw,
)


def parse_entries(entries_str):
    """兼容旧名称，内部转发到 unified Tool API 解析器。"""
    return parse_batch_entries(entries_str)


def batch_thaw(yaml_path, entries, date_str, action="取出", note=None, dry_run=False):
    """批量记录取出/复苏/扔掉/移动（CLI wrapper for unified Tool API）。"""
    actor_context = build_actor_context(actor_type="human", channel="cli")
    result = tool_batch_thaw(
        yaml_path=yaml_path,
        entries=entries,
        date_str=date_str,
        action=action,
        note=note,
        dry_run=dry_run,
        actor_context=actor_context,
        source="scripts/batch_thaw.py",
    )

    if not result.get("ok"):
        if result.get("error_code") == "validation_failed":
            errors = result.get("errors", [])
            print(f"\n❌ 发现 {len(errors)} 个错误:\n")
            for i, err in enumerate(errors, 1):
                print(f"  {i}. {err}")
            print()
        else:
            print(f"❌ 错误: {result.get('message', '批量更新失败')}")
        return 1

    preview = result.get("preview", {})
    operations = preview.get("operations", [])

    print(f"\n{'=' * 70}")
    print(f"📋 批量操作预览 - 共 {preview.get('count', 0)} 个操作")
    print(f"{'=' * 70}")
    print(f"日期: {preview.get('date')}")
    print(f"操作: {preview.get('action_cn')}")
    if preview.get("note"):
        print(f"备注: {preview.get('note')}")
    print()

    for i, op in enumerate(operations, 1):
        print(f"{i}. ID={op.get('record_id')}: {op.get('parent_cell_line')} - {op.get('short_name')}")
        to_pos = op.get("to_position")
        if to_pos is not None:
            print(f"   盒子 {op.get('box')}, 移动 {op.get('position')} -> {to_pos}")
        else:
            print(f"   盒子 {op.get('box')}, 取出位置 {op.get('position')}")
        print(f"   位置: {op.get('old_positions')} → {op.get('new_positions')}")
        print()

    print(f"{'=' * 70}\n")

    if result.get("dry_run"):
        print("ℹ️  这是预览模式，未实际修改文件")
        print("   移除 --dry-run 参数以执行实际修改\n")
        return 0

    count = result.get("result", {}).get("count", 0)
    print(f"✅ 成功！已更新 {count} 条记录")
    print("✅ 占用位置信息已自动重建\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="批量记录液氮罐冻存管操作（取出/复苏/扔掉/移动）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 批量记录5个细胞系的取出操作
  python batch_thaw.py \\
    --entries "182:23,183:41,184:43,186:59,187:72" \\
    --date 2026-01-08

  # 带备注的批量取出
  python batch_thaw.py \\
    --entries "182:23,183:41" \\
    --date 2026-01-08 \\
    --note "复苏培养"

  # 批量记录移动整理（真实换位/搬移）
  python batch_thaw.py \\
    --entries "182:23->31,183:41->42" \\
    --date 2026-01-08 \\
    --action move \\
    --note "盘点整理"

  # 预览模式（不实际修改）
  python batch_thaw.py \\
    --entries "182:23,183:41" \\
    --date 2026-01-08 \\
    --dry-run

输入格式:
  --entries "id1:position1,id2:position2,..."
  --entries "id1:from1->to1,id2:from2->to2,..."  # move
  例如: "182:23,183:41,184:43" 或 "182:23->31,183:41->42"
        """
    )

    parser.add_argument(
        "--entries",
        type=str,
        required=True,
        help="批量操作列表，格式: 'id1:pos1,id2:pos2,...' 或 'id1:from->to,...'（必填）"
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="日期 YYYY-MM-DD 格式（必填，如 2026-01-08）"
    )
    parser.add_argument("--note", type=str, help="备注信息（可选，如：复苏、送人、扔掉、移动整理）")
    parser.add_argument("--action", type=str, default="取出", help="操作类型（取出/复苏/扔掉/移动，默认取出）")
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")

    args = parser.parse_args()

    # 解析输入
    try:
        entries = parse_entries(args.entries)
    except ValueError as e:
        print(f"❌ 错误: {e}\n")
        parser.print_help()
        return 1

    return batch_thaw(
        args.yaml,
        entries,
        args.date,
        action=args.action,
        note=args.note,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
