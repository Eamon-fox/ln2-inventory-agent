#!/usr/bin/env python3
"""
批量记录多个冻存管的取出/复苏操作
"""
import argparse
import sys

# Import from lib
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.config import YAML_PATH
from lib.yaml_ops import load_yaml, write_yaml
from lib.validators import validate_date
from lib.operations import find_record_by_id
from lib.thaw_parser import normalize_action, ACTION_LABEL


def parse_entries(entries_str):
    """
    解析批量输入格式: "id1:pos1,id2:pos2,..."

    例如: "182:23,183:41,184:43"
    返回: [(182, 23), (183, 41), (184, 43)]
    """
    result = []
    try:
        for entry in entries_str.split(","):
            entry = entry.strip()
            if not entry:
                continue
            record_id, position = entry.split(":")
            result.append((int(record_id), int(position)))
    except Exception as e:
        raise ValueError(f"输入格式错误: {e}. 正确格式示例: '182:23,183:41,184:43'")
    return result


def batch_thaw(yaml_path, entries, date_str, action="取出", note=None, dry_run=False):
    """
    批量记录取出操作

    Args:
        yaml_path: YAML文件路径
        entries: [(record_id, position), ...] 列表
        date_str: 日期 YYYY-MM-DD
        action: 操作类型（取出/复苏/扔掉）
        note: 备注信息（可选）
        dry_run: 是否只预览不实际修改
    """
    # 验证参数
    if not validate_date(date_str):
        print(f"❌ 错误: 日期格式无效，请使用 YYYY-MM-DD 格式（如 2026-01-08）")
        return 1

    if not entries:
        print(f"❌ 错误: 未指定任何取出操作")
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

    # 验证所有操作
    operations = []
    errors = []

    for record_id, position in entries:
        # 验证位置范围
        if position <= 0 or position > 81:
            errors.append(f"ID {record_id}: 位置编号 {position} 必须在 1-81 之间")
            continue

        # 查找记录
        idx, record = find_record_by_id(records, record_id)
        if record is None:
            errors.append(f"ID {record_id}: 未找到该记录")
            continue

        # 验证位置是否存在
        positions = record.get("positions", [])
        if position not in positions:
            errors.append(f"ID {record_id}: 位置 {position} 不在现有位置 {positions} 中")
            continue

        operations.append({
            "idx": idx,
            "record_id": record_id,
            "record": record,
            "position": position,
            "old_positions": positions.copy(),
            "new_positions": [p for p in positions if p != position]
        })

    # 如果有错误，显示并退出
    if errors:
        print(f"\n❌ 发现 {len(errors)} 个错误:\n")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")
        print()
        return 1

    # 显示预览
    print(f"\n{'=' * 70}")
    print(f"📋 批量操作预览 - 共 {len(operations)} 个操作")
    print(f"{'=' * 70}")
    print(f"日期: {date_str}")
    print(f"操作: {action_cn}")
    if note:
        print(f"备注: {note}")
    print()

    for i, op in enumerate(operations, 1):
        rec = op["record"]
        print(f"{i}. ID={op['record_id']}: {rec.get('parent_cell_line')} - {rec.get('short_name')}")
        print(f"   盒子 {rec.get('box')}, 取出位置 {op['position']}")
        print(f"   位置: {op['old_positions']} → {op['new_positions']}")
        print()

    print(f"{'=' * 70}\n")

    if dry_run:
        print("ℹ️  这是预览模式，未实际修改文件")
        print("   移除 --dry-run 参数以执行实际修改\n")
        return 0

    # 执行批量更新
    try:
        success_count = 0
        for op in operations:
            idx = op["idx"]
            position = op["position"]
            record = op["record"]

            # 更新位置列表
            records[idx]["positions"] = op["new_positions"]

            # 追加到 thaw_events
            new_event = {"date": date_str, "action": action_en, "positions": [position]}
            if note:
                new_event["note"] = note
            if records[idx].get("thaw_events") is None:
                records[idx]["thaw_events"] = []
            records[idx]["thaw_events"].append(new_event)

            success_count += 1

        # 写入文件
        write_yaml(
            data,
            yaml_path,
            audit_meta={
                "action": "batch_thaw",
                "source": "scripts/batch_thaw.py",
                "details": {
                    "count": len(operations),
                    "action": action_en,
                    "date": date_str,
                    "record_ids": [op["record_id"] for op in operations],
                },
            },
        )

        print(f"✅ 成功！已更新 {success_count} 条记录")
        print(f"✅ 占用位置信息已自动重建\n")
        return 0

    except Exception as e:
        print(f"❌ 错误: 批量更新失败: {e}")
        print(f"⚠️  数据可能处于不一致状态，请检查 YAML 文件")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="批量记录液氮罐冻存管的取出操作",
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

  # 预览模式（不实际修改）
  python batch_thaw.py \\
    --entries "182:23,183:41" \\
    --date 2026-01-08 \\
    --dry-run

输入格式:
  --entries "id1:position1,id2:position2,..."
  例如: "182:23,183:41,184:43"
        """
    )

    parser.add_argument(
        "--entries",
        type=str,
        required=True,
        help="批量操作列表，格式: 'id1:pos1,id2:pos2,...'（必填）"
    )
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
