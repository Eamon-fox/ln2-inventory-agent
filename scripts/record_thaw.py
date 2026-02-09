#!/usr/bin/env python3
"""
记录单个冻存管的取出/复苏操作
"""
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.yaml_ops import load_yaml, write_yaml
from lib.validators import validate_date, format_chinese_date
from lib.operations import find_record_by_id
from lib.thaw_parser import normalize_action, ACTION_LABEL


def record_thaw(yaml_path, record_id, position, date_str, action="取出", note=None, dry_run=False):
    """
    记录取出操作

    Args:
        yaml_path: YAML文件路径
        record_id: 记录ID
        position: 取出的位置编号
        date_str: 日期 YYYY-MM-DD
        action: 操作类型（取出/复苏/扔掉）
        note: 备注信息（可选）
        dry_run: 是否只预览不实际修改
    """
    # 验证参数
    if not validate_date(date_str):
        print(f"❌ 错误: 日期格式无效，请使用 YYYY-MM-DD 格式（如 2026-01-08）")
        return 1

    if position <= 0 or position > 81:
        print(f"❌ 错误: 位置编号必须在 1-81 之间")
        return 1

    action_en = normalize_action(action)
    if not action_en:
        print(f"❌ 错误: 操作类型必须是 取出/复苏/扔掉")
        return 1
    action_cn = ACTION_LABEL.get(action_en, action)

    # 加载数据
    try:
        data = load_yaml(yaml_path)
    except Exception as e:
        print(f"❌ 错误: 无法读取YAML文件: {e}")
        return 1

    records = data.get("inventory", [])

    # 查找记录
    idx, record = find_record_by_id(records, record_id)
    if record is None:
        print(f"❌ 错误: 未找到 ID={record_id} 的记录")
        return 1

    # 验证位置是否存在
    positions = record.get("positions", [])
    if position not in positions:
        print(f"❌ 错误: 位置 {position} 不在记录 #{record_id} 的现有位置中")
        print(f"   当前位置: {positions}")
        return 1

    # 准备更新
    chinese_date = format_chinese_date(date_str)
    new_positions = [p for p in positions if p != position]

    # 构建新的 thaw event
    new_event = {"date": date_str, "action": action_en, "positions": [position]}
    if note:
        new_event["note"] = note

    # 显示预览
    print(f"\n{'=' * 60}")
    print(f"📋 操作预览")
    print(f"{'=' * 60}")
    print(f"记录ID:      {record_id}")
    print(f"细胞系:      {record.get('parent_cell_line')} - {record.get('short_name')}")
    print(f"盒子:        {record.get('box')}")
    print(f"操作:        {action_cn} 位置 {position}")
    if note:
        print(f"备注:        {note}")
    print(f"日期:        {date_str} ({chinese_date})")
    print(f"\n位置变化:")
    print(f"  修改前:    {positions}")
    print(f"  修改后:    {new_positions}")
    print(f"{'=' * 60}\n")

    if dry_run:
        print("ℹ️  这是预览模式，未实际修改文件")
        print("   移除 --dry-run 参数以执行实际修改\n")
        return 0

    # 执行更新
    try:
        records[idx]["positions"] = new_positions

        # 追加到 thaw_events
        if records[idx].get("thaw_events") is None:
            records[idx]["thaw_events"] = []
        records[idx]["thaw_events"].append(new_event)

        # 写入文件
        write_yaml(
            data,
            yaml_path,
            audit_meta={
                "action": "record_thaw",
                "source": "scripts/record_thaw.py",
                "details": {
                    "record_id": record_id,
                    "box": record.get("box"),
                    "position": position,
                    "action": action_en,
                    "date": date_str,
                },
            },
        )

        print("✅ 成功！取出记录已更新")
        print(f"✅ 占用位置信息已自动重建")
        print(f"\n剩余位置: {new_positions if new_positions else '无（所有管子已取出）'}\n")
        return 0

    except Exception as e:
        print(f"❌ 错误: 更新失败: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="记录液氮罐冻存管的取出操作",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 记录取出操作
  python record_thaw.py --id 182 --position 23 --date 2026-01-08

  # 带备注的取出操作
  python record_thaw.py --id 182 --position 23 --date 2026-01-08 --note "复苏培养"

  # 预览模式（不实际修改）
  python record_thaw.py --id 182 --position 23 --date 2026-01-08 --dry-run
        """
    )

    parser.add_argument("--id", type=int, required=True, help="记录ID（必填）")
    parser.add_argument("--position", type=int, required=True, help="取出的位置编号 1-81（必填）")
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="日期 YYYY-MM-DD 格式（必填，如 2026-01-08）"
    )
    parser.add_argument("--note", type=str, help="备注信息（可选，如：复苏、送人、扔掉）")
    parser.add_argument("--action", type=str, default="取出", help="操作类型（取出/复苏/扔掉，默认取出）")
    parser.add_argument("--yaml", default=YAML_PATH, help="YAML文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")

    args = parser.parse_args()

    return record_thaw(
        args.yaml,
        args.id,
        args.position,
        args.date,
        action=args.action,
        note=args.note,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    sys.exit(main())
