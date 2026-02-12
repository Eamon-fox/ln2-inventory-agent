#!/usr/bin/env python3
"""
记录单个冻存管的取出/复苏/扔掉/移动操作
"""
import argparse
import sys

import _bootstrap

from lib.config import YAML_PATH
from lib.tool_api import build_actor_context, tool_record_thaw
from lib.validators import format_chinese_date


def record_thaw(yaml_path, record_id, position, date_str, action="取出", note=None, to_position=None, dry_run=False):
    """记录取出/复苏/扔掉/移动（CLI wrapper for unified Tool API）。"""
    actor_context = build_actor_context(actor_type="human", channel="cli")
    result = tool_record_thaw(
        yaml_path=yaml_path,
        record_id=record_id,
        position=position,
        date_str=date_str,
        action=action,
        note=note,
        to_position=to_position,
        dry_run=dry_run,
        actor_context=actor_context,
        source="scripts/record_thaw.py",
    )

    if not result.get("ok"):
        message = result.get("message", "更新失败")
        print(f"[ERROR] 错误: {message}")
        current_positions = result.get("current_positions")
        if current_positions is not None:
            print(f"   当前位置: {current_positions}")
        return 1

    preview = result.get("preview", {})
    action_cn = preview.get("action_cn", action)
    chinese_date = format_chinese_date(preview.get("date"))

    print(f"\n{'=' * 60}")
    print("[PREVIEW] 操作预览")
    print(f"{'=' * 60}")
    print(f"记录ID:      {preview.get('record_id')}")
    print(f"细胞系:      {preview.get('parent_cell_line')} - {preview.get('short_name')}")
    print(f"盒子:        {preview.get('box')}")
    to_pos = preview.get("to_position")
    if to_pos is not None:
        print(f"操作:        {action_cn} {preview.get('position')} -> {to_pos}")
    else:
        print(f"操作:        {action_cn} 位置 {preview.get('position')}")
    if preview.get("note"):
        print(f"备注:        {preview.get('note')}")
    print(f"日期:        {preview.get('date')} ({chinese_date})")
    print("\n位置变化:")
    print(f"  修改前:    {preview.get('positions_before')}")
    print(f"  修改后:    {preview.get('positions_after')}")
    print(f"{'=' * 60}\n")

    if result.get("dry_run"):
        print("[INFO]  这是预览模式，未实际修改文件")
        print("   移除 --dry-run 参数以执行实际修改\n")
        return 0

    remaining = result.get("result", {}).get("remaining_positions")
    print("[OK] 成功！操作记录已更新")
    print("[OK] 占用位置信息已自动重建")
    print(f"\n剩余位置: {remaining if remaining else '无（所有管子已取出）'}\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="记录液氮罐冻存管操作（取出/复苏/扔掉/移动）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 记录取出操作
  python record_thaw.py --id 182 --position 23 --date 2026-01-08

  # 带备注的取出操作
  python record_thaw.py --id 182 --position 23 --date 2026-01-08 --note "复苏培养"

  # 记录移动整理（真实换位/搬移）
  python record_thaw.py --id 182 --position 23 --to-position 31 --date 2026-01-08 --action move --note "移到相邻格"

  # 预览模式（不实际修改）
  python record_thaw.py --id 182 --position 23 --date 2026-01-08 --dry-run
        """
    )

    parser.add_argument("--id", type=int, required=True, help="记录ID（必填）")
    parser.add_argument("--position", type=int, required=True, help="目标记录中的位置编号 1-81（必填）")
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="日期 YYYY-MM-DD 格式（必填，如 2026-01-08）"
    )
    parser.add_argument("--note", type=str, help="备注信息（可选，如：复苏、送人、扔掉、移动整理）")
    parser.add_argument("--action", type=str, default="取出", help="操作类型（取出/复苏/扔掉/移动，默认取出）")
    parser.add_argument("--to-position", type=int, help="移动操作目标位置（action=move 时必填）")
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")

    args = parser.parse_args()

    action_text = str(args.action or "").strip().lower()
    if action_text in {"move", "移动", "整理"} and args.to_position is None:
        print("[ERROR] 错误: action=move 时必须提供 --to-position")
        return 1

    return record_thaw(
        args.yaml,
        args.id,
        args.position,
        args.date,
        action=args.action,
        note=args.note,
        to_position=args.to_position,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
